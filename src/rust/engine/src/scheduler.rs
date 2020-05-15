// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};
use std::convert::TryInto;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::{mpsc, Arc};
use std::time::{Duration, Instant};

use futures::compat::Future01CompatExt;
use futures::future;

use crate::context::{Context, Core};
use crate::core::{Failure, Params, TypeId, Value};
use crate::nodes::{NodeKey, Select, Tracer, Visualizer};

use graph::{Graph, InvalidationResult, LastObserved};
use hashing;
use indexmap::IndexMap;
use log::{debug, info, warn};
use logging::logger::LOGGER;
use parking_lot::Mutex;
use ui::{EngineDisplay, KeyboardCommand};
use uuid::Uuid;
use watch::Invalidatable;
use workunit_store::WorkUnitStore;

pub enum ExecutionTermination {
  KeyboardInterrupt,
  Timeout,
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
  // The set of roots that have been requested within this session, with associated LastObserved
  // times if they were polled.
  roots: Mutex<HashMap<Root, Option<LastObserved>>>,
  // If enabled, the display that will render the progress of the V2 engine. This is only
  // Some(_) if the --v2-ui option is enabled.
  display: Option<Arc<Mutex<EngineDisplay>>>,
  // If enabled, Zipkin spans for v2 engine will be collected.
  should_record_zipkin_spans: bool,
  // A place to store info about workunits in rust part
  workunit_store: WorkUnitStore,
  // The unique id for this Session: used for metrics gathering purposes.
  build_id: String,
  // An id used to control the visibility of uncacheable rules. Generally this is identical for an
  // entire Session, but in some cases (in particular, a `--loop`) the caller wants to retain the
  // same Session while still observing new values for uncacheable rules like Goals.
  //
  // TODO: Figure out how the `--loop` interplays with metrics. It's possible that for metrics
  // purposes, each iteration of a loop should be considered to be a new Session, but for now the
  // Session/build_id would be stable.
  run_id: Mutex<Uuid>,
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
      roots: Mutex::new(HashMap::new()),
      display,
      should_record_zipkin_spans,
      workunit_store: WorkUnitStore::new(),
      build_id,
      run_id: Mutex::new(Uuid::new_v4()),
      should_report_workunits,
    };
    Session(Arc::new(inner_session))
  }

  fn extend(&self, new_roots: Vec<(Root, Option<LastObserved>)>) {
    let mut roots = self.0.roots.lock();
    roots.extend(new_roots);
  }

  fn zip_last_observed(&self, inputs: &[Root]) -> Vec<(Root, Option<LastObserved>)> {
    let roots = self.0.roots.lock();
    inputs
      .iter()
      .map(|root| {
        let last_observed = roots.get(root).cloned().unwrap_or(None);
        (root.clone(), last_observed)
      })
      .collect()
  }

  fn root_nodes(&self) -> Vec<NodeKey> {
    let roots = self.0.roots.lock();
    roots.keys().map(|r| r.clone().into()).collect()
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

  pub fn run_id(&self) -> Uuid {
    let run_id = self.0.run_id.lock();
    *run_id
  }

  pub fn new_run_id(&self) {
    let mut run_id = self.0.run_id.lock();
    *run_id = Uuid::new_v4();
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

impl ExecutionRequest {
  pub fn new() -> ExecutionRequest {
    ExecutionRequest {
      roots: Vec::new(),
      poll: false,
      poll_delay: None,
      timeout: None,
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
    let context = Context::new(self.core.clone(), session.clone());
    self
      .core
      .graph
      .visualize(Visualizer::default(), &session.root_nodes(), path, &context)
  }

  pub fn trace(
    &self,
    session: &Session,
    request: &ExecutionRequest,
    path: &Path,
  ) -> Result<(), String> {
    let context = Context::new(self.core.clone(), session.clone());
    self
      .core
      .graph
      .trace::<Tracer>(&request.root_nodes(), path, &context)?;
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
    self.core.graph.invalidate(paths, "watchman")
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
    let context = Context::new(self.core.clone(), session.clone());
    let mut m = HashMap::new();
    m.insert(
      "affected_file_count",
      self
        .core
        .graph
        .reachable_digest_count(&session.root_nodes(), &context) as i64,
    );
    m.insert(
      "preceding_graph_size",
      session.preceding_graph_size() as i64,
    );
    m.insert("resulting_graph_size", self.core.graph.len() as i64);
    m
  }

  ///
  /// Return unit if the Scheduler is still valid, or an error string if something has invalidated
  /// the Scheduler, indicating that it should re-initialize. See InvalidationWatcher.
  ///
  pub fn is_valid(&self) -> Result<(), String> {
    let core = self.core.clone();
    self.core.executor.block_on(async move {
      // Confirm that our InvalidationWatcher is still alive.
      core.watcher.is_valid().await
    })
  }

  ///
  /// Return all Digests currently in memory in this Scheduler.
  ///
  pub fn all_digests(&self, session: &Session) -> Vec<hashing::Digest> {
    let context = Context::new(self.core.clone(), session.clone());
    self.core.graph.all_digests(&context)
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
        .poll(root.into(), last_observed, poll_delay, &context)
        .await?;
      (result, Some(last_observed))
    } else {
      let result = context
        .core
        .graph
        .create(root.into(), &context)
        .compat()
        .await?;
      (result, None)
    };

    Ok((
      result
        .try_into()
        .unwrap_or_else(|e| panic!("A Node implementation was ambiguous: {:?}", e)),
      last_observed,
    ))
  }

  ///
  /// Attempts to complete all of the given roots, and send the result on the given mpsc Sender,
  /// which allows the caller to poll a channel for the result without blocking uninterruptibly
  /// on a Future.
  ///
  fn execute_helper(
    &self,
    request: &ExecutionRequest,
    session: &Session,
    sender: mpsc::Sender<Vec<ObservedValueResult>>,
  ) {
    let context = Context::new(self.core.clone(), session.clone());
    let roots = session.zip_last_observed(&request.roots);
    let poll = request.poll;
    let poll_delay = request.poll_delay;
    let core = context.core.clone();
    core.executor.spawn_and_ignore(async move {
      let res = future::join_all(
        roots
          .into_iter()
          .map(|(root, last_observed)| {
            Self::poll_or_create(&context, root, last_observed, poll, poll_delay)
          })
          .collect::<Vec<_>>(),
      )
      .await;
      let _ = sender.send(res);
    });
  }

  fn execute_record_results(
    roots: &[Root],
    session: &Session,
    results: Vec<ObservedValueResult>,
  ) -> Vec<Result<Value, Failure>> {
    // Store the roots that were operated on and their LastObserved values.
    session.extend(
      results
        .iter()
        .zip(roots.iter())
        .map(|(result, root)| {
          let last_observed = result
            .as_ref()
            .ok()
            .and_then(|(_value, last_observed)| *last_observed);
          (root.clone(), last_observed)
        })
        .collect::<Vec<_>>(),
    );

    results
      .into_iter()
      .map(|res| res.map(|(value, _last_observed)| value))
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

    // Spawn and wait for all roots to complete. Failure here should be impossible, because each
    // individual Future in the join was (eventually) mapped into success.
    let (sender, receiver) = mpsc::channel();
    self.execute_helper(request, session, sender);
    let roots: Vec<NodeKey> = request
      .roots
      .clone()
      .into_iter()
      .map(NodeKey::from)
      .collect();

    // This map keeps the k most relevant jobs in assigned possitions.
    // Keys are positions in the display (display workers) and the values are the actual jobs to print.
    let mut tasks = IndexMap::new();
    let deadline = request.timeout.map(|timeout| Instant::now() + timeout);

    let maybe_display_handle = Self::maybe_display_initialize(&session);
    let result = loop {
      if let Ok(res) = receiver.recv_timeout(Self::compute_refresh_delay(deadline)) {
        // Completed successfully.
        break Ok(Self::execute_record_results(&request.roots, &session, res));
      } else if let Err(e) =
        Self::maybe_display_render(&self.core.graph, &roots, &session, &mut tasks)
      {
        break Err(e);
      } else if deadline.map(|d| d < Instant::now()).unwrap_or(false) {
        // The timeout on the request has been exceeded.
        break Err(ExecutionTermination::Timeout);
      }
    };
    Self::maybe_display_teardown(session, maybe_display_handle);

    result
  }

  fn compute_refresh_delay(deadline: Option<Instant>) -> Duration {
    let refresh_interval = Duration::from_millis(100);
    deadline
      .and_then(|deadline| deadline.checked_duration_since(Instant::now()))
      .map(|duration_till_deadline| std::cmp::min(refresh_interval, duration_till_deadline))
      .unwrap_or(refresh_interval)
  }

  fn maybe_display_initialize(session: &Session) -> Option<Uuid> {
    if let Some(display) = session.maybe_display() {
      {
        let mut display = display.lock();
        display.start();
      }
      Some(LOGGER.register_engine_display(display.clone()))
    } else {
      None
    }
  }

  fn maybe_display_teardown(session: &Session, handle: Option<Uuid>) {
    if let Some(handle) = handle {
      LOGGER.deregister_engine_display(handle);
    }
    if let Some(display) = session.maybe_display() {
      let mut display = display.lock();
      display.finish();
    }
  }

  fn maybe_display_render(
    graph: &Graph<NodeKey>,
    roots: &[NodeKey],
    session: &Session,
    tasks_to_display: &mut IndexMap<String, Duration>,
  ) -> Result<(), ExecutionTermination> {
    let display = if let Some(display) = session.maybe_display() {
      display
    } else {
      return Ok(());
    };

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

    match d.render() {
      Err(e) => {
        warn!("{}", e);
        Ok(())
      }
      Ok(KeyboardCommand::CtrlC) => {
        info!("Exiting early in response to Ctrl-C");
        {
          let mut display = display.lock();
          display.finish();
        }
        Err(ExecutionTermination::KeyboardInterrupt)
      }
      Ok(KeyboardCommand::None) => Ok(()),
    }
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

pub type ObservedValueResult = Result<(Value, Option<LastObserved>), Failure>;
