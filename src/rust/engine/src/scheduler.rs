// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};
use std::convert::TryInto;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::{mpsc, Arc};
use std::time::Duration;

use futures01::future::{self, Future};

use crate::context::{Context, Core};
use crate::core::{Failure, Params, TypeId, Value};
use crate::nodes::{NodeKey, Select, Tracer, Visualizer};
use graph::{Graph, InvalidationResult};
use indexmap::IndexMap;
use log::{debug, info, warn};
use logging::logger::LOGGER;
use parking_lot::Mutex;
use ui::{EngineDisplay, KeyboardCommand};
use workunit_store::WorkUnitStore;

pub enum ExecutionTermination {
  KeyboardInterrupt,
}

///
/// A Session represents a related series of requests (generally: one run of the pants CLI) on an
/// underlying Scheduler, and is a useful scope for metrics.
///
/// Both Scheduler and Session are exposed to python and expected to be used by multiple threads, so
/// they use internal mutability in order to avoid exposing locks to callers.
///
struct InnerSession {
  // The total size of the graph at Session-creation time.
  preceding_graph_size: usize,
  // The set of roots that have been requested within this session.
  roots: Mutex<HashSet<Root>>,
  // If enabled, the display that will render the progress of the V2 engine. This is only
  // Some(_) if the --v2-ui option is enabled.
  display: Option<Arc<Mutex<EngineDisplay>>>,
  // If enabled, Zipkin spans for v2 engine will be collected.
  should_record_zipkin_spans: bool,
  // A place to store info about workunits in rust part
  workunit_store: WorkUnitStore,
  // The unique id for this run. Used as the id of the session, and for metrics gathering purposes.
  build_id: String,
  should_report_workunits: bool,
}

#[derive(Clone)]
pub struct Session(Arc<InnerSession>);

impl Session {
  pub fn new(
    scheduler: &Scheduler,
    should_record_zipkin_spans: bool,
    should_render_ui: bool,
    ui_worker_count: usize,
    build_id: String,
    should_report_workunits: bool,
  ) -> Session {
    let display = if should_render_ui && EngineDisplay::stdout_is_tty() {
      let mut display = EngineDisplay::new(0);
      display.initialize(ui_worker_count);
      Some(Arc::new(Mutex::new(display)))
    } else {
      None
    };

    let inner_session = InnerSession {
      preceding_graph_size: scheduler.core.graph.len(),
      roots: Mutex::new(HashSet::new()),
      display,
      should_record_zipkin_spans,
      workunit_store: WorkUnitStore::new(),
      build_id,
      should_report_workunits,
    };
    Session(Arc::new(inner_session))
  }

  fn extend(&self, new_roots: &[Root]) {
    let mut roots = self.0.roots.lock();
    roots.extend(new_roots.iter().cloned());
  }

  fn root_nodes(&self) -> Vec<NodeKey> {
    let roots = self.0.roots.lock();
    roots.iter().map(|r| r.clone().into()).collect()
  }

  pub fn preceding_graph_size(&self) -> usize {
    self.0.preceding_graph_size
  }

  fn maybe_display(&self) -> Option<&Arc<Mutex<EngineDisplay>>> {
    self.0.display.as_ref()
  }

  pub fn should_record_zipkin_spans(&self) -> bool {
    self.0.should_record_zipkin_spans
  }

  pub fn should_report_workunits(&self) -> bool {
    self.0.should_report_workunits
  }

  pub fn workunit_store(&self) -> WorkUnitStore {
    self.0.workunit_store.clone()
  }

  pub fn build_id(&self) -> &String {
    &self.0.build_id
  }

  pub fn write_stdout(&self, msg: &str) {
    if let Some(display) = self.maybe_display() {
      let mut d = display.lock();
      d.write_stdout(msg);
    }
  }

  pub fn write_stderr(&self, msg: &str) {
    if let Some(display) = self.maybe_display() {
      let mut d = display.lock();
      d.write_stderr(msg);
    }
  }

  pub fn with_console_ui_disabled<F: FnOnce() -> T, T>(&self, f: F) -> T {
    if let Some(display) = self.maybe_display() {
      {
        let mut d = display.lock();
        d.suspend()
      }
      let output = f();
      {
        let mut d = display.lock();
        d.unsuspend();
      }
      output
    } else {
      f()
    }
  }

  pub fn should_handle_workunits(&self) -> bool {
    self.should_report_workunits() || self.should_record_zipkin_spans()
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
    params: Params,
    product: TypeId,
  ) -> Result<(), String> {
    let edges = self
      .core
      .rule_graph
      .find_root_edges(params.type_ids(), product)?;
    request
      .roots
      .push(Select::new_from_edges(params, product, &edges));
    Ok(())
  }

  ///
  /// Invalidate the invalidation roots represented by the given Paths.
  ///
  pub fn invalidate(&self, paths: &HashSet<PathBuf>) -> usize {
    let InvalidationResult { cleared, dirtied } =
      self.core.graph.invalidate_from_roots(move |node| {
        if let Some(fs_subject) = node.fs_subject() {
          paths.contains(fs_subject)
        } else {
          false
        }
      });
    // TODO: The rust log level is not currently set correctly in a pantsd context. To ensure that
    // we see this even at `info` level, we set it to warn. #6004 should address this by making
    // rust logging re-configuration an explicit step in `src/python/pants/init/logging.py`.
    warn!(
      "invalidation: cleared {} and dirtied {} nodes for: {:?}",
      cleared, dirtied, paths
    );
    cleared + dirtied
  }

