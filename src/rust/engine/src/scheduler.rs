// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};
use std::io;
use std::path::Path;
use std::sync::{Arc, Mutex};

use futures::future::{self, Future};
use futures::sync::oneshot;

use boxfuture::{BoxFuture, Boxable};
use context::{Context, ContextFactory, Core};
use core::{Failure, Key, TypeConstraint, TypeId, Value};
use fs::{self, PosixFS, VFS};
use graph::EntryId;
use nodes::{NodeKey, Select};
use rule_graph;
use selectors;

///
/// A Session represents a related series of requests (generally: one run of the pants CLI) on an
/// underlying Scheduler, and is a useful scope for metrics.
///
/// Both Scheduler and Session are exposed to python and expected to be used by multiple threads, so
/// they use internal mutability in order to avoid exposing locks to callers.
///
pub struct Session {
  // The total size of the graph at Session-creation time.
  preceding_graph_size: usize,
  // The set of roots that have been requested within this session.
  roots: Mutex<HashSet<Root>>,
}

impl Session {
  pub fn new(scheduler: &Scheduler) -> Session {
    Session {
      preceding_graph_size: scheduler.core.graph.len(),
      roots: Mutex::new(HashSet::new()),
    }
  }

  fn extend(&self, new_roots: &[Root]) {
    let mut roots = self.roots.lock().unwrap();
    roots.extend(new_roots.iter().cloned());
  }

  fn root_nodes(&self) -> Vec<NodeKey> {
    let roots = self.roots.lock().unwrap();
    roots.iter().map(|r| r.clone().into()).collect()
  }
}

pub struct ExecutionRequest {
  // Set of roots for an execution, in the order they were declared.
  pub roots: Vec<Root>,
}

impl ExecutionRequest {
  pub fn new() -> ExecutionRequest {
    ExecutionRequest { roots: Vec::new() }
  }

  ///
  /// Roots are limited to `Select`, which is known to produce a Value. This method
  /// exists to satisfy Graph APIs which need instances of the NodeKey enum.
  ///
  fn root_nodes(&self) -> Vec<NodeKey> {
    self.roots.iter().map(|r| r.clone().into()).collect()
  }
}

///
/// Represents the state of an execution of a Graph.
///
pub struct Scheduler {
  pub core: Arc<Core>,
}

impl Scheduler {
  pub fn new(core: Core) -> Scheduler {
    Scheduler {
      core: Arc::new(core),
    }
  }

  pub fn visualize(&self, session: &Session, path: &Path) -> io::Result<()> {
    self.core.graph.visualize(&session.root_nodes(), path)
  }

  pub fn trace(&self, request: &ExecutionRequest, path: &Path) -> io::Result<()> {
    for root in request.root_nodes() {
      self.core.graph.trace(&root, path)?;
    }
    Ok(())
  }

  pub fn add_root_select(
    &self,
    request: &mut ExecutionRequest,
    subject: Key,
    product: TypeConstraint,
  ) -> Result<(), String> {
    let edges = self.find_root_edges_or_update_rule_graph(
      subject.type_id().clone(),
      selectors::Select::without_variant(product),
    )?;
    request
      .roots
      .push(Select::new(product, subject, Default::default(), &edges));
    Ok(())
  }

  fn find_root_edges_or_update_rule_graph(
    &self,
    subject_type: TypeId,
    select: selectors::Select,
  ) -> Result<rule_graph::RuleEdges, String> {
    self
      .core
      .rule_graph
      .find_root_edges(subject_type.clone(), select.clone())
      .ok_or_else(|| {
        format!(
          "No installed rules can satisfy {} for a root subject of type {}.",
          rule_graph::select_str(&select),
          rule_graph::type_str(subject_type)
        )
      })
  }

  ///
  /// Return Scheduler and per-Session metrics.
  ///
  pub fn metrics(&self, session: &Session) -> HashMap<&str, i64> {
    let mut m = HashMap::new();
    m.insert(
      "affected_file_count",
      self
        .core
        .graph
        .reachable_digest_count(&session.root_nodes()) as i64,
    );
    m.insert("preceding_graph_size", session.preceding_graph_size as i64);
    m.insert("resulting_graph_size", self.core.graph.len() as i64);
    m
  }

