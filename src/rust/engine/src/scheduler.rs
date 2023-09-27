// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};
use std::convert::TryInto;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use deepsize::DeepSizeOf;
use futures::{future, FutureExt};
use log::debug;
use tokio::time;

use crate::context::{Context, Core};
use crate::nodes::{NodeKey, Select};
use crate::python::{Failure, Params, TypeId, Value};
use crate::session::{ObservedValueResult, Root, Session};

use graph::LastObserved;
use ui::ConsoleUI;
use watch::{Invalidatable, InvalidateCaller};

pub enum ExecutionTermination {
  // Raised as a vanilla keyboard interrupt on the python side.
  KeyboardInterrupt,
  // An execute-method specific timeout: raised as PollTimeout.
  PollTimeout,
  // No clear reason: possibly a panic on a background thread.
  Fatal(String),
}

#[derive(Default)]
pub struct ExecutionRequest {
  // Set of roots for an execution, in the order they were declared.
  pub roots: Vec<Root>,
  // An ExecutionRequest with `poll` set will wait for _all_ of the given roots to have changed
  // since their previous observed value in this Session before returning them.
  //
  // Example: if an ExecutionRequest is made twice in a row for roots within the same Session,
  // and this value is set, the first run will request the roots and return immediately when they
  // complete. The second request will check whether the roots have changed, and if they haven't
  // changed, will wait until they have (or until the timeout elapses) before re-requesting them.
  //
  // TODO: The `poll`, `poll_delay`, and `timeout` parameters exist to support a coarse-grained API
  // for synchronous Node-watching to Python. Rather than further expanding this `execute` API, we
  // should likely port those usecases to rust.
  pub poll: bool,
  // If poll is set, a delay to apply after having noticed that Nodes have changed and before
  // requesting them.
  pub poll_delay: Option<Duration>,
  // A timeout applied globally to the request. When a request times out, work is _not_ cancelled,
  // and will continue to completion in the background.
  pub timeout: Option<Duration>,
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
    let context = session.graph_context();
    self
      .core
      .graph
      .visualize(&session.roots_nodes(), path, &context)
  }

  pub fn add_root_select(
    &self,
    request: &mut ExecutionRequest,
    params: Params,
    product: TypeId,
  ) -> Result<(), String> {
    let edges = self
      .core
      .rule_graph
      .find_root_edges(params.type_ids(), product)?;
    request.roots.push(Select::new_from_edges(
      params,
      &rule_graph::DependencyKey::new(product),
      &edges,
    ));
    Ok(())
  }

  ///
  /// Invalidate the invalidation roots represented by the given Paths.
  ///
  pub fn invalidate_paths(&self, paths: &HashSet<PathBuf>) -> usize {
    self
      .core
      .graph
      .invalidate(paths, InvalidateCaller::External)
  }

  ///
  /// Invalidate all filesystem dependencies in the graph.
  ///
  pub fn invalidate_all_paths(&self) -> usize {
    self.core.graph.invalidate_all(InvalidateCaller::External)
  }

  ///
  /// Invalidate the entire graph.
  ///
  pub fn invalidate_all(&self) {
    self.core.graph.clear();
  }

  ///
  /// Return Scheduler and per-Session metrics.
  ///
  pub fn metrics(&self, session: &Session) -> HashMap<&str, i64> {
    let context = session.graph_context();
    let mut m = HashMap::new();
    m.insert("affected_file_count", {
      let mut count = 0;
      self
        .core
        .graph
        .visit_live_reachable(&session.roots_nodes(), &context, |n, _| {
          if n.fs_subject().is_some() {
            count += 1;
          }
        });
      count
    });
    m.insert(
      "preceding_graph_size",
      session.preceding_graph_size() as i64,
    );
    m.insert("resulting_graph_size", self.core.graph.len() as i64);
    m
  }

  ///
  /// Returns references to all Python objects held alive by the graph, and a summary of sizes of
  /// Rust structs as a count and total size.
  ///
  pub fn live_items(
    &self,
    session: &Session,
  ) -> (Vec<Value>, HashMap<&'static str, (usize, usize)>) {
    let context = session.graph_context();
    let mut items = vec![];
    let mut sizes: HashMap<&'static str, (usize, usize)> = HashMap::new();
    // TODO: Creation of a Context is exposed in https://github.com/Aeledfyr/deepsize/pull/31.
    let mut deep_context = deepsize::Context::new();
    self.core.graph.visit_live(&context, |k, v| {
      if let NodeKey::Task(ref t) = k {
        items.extend(t.params.keys().map(|k| k.to_value()));
        items.push(v.clone().try_into().unwrap());
      }
      let entry = sizes.entry(k.workunit_name()).or_insert_with(|| (0, 0));
      entry.0 += 1;
      entry.1 += {
        std::mem::size_of_val(k)
          + k.deep_size_of_children(&mut deep_context)
          + std::mem::size_of_val(&v)
          + v.deep_size_of_children(&mut deep_context)
      };
    });
    (items, sizes)
  }

  ///
  /// Return unit if the Scheduler is still valid, or an error string if something has invalidated
  /// the Scheduler, indicating that it should re-initialize. See InvalidationWatcher.
  ///
  pub fn is_valid(&self) -> Result<(), String> {
    let core = self.core.clone();
    self.core.executor.block_on(async move {
      // Confirm that our InvalidationWatcher is still alive.
      if let Some(watcher) = &core.watcher {
        watcher.is_valid().await
      } else {
        Ok(())
      }
    })
  }

  ///
  /// Return all Digests currently in memory in this Scheduler.
  ///
  pub fn all_digests(&self, session: &Session) -> HashSet<hashing::Digest> {
    let context = session.graph_context();
    let mut digests = HashSet::new();
    self
      .core
      .graph
      .visit_live(&context, |_, v| digests.extend(v.digests()));
    digests
  }

  async fn poll_or_create(
    context: &Context,
    root: Root,
    last_observed: Option<LastObserved>,
    poll: bool,
    poll_delay: Option<Duration>,
  ) -> ObservedValueResult {
    let (result, last_observed) = if poll {
      let (result, last_observed) = context
        .core
        .graph
        .poll(root.into(), last_observed, poll_delay, context)
        .await;
      (result, Some(last_observed))
    } else {
      let result = context.core.graph.create(root.into(), context).await;
      (result, None)
    };

    (
      result.map(|v| {
        v.try_into()
          .unwrap_or_else(|e| panic!("A Node implementation was ambiguous: {e:?}"))
      }),
      last_observed,
    )
  }

  ///
  /// Attempts to complete all of the given roots.
  ///
  async fn execute_helper(
    request: &ExecutionRequest,
    session: &Session,
  ) -> Vec<ObservedValueResult> {
    let context = session.graph_context();
    let roots = session.roots_zip_last_observed(&request.roots);
    let poll = request.poll;
    let poll_delay = request.poll_delay;
    future::join_all(
      roots
        .into_iter()
        .map(|(root, last_observed)| {
          Self::poll_or_create(&context, root, last_observed, poll, poll_delay)
        })
        .collect::<Vec<_>>(),
    )
    .await
  }

  fn execute_record_results(
    roots: &[Root],
    session: &Session,
    results: Vec<ObservedValueResult>,
  ) -> Vec<Result<Value, Failure>> {
    // Store the roots that were operated on and their LastObserved values.
    session.roots_extend(
      results
        .iter()
        .zip(roots.iter())
        .map(|(result, root)| (root.clone(), result.1))
        .collect(),
    );

    results
      .into_iter()
      .map(|(res, _last_observed)| res)
      .collect()
  }

  ///
  /// Compute the results for roots in the given request.
  ///
  pub fn execute(
    &self,
    request: &ExecutionRequest,
    session: &Session,
  ) -> Result<Vec<Result<Value, Failure>>, ExecutionTermination> {
    debug!(
      "Launching {} roots (poll={}).",
      request.roots.len(),
      request.poll
    );

    let interval = ConsoleUI::render_interval();
    let deadline = request.timeout.map(|timeout| Instant::now() + timeout);
    let executor = self.core.executor.clone();

    // Spawn and wait for all roots to complete.
    self.core.executor.block_on(async move {
      session.maybe_display_initialize(&executor).await;
      let mut execution_task = Self::execute_helper(request, session).boxed();

      let mut refresh_delay = time::sleep(Self::refresh_delay(interval, deadline)).boxed();
      let result = loop {
        tokio::select! {
          _ = session.cancelled() => {
            // The Session was cancelled.
            break Err(ExecutionTermination::KeyboardInterrupt)
          }
          _ = &mut refresh_delay => {
            // It's time to render a new frame (or maybe to time out entirely if the deadline has
            // elapsed).
            if deadline.map(|d| d < Instant::now()).unwrap_or(false) {
              // The timeout on the request has been exceeded.
              break Err(ExecutionTermination::PollTimeout);
            } else {
              // Just a receive timeout. render and continue.
              session.maybe_display_render();
            }
            refresh_delay = time::sleep(Self::refresh_delay(interval, deadline)).boxed();
          }
          res = &mut execution_task => {
            // Completed successfully.
            break Ok(Self::execute_record_results(&request.roots, session, res));
          }
        }
      };
      session.maybe_display_teardown().await;
      result
    })
  }

  fn refresh_delay(refresh_interval: Duration, deadline: Option<Instant>) -> Duration {
    deadline
      .and_then(|deadline| deadline.checked_duration_since(Instant::now()))
      .map(|duration_till_deadline| std::cmp::min(refresh_interval, duration_till_deadline))
      .unwrap_or(refresh_interval)
  }
}

impl Drop for Scheduler {
  fn drop(&mut self) {
    // Because Nodes may hold references to the Core in their closure, this is intended to
    // break cycles between Nodes and the Core.
    self.core.graph.clear();
  }
}