  ///
  /// Invalidate all filesystem dependencies in the graph.
  ///
  pub fn invalidate_all_paths(&self) -> usize {
    let InvalidationResult { cleared, dirtied } = self
      .core
      .graph
      .invalidate_from_roots(|node| node.fs_subject().is_some());
    info!(
      "invalidation: cleared {} and dirtied {} nodes for all paths",
      cleared, dirtied
    );
    cleared + dirtied
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
    m.insert(
      "preceding_graph_size",
      session.preceding_graph_size() as i64,
    );
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
    context: Context,
    sender: mpsc::Sender<Vec<Result<Value, Failure>>>,
    roots: Vec<Root>,
    count: usize,
  ) {
    let core = context.core.clone();
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
                  debug!("Root {} completed.", NodeKey::Select(Box::new(root)));
                  Ok(other.map(|res| {
                    res
                      .try_into()
                      .unwrap_or_else(|_| panic!("A Node implementation was ambiguous."))
                  }))
                }
              }
            })
        })
        .collect::<Vec<_>>(),
    );

    // If the join failed (due to `Invalidated`, since that is the only error we propagate), retry
    // the entire set of roots.
    core.executor.spawn_and_ignore(roots_res.then(move |res| {
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
  pub fn execute(
    &self,
    request: &ExecutionRequest,
    session: &Session,
  ) -> Result<Vec<RootResult>, ExecutionTermination> {
    // Bootstrap tasks for the roots, and then wait for all of them.
    debug!("Launching {} roots.", request.roots.len());

    session.extend(&request.roots);

    // Wait for all roots to complete. Failure here should be impossible, because each
    // individual Future in the join was (eventually) mapped into success.
    let context = Context::new(self.core.clone(), session.clone());
    let (sender, receiver) = mpsc::channel();

    Scheduler::execute_helper(context, sender, request.roots.clone(), 8);
    let roots: Vec<NodeKey> = request
      .roots
      .clone()
      .into_iter()
      .map(NodeKey::from)
      .collect();

    // This map keeps the k most relevant jobs in assigned possitions.
    // Keys are positions in the display (display workers) and the values are the actual jobs to print.
    let mut tasks_to_display = IndexMap::new();
    let refresh_interval = Duration::from_millis(100);

    Ok(match session.maybe_display() {
      Some(display) => {
        {
          let mut display = display.lock();
          display.start();
        }
        let unique_handle = LOGGER.register_engine_display(display.clone());

        let results = loop {
          if let Ok(res) = receiver.recv_timeout(refresh_interval) {
            break res;
          } else {
            let render_result = Scheduler::display_ongoing_tasks(
              &self.core.graph,
              &roots,
              display,
              &mut tasks_to_display,
            );
            match render_result {
              Err(e) => warn!("{}", e),
              Ok(KeyboardCommand::CtrlC) => {
                info!("Exiting early in response to Ctrl-C");
                {
                  let mut display = display.lock();
                  display.finish();
                }
                return Err(ExecutionTermination::KeyboardInterrupt);
              }
              Ok(KeyboardCommand::None) => (),
            };
          }
        };
        LOGGER.deregister_engine_display(unique_handle);
        {
          let mut display = display.lock();
          display.finish();
        }
        results
      }
      None => loop {
        if let Ok(res) = receiver.recv_timeout(refresh_interval) {
          break res;
        }
      },
    })
  }

  fn display_ongoing_tasks(
    graph: &Graph<NodeKey>,
    roots: &[NodeKey],
    display: &Mutex<EngineDisplay>,
    tasks_to_display: &mut IndexMap<String, Duration>,
  ) -> Result<KeyboardCommand, String> {
    // Update the graph. To do that, we iterate over heavy hitters.

    let worker_count = {
      let d = display.lock();
      d.worker_count()
    };
    let heavy_hitters = graph.heavy_hitters(&roots, worker_count);

    // Insert every one in the set of tasks to display.
    // For tasks already here, the durations are overwritten.
    tasks_to_display.extend(heavy_hitters.clone().into_iter());

    // And remove the tasks that no longer should be there.
    for (task, _) in tasks_to_display.clone().into_iter() {
      if !heavy_hitters.contains_key(&task) {
        tasks_to_display.swap_remove(&task);
      }
    }

    for (i, item) in tasks_to_display.iter().enumerate() {
      let label = item.0;
      let duration = item.1;
      let duration_secs: f64 = (duration.as_millis() as f64) / 1000.0;
      let mut d = display.lock();
      d.update(i.to_string(), format!("{:.2}s {}", duration_secs, label));
    }

    // If the number of ongoing tasks is less than the number of workers,
    // fill the rest of the workers with empty string.
    // TODO(yic): further improve the UI. https://github.com/pantsbuild/pants/issues/6666
    let worker_count = {
      let d = display.lock();
      d.worker_count()
    };

    let mut d = display.lock();
    for i in tasks_to_display.len()..worker_count {
      d.update(i.to_string(), "".to_string());
    }
    d.render()
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
