// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::{mpsc, Arc};
use std::time::Duration;

use futures::future::{self, Future};

use boxfuture::{BoxFuture, Boxable};
use context::{Context, Core};
use core::{Failure, Key, Params, TypeConstraint, TypeId, Value};
use fs::{self, GlobMatching, PosixFS};
use graph::{EntryId, Graph, Node, NodeContext};
use nodes::{NodeKey, Select, Tracer, TryInto, Visualizer};
use parking_lot::Mutex;
use rule_graph;
use selectors;
use ui::EngineDisplay;

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
    let mut roots = self.roots.lock();
    roots.extend(new_roots.iter().cloned());
  }

  fn root_nodes(&self) -> Vec<NodeKey> {
    let roots = self.roots.lock();
    roots.iter().map(|r| r.clone().into()).collect()
  }
}

pub struct ExecutionRequest {
  // Set of roots for an execution, in the order they were declared.
  pub roots: Vec<Root>,
  // Flag used to determine whether to show engine execution progress.
  pub should_render_ui: bool,
  pub ui_worker_count: u64,
}

impl ExecutionRequest {
  pub fn new(should_render_ui: bool, ui_worker_count: u64) -> ExecutionRequest {
    ExecutionRequest {
      roots: Vec::new(),
      should_render_ui,
      ui_worker_count,
    }
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
    self
      .core
      .graph
      .visualize(Visualizer::default(), &session.root_nodes(), path)
  }

