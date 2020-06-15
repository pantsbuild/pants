// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};
use std::convert::TryInto;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::{mpsc, Arc};
use std::time::{Duration, Instant};

use futures::future;

use crate::context::{Context, Core};
use crate::core::{Failure, Params, TypeId, Value};
use crate::nodes::{NodeKey, Select, Visualizer};

use graph::{InvalidationResult, LastObserved};
use log::{debug, info, warn};
use parking_lot::Mutex;
use task_executor::Executor;
use ui::ConsoleUI;
use uuid::Uuid;
use watch::Invalidatable;
use workunit_store::WorkunitStore;

pub enum ExecutionTermination {
  // Raised as a vanilla keyboard interrupt on the python side.
  KeyboardInterrupt,
  // An execute-method specific timeout: raised as PollTimeout.
  PollTimeout,
  // No clear reason: possibly a panic on a background thread.
  Fatal(String),
}

enum ExecutionEvent {
  Completed(Vec<ObservedValueResult>),
  Stderr(String),
}

type ObservedValueResult = Result<(Value, Option<LastObserved>), Failure>;

// Root requests are limited to Select nodes, which produce (python) Values.
type Root = Select;

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
  // Some(_) if the --dynamic-ui option is enabled.
  display: Option<Mutex<ConsoleUI>>,
  // If enabled, Zipkin spans for v2 engine will be collected.
  should_record_zipkin_spans: bool,
  // A place to store info about workunits in rust part
  workunit_store: WorkunitStore,
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
    build_id: String,
    should_report_workunits: bool,
  ) -> Session {
    let workunit_store = WorkunitStore::new(should_render_ui);
    let display = if should_render_ui {
      Some(Mutex::new(ConsoleUI::new(workunit_store.clone())))
    } else {
      None
    };

    let inner_session = InnerSession {
      preceding_graph_size: scheduler.core.graph.len(),
      roots: Mutex::new(HashMap::new()),
      display,
      should_record_zipkin_spans,
      workunit_store,
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

  pub fn should_record_zipkin_spans(&self) -> bool {
    self.0.should_record_zipkin_spans
  }

  pub fn should_report_workunits(&self) -> bool {
    self.0.should_report_workunits
  }

  pub fn workunit_store(&self) -> WorkunitStore {
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

  pub async fn write_stdout(&self, msg: &str) -> Result<(), String> {
    if let Some(display) = &self.0.display {
      let mut display = display.lock();
      display.write_stdout(msg).await
    } else {
      print!("{}", msg);
      Ok(())
    }
  }

  pub fn write_stderr(&self, msg: &str) {
    if let Some(display) = &self.0.display {
      let display = display.lock();
      display.write_stderr(msg);
    } else {
      eprint!("{}", msg);
    }
  }

  pub async fn with_console_ui_disabled<F: FnOnce() -> T, T>(&self, f: F) -> T {
    if let Some(display) = &self.0.display {
      let mut display = display.lock();
      display.with_console_ui_disabled(f).await
    } else {
      f()
    }
  }

  pub fn should_handle_workunits(&self) -> bool {
    self.should_report_workunits() || self.should_record_zipkin_spans()
  }

  fn maybe_display_initialize(&self, executor: &Executor, sender: &mpsc::Sender<ExecutionEvent>) {
    if let Some(display) = &self.0.display {
      let mut display = display.lock();
      let sender = sender.clone();
      let res = display.initialize(
        executor.clone(),
        Box::new(move |msg: &str| {
          // If we fail to send, it's because the execute loop has exited: we fail the callback to
          // have the logging module directly log to stderr at that point.
          sender
            .send(ExecutionEvent::Stderr(msg.to_owned()))
            .map_err(|_| ())
        }),
      );
      if let Err(e) = res {
        warn!("{}", e);
      }
    }
  }

  async fn maybe_display_teardown(&self) {
    if let Some(display) = &self.0.display {
      let teardown = {
        let mut display = display.lock();
        display.teardown()
      };
      if let Err(e) = teardown.await {
        warn!("{}", e);
      }
    }
  }

  fn maybe_display_render(&self) {
    if let Some(display) = &self.0.display {
      let mut display = display.lock();
      display.render();
    }
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
    m.insert("affected_file_count", {
      let mut count = 0;
      self
        .core
        .graph
        .visit_live_reachable(&session.root_nodes(), &context, |n, _| {
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
  pub fn all_digests(&self, session: &Session) -> HashSet<hashing::Digest> {
    let context = Context::new(self.core.clone(), session.clone());
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
        .poll(root.into(), last_observed, poll_delay, &context)
        .await?;
      (result, Some(last_observed))
    } else {
      let result = context.core.graph.create(root.into(), &context).await?;
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
  /// Attempts to complete all of the given roots, and send a FinalResult on the given mpsc Sender,
  /// which allows the caller to poll a channel for the result without blocking uninterruptibly
  /// on a Future.
  ///
  fn execute_helper(
    &self,
    request: &ExecutionRequest,
    session: &Session,
    sender: mpsc::Sender<ExecutionEvent>,
  ) {
    let context = Context::new(self.core.clone(), session.clone());
    let roots = session.zip_last_observed(&request.roots);
    let poll = request.poll;
    let poll_delay = request.poll_delay;
    let core = context.core.clone();
    let _join = core.executor.spawn(async move {
      let res = future::join_all(
        roots
          .into_iter()
          .map(|(root, last_observed)| {
            Self::poll_or_create(&context, root, last_observed, poll, poll_delay)
          })
          .collect::<Vec<_>>(),
      )
      .await;

      // The receiver may have gone away due to timeout.
      let _ = sender.send(ExecutionEvent::Completed(res));
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

    let interval = ConsoleUI::render_interval();
    let deadline = request.timeout.map(|timeout| Instant::now() + timeout);

    // Spawn and wait for all roots to complete.
    let (sender, receiver) = mpsc::channel();
    session.maybe_display_initialize(&self.core.executor, &sender);
    self.execute_helper(request, session, sender);
    let result = loop {
      match receiver.recv_timeout(Self::refresh_delay(interval, deadline)) {
        Ok(ExecutionEvent::Completed(res)) => {
          // Completed successfully.
          break Ok(Self::execute_record_results(&request.roots, &session, res));
        }
        Ok(ExecutionEvent::Stderr(stderr)) => {
          session.write_stderr(&stderr);
        }
        Err(mpsc::RecvTimeoutError::Timeout) => {
          if deadline.map(|d| d < Instant::now()).unwrap_or(false) {
            // The timeout on the request has been exceeded.
            break Err(ExecutionTermination::PollTimeout);
          } else {
            // Just a receive timeout. render and continue.
            session.maybe_display_render();
          }
        }
        Err(mpsc::RecvTimeoutError::Disconnected) => {
          break Err(ExecutionTermination::Fatal(
            "Execution threads exited early.".to_owned(),
          ));
        }
      }
    };
    self
      .core
      .executor
      .block_on(session.maybe_display_teardown());

    result
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