  ///
  /// Attempts to complete all of the given roots, retrying the entire set (up to `count`
  /// times) if any of them fail with `Failure::Invalidated`.
  ///
  /// In common usage, graph entries won't be repeatedly invalidated, but in a case where they
  /// were (say by an automated process changing files under pants), we'd want to eventually
  /// give up.
  ///
  fn execute_helper(
    core: Arc<Core>,
    roots: Vec<Root>,
    count: usize,
  ) -> BoxFuture<Vec<Result<Value, Failure>>, ()> {
    let executor = core.runtime.get().executor();
    // Attempt all roots in parallel, failing fast to retry for `Invalidated`.
    let roots_res = future::join_all(
      roots
        .clone()
        .into_iter()
        .map(|root| {
          core
            .graph
            .create(root.clone(), &core)
            .then::<_, Result<Result<Value, Failure>, Failure>>(move |r| {
              match r {
                Err(Failure::Invalidated) if count > 0 => {
                  // A node was invalidated: fail quickly so that all roots can be retried.
                  Err(Failure::Invalidated)
                }
                other => {
                  // Otherwise (if it is a success, some other type of Failure, or if we've run
                  // out of retries) recover to complete the join, which will cause the results to
                  // propagate to the user.
                  debug!("Root {} completed.", NodeKey::Select(root).format());
                  Ok(other)
                }
              }
            })
        })
        .collect::<Vec<_>>(),
    );

    // If the join failed (due to `Invalidated`, since that is the only error we propagate), retry
    // the entire set of roots.
    oneshot::spawn(
      roots_res.or_else(move |_| Scheduler::execute_helper(core, roots, count - 1)),
      &executor,
    ).to_boxed()
  }

  ///
  /// Compute the results for roots in the given request.
  ///
  pub fn execute<'e>(
    &self,
    request: &'e ExecutionRequest,
    session: &Session,
  ) -> Vec<(&'e Key, &'e TypeConstraint, RootResult)> {
    // Bootstrap tasks for the roots, and then wait for all of them.
    debug!("Launching {} roots.", request.roots.len());

    session.extend(&request.roots);

    // Wait for all roots to complete. Failure here should be impossible, because each
    // individual Future in the join was (eventually) mapped into success.
    let results = Scheduler::execute_helper(self.core.clone(), request.roots.clone(), 8)
      .wait()
      .expect("Execution failed.");

    request
      .roots
      .iter()
      .zip(results.into_iter())
      .map(|(s, r)| (&s.subject, &s.selector.product, r))
      .collect()
  }

  pub fn capture_snapshot_from_arbitrary_root<P: AsRef<Path>>(
    &self,
    root_path: P,
    path_globs: fs::PathGlobs,
  ) -> BoxFuture<fs::Snapshot, String> {
    // Note that we don't use a Graph here, and don't cache any intermediate steps, we just place
    // the resultant Snapshot into the store and return it. This is important, because we're reading
    // things from arbitrary filepaths which we don't want to cache in the graph, as we don't watch
    // them for changes.
    // We assume that this Snapshot is of an immutable piece of the filesystem.

    let posix_fs = Arc::new(try_future!(PosixFS::new(
      root_path,
      self.core.fs_pool.clone(),
      vec![]
    )));
    let store = self.core.store.clone();

    posix_fs
      .expand(path_globs)
      .map_err(|err| format!("Error expanding globs: {:?}", err))
      .and_then(|path_stats| {
        fs::Snapshot::from_path_stats(
          store.clone(),
          fs::OneOffStoreFileByDigest::new(store, posix_fs),
          path_stats,
        )
      })
      .to_boxed()
  }
}

impl Drop for Scheduler {
  fn drop(&mut self) {
    // Because Nodes may hold references to the Core in their closure, this is intended to
    // break cycles between Nodes and the Core.
    self.core.graph.clear();
  }
}

///
/// Root requests are limited to Selectors that produce (python) Values.
///
type Root = Select;

pub type RootResult = Result<Value, Failure>;

impl ContextFactory for Arc<Core> {
  fn create(&self, entry_id: EntryId) -> Context {
    Context::new(entry_id, self.clone())
  }
}