  pub fn trace(&self, request: &ExecutionRequest, path: &Path) -> Result<(), String> {
    self
      .core
      .graph
      .trace::<Tracer>(&request.root_nodes(), path)?;
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
      &selectors::Select::new(product),
    )?;
    request
      .roots
      .push(Select::new(product, Params::new_single(subject), &edges));
    Ok(())
  }

  fn find_root_edges_or_update_rule_graph(
    &self,
    subject_type: TypeId,
    select: &selectors::Select,
  ) -> Result<rule_graph::RuleEdges, String> {
    self
      .core
      .rule_graph
      .find_root_edges(subject_type, select.clone())
      .ok_or_else(|| {
        format!(
          "No installed rules can satisfy {} for a root subject of type {}.",
          rule_graph::select_str(&select),
          rule_graph::type_str(subject_type)
        )
      })
  }

  ///
  /// Invalidate the invalidation roots represented by the given Paths.
  ///
  pub fn invalidate(&self, paths: &HashSet<PathBuf>) -> usize {
    let invalidation_result = self.core.graph.invalidate_from_roots(move |node| {
      if let Some(fs_subject) = node.fs_subject() {
        paths.contains(fs_subject)
      } else {
        false
      }
    });
    // TODO: Expose.
    invalidation_result.cleared + invalidation_result.dirtied
  }

  ///
  /// Invalidate all filesystem dependencies in the graph.
  ///
  pub fn invalidate_all_paths(&self) -> usize {
    let invalidation_result = self
      .core
      .graph
      .invalidate_from_roots(|node| node.fs_subject().is_some());
    // TODO: Expose.
    invalidation_result.cleared + invalidation_result.dirtied
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
  /// times) if any of them fail with `Failure::Invalidated`. Sends the result on the given
  /// mpsc Sender, which allows the caller to poll a channel for the result without blocking
  /// uninterruptibly on a Future.
  ///
  /// In common usage, graph entries won't be repeatedly invalidated, but in a case where they
  /// were (say by an automated process changing files under pants), we'd want to eventually
  /// give up.
  ///
  fn execute_helper(
    context: RootContext,
    sender: mpsc::Sender<Vec<Result<Value, Failure>>>,
    roots: Vec<Root>,
    count: usize,
  ) {
    let executor = context.core.runtime.get().executor();
    // Attempt all roots in parallel, failing fast to retry for `Invalidated`.
    let roots_res = future::join_all(
      roots
        .clone()
        .into_iter()
        .map(|root| {
          context
            .core
            .graph
            .create(root.clone().into(), &context)
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
                  debug!(
                    "Root {} completed.",
                    NodeKey::Select(Box::new(root)).format()
                  );
                  Ok(other.map(|res| {
                    res
                      .try_into()
                      .unwrap_or_else(|_| panic!("A Node implementation was ambiguous."))
                  }))
                }
              }
            })
        }).collect::<Vec<_>>(),
    );

    // If the join failed (due to `Invalidated`, since that is the only error we propagate), retry
    // the entire set of roots.
    executor.spawn(roots_res.then(move |res| {
      if let Ok(res) = res {
        sender.send(res).map_err(|_| ())
      } else {
        Scheduler::execute_helper(context, sender, roots, count - 1);
        Ok(())
      }
    }));
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
    let context = RootContext {
      core: self.core.clone(),
    };
    let (sender, receiver) = mpsc::channel();

    // Setting up display
    let display_worker_count = request.ui_worker_count as usize;
    let mut optional_display = if request.should_render_ui {
      Some(EngineDisplay::for_stdout(0))
    } else {
      None
    };
    if let Some(display) = optional_display.as_mut() {
      display.start();
      display.render();
      let worker_ids: Vec<String> = (0..display_worker_count)
        .map(|s| format!("{}", s))
        .collect();
      for worker_id in worker_ids {
        display.add_worker(worker_id);
        display.render();
      }
    }

    Scheduler::execute_helper(context, sender, request.roots.clone(), 8);
    let roots: Vec<NodeKey> = request
      .roots
      .clone()
      .into_iter()
      .map(|s| s.into())
      .collect();

    let results = loop {
      if let Ok(res) = receiver.recv_timeout(Duration::from_millis(100)) {
        break res;
      } else if let Some(display) = optional_display.as_mut() {
        self.display_ongoing_tasks(&self.core.graph, &roots, display, display_worker_count);
      }
    };
    if let Some(display) = optional_display.as_mut() {
      display.render();
      display.finish();
    };

    request
      .roots
      .iter()
      .zip(results.into_iter())
      .map(|(s, r)| (s.params.expect_single(), &s.selector.product, r))
      .collect()
  }

  fn display_ongoing_tasks(
    &self,
    graph: &Graph<NodeKey>,
    roots: &[NodeKey],
    display: &mut EngineDisplay,
    display_worker_count: usize,
  ) {
    let ongoing_tasks = graph.heavy_hitters(&roots, display_worker_count);
    for (i, task) in ongoing_tasks.iter().enumerate() {
      display.update(i.to_string(), format!("{:?}", task));
    }
    // If the number of ongoing tasks is less than the number of workers,
    // fill the rest of the workers with empty string.
    // TODO(yic): further improve the UI. https://github.com/pantsbuild/pants/issues/6666
    for i in ongoing_tasks.len()..display_worker_count {
      display.update(i.to_string(), "".to_string());
    }
    display.render();
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
      &[]
    )));
    let store = self.core.store();

    posix_fs
      .expand(path_globs)
      .map_err(|err| format!("Error expanding globs: {:?}", err))
      .and_then(|path_stats| {
        fs::Snapshot::from_path_stats(
          store.clone(),
          &fs::OneOffStoreFileByDigest::new(store, posix_fs),
          path_stats,
        )
      }).to_boxed()
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

///
/// NB: This basic wrapper exists to allow us to implement the `NodeContext` trait (which lives
/// outside of this crate) for the `Arc` struct (which also lives outside our crate), which is not
/// possible without the wrapper due to "trait coherence".
///
#[derive(Clone)]
struct RootContext {
  core: Arc<Core>,
}

impl NodeContext for RootContext {
  type Node = NodeKey;

  fn clone_for(&self, entry_id: EntryId) -> Context {
    Context::new(entry_id, self.core.clone())
  }

  fn graph(&self) -> &Graph<NodeKey> {
    &self.core.graph
  }

  fn spawn<F>(&self, future: F)
  where
    F: Future<Item = (), Error = ()> + Send + 'static,
  {
    self.core.runtime.get().executor().spawn(future);
  }
}
