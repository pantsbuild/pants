// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::future::Future;
use std::sync::{Arc, Weak};
use std::time::{Duration, Instant};

use crate::context::Core;
use crate::core::{Failure, Value};
use crate::nodes::{NodeKey, Select};
use crate::scheduler::Scheduler;

use async_latch::AsyncLatch;
use futures::FutureExt;
use graph::LastObserved;
use lazy_static::lazy_static;
use log::warn;
use parking_lot::{Mutex, RwLock};
use task_executor::Executor;
use tokio::sync::mpsc;
use ui::ConsoleUI;
use uuid::Uuid;
use workunit_store::{UserMetadataPyValue, WorkunitStore};

// When enabled, the interval at which all stragglers that have been running for longer than a
// threshold should be logged. The threshold might become configurable, but this might not need
// to be.
const STRAGGLER_LOGGING_INTERVAL: Duration = Duration::from_secs(30);

// Root requests are limited to Select nodes, which produce (python) Values.
pub type Root = Select;

pub enum ExecutionEvent {
  Completed(Vec<ObservedValueResult>),
  Stderr(String),
}

pub type ObservedValueResult = Result<(Value, Option<LastObserved>), Failure>;

///
/// An enum for the two cases of `--[no-]dynamic-ui`.
///
enum SessionDisplay {
  // The dynamic UI is enabled, and the ConsoleUI should interact with a TTY.
  ConsoleUI(ConsoleUI),
  // The dynamic UI is disabled, and we should use only logging.
  Logging {
    straggler_threshold: Duration,
    straggler_deadline: Option<Instant>,
  },
}

lazy_static! {
  // A collection of all live Sessions. Completed Sessions (i.e., those for which the Weak
  // reference is dead) are removed from this collection on a best effort basis.
  static ref SESSIONS: Mutex<Vec<Weak<InnerSession>>> = Mutex::default();
}

fn sessions_add(session: &Arc<InnerSession>) {
  let mut sessions = SESSIONS.lock();
  sessions.retain(|weak_session| weak_session.upgrade().is_some());
  sessions.push(Arc::downgrade(session));
}

///
/// Cancel all live Sessions.
///
/// In the case of pantsd, Sessions are generally canceled one at a time if their associated clients
/// disconnect. But if a pants process receives a Unix signal, it might use this method to attempt to
/// cancel ongoing work before exiting.
///
pub fn sessions_cancel() {
  let sessions = {
    let sessions = SESSIONS.lock();
    sessions
      .iter()
      .filter_map(|weak_session| weak_session.upgrade())
      .collect::<Vec<_>>()
  };
  for session in sessions {
    session.core.executor.block_on(session.cancel());
  }
}

///
/// A Session represents a related series of requests (generally: one run of the pants CLI) on an
/// underlying Scheduler, and is a useful scope for metrics.
///
/// Both Scheduler and Session are exposed to python and expected to be used by multiple threads, so
/// they use internal mutability in order to avoid exposing locks to callers.
///
struct InnerSession {
  // Whether or not this Session has been cancelled. If a Session has been cancelled, all work that
  // it started should attempt to exit in an orderly fashion.
  cancelled: AsyncLatch,
  // The Core that this Session is running on.
  core: Arc<Core>,
  // The total size of the graph at Session-creation time.
  preceding_graph_size: usize,
  // The set of roots that have been requested within this session, with associated LastObserved
  // times if they were polled.
  roots: Mutex<HashMap<Root, Option<LastObserved>>>,
  // The display mechanism to use in this Session.
  display: Mutex<SessionDisplay>,
  // A place to store info about workunits in rust part
  workunit_store: WorkunitStore,
  // The unique id for this Session: used for metrics gathering purposes.
  build_id: String,
  // Per-Session values that have been set for this session.
  session_values: Mutex<Value>,
  // An id used to control the visibility of uncacheable rules. Generally this is identical for an
  // entire Session, but in some cases (in particular, a `--loop`) the caller wants to retain the
  // same Session while still observing new values for uncacheable rules like Goals.
  //
  // TODO: Figure out how the `--loop` interplays with metrics. It's possible that for metrics
  // purposes, each iteration of a loop should be considered to be a new Session, but for now the
  // Session/build_id would be stable.
  run_id: Mutex<Uuid>,
  should_report_workunits: bool,
  workunit_metadata_map: RwLock<HashMap<UserMetadataPyValue, Value>>,
}

impl InnerSession {
  ///
  /// Cancels this Session.
  ///
  pub async fn cancel(&self) {
    // TODO: If this sticks, this function doesn't need to be async.
    self.cancelled.trigger();
  }
}

#[derive(Clone)]
pub struct Session(Arc<InnerSession>);

impl Session {
  pub fn new(
    scheduler: &Scheduler,
    should_render_ui: bool,
    build_id: String,
    should_report_workunits: bool,
    session_values: Value,
    cancelled: AsyncLatch,
  ) -> Session {
    let workunit_store = WorkunitStore::new(!should_render_ui);
    let display = Mutex::new(if should_render_ui {
      SessionDisplay::ConsoleUI(ConsoleUI::new(
        workunit_store.clone(),
        scheduler.core.local_parallelism,
      ))
    } else {
      SessionDisplay::Logging {
        // TODO: This threshold should likely be configurable, but the interval we render at
        // probably does not need to be.
        straggler_threshold: Duration::from_secs(60),
        straggler_deadline: None,
      }
    });

    let inner_session = Arc::new(InnerSession {
      cancelled,
      core: scheduler.core.clone(),
      preceding_graph_size: scheduler.core.graph.len(),
      roots: Mutex::new(HashMap::new()),
      display,
      workunit_store,
      build_id,
      session_values: Mutex::new(session_values),
      run_id: Mutex::new(Uuid::new_v4()),
      should_report_workunits,
      workunit_metadata_map: RwLock::new(HashMap::new()),
    });
    sessions_add(&inner_session);
    Session(inner_session)
  }

  pub fn core(&self) -> &Arc<Core> {
    &self.0.core
  }

  ///
  /// Cancels this Session.
  ///
  pub async fn cancel(&self) {
    self.0.cancel().await;
  }

  ///
  /// Returns only if this Session has been cancelled.
  ///
  pub async fn cancelled(&self) {
    self.0.cancelled.triggered().await;
  }

  pub fn with_metadata_map<F, T>(&self, f: F) -> T
  where
    F: Fn(&mut HashMap<UserMetadataPyValue, Value>) -> T,
  {
    f(&mut self.0.workunit_metadata_map.write())
  }

  pub fn roots_extend(&self, new_roots: Vec<(Root, Option<LastObserved>)>) {
    let mut roots = self.0.roots.lock();
    roots.extend(new_roots);
  }

  pub fn roots_zip_last_observed(&self, inputs: &[Root]) -> Vec<(Root, Option<LastObserved>)> {
    let roots = self.0.roots.lock();
    inputs
      .iter()
      .map(|root| {
        let last_observed = roots.get(root).cloned().unwrap_or(None);
        (root.clone(), last_observed)
      })
      .collect()
  }

  pub fn roots_nodes(&self) -> Vec<NodeKey> {
    let roots = self.0.roots.lock();
    roots.keys().map(|r| r.clone().into()).collect()
  }

  pub fn session_values(&self) -> Value {
    self.0.session_values.lock().clone()
  }

  pub fn preceding_graph_size(&self) -> usize {
    self.0.preceding_graph_size
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
    if let SessionDisplay::ConsoleUI(ref mut ui) = *self.0.display.lock() {
      ui.write_stdout(msg).await
    } else {
      print!("{}", msg);
      Ok(())
    }
  }

  pub fn write_stderr(&self, msg: &str) {
    if let SessionDisplay::ConsoleUI(ref mut ui) = *self.0.display.lock() {
      ui.write_stderr(msg);
    } else {
      eprint!("{}", msg);
    }
  }

  pub async fn with_console_ui_disabled<T>(&self, f: impl Future<Output = T>) -> T {
    match *self.0.display.lock() {
      SessionDisplay::ConsoleUI(ref mut ui) => ui.with_console_ui_disabled(f).await,
      SessionDisplay::Logging { .. } => f.await,
    }
  }

  pub fn maybe_display_initialize(
    &self,
    executor: &Executor,
    sender: &mpsc::UnboundedSender<ExecutionEvent>,
  ) {
    let result = match *self.0.display.lock() {
      SessionDisplay::ConsoleUI(ref mut ui) => {
        let sender = sender.clone();
        ui.initialize(
          executor.clone(),
          Box::new(move |msg: &str| {
            // If we fail to send, it's because the execute loop has exited: we fail the callback to
            // have the logging module directly log to stderr at that point.
            sender
              .send(ExecutionEvent::Stderr(msg.to_owned()))
              .map_err(|_| ())
          }),
        )
      }
      SessionDisplay::Logging {
        ref mut straggler_deadline,
        ..
      } => {
        *straggler_deadline = Some(Instant::now() + STRAGGLER_LOGGING_INTERVAL);
        Ok(())
      }
    };
    if let Err(e) = result {
      warn!("{}", e);
    }
  }

  pub async fn maybe_display_teardown(&self) {
    let teardown = match *self.0.display.lock() {
      SessionDisplay::ConsoleUI(ref mut ui) => ui.teardown().boxed(),
      SessionDisplay::Logging {
        ref mut straggler_deadline,
        ..
      } => {
        *straggler_deadline = None;
        async { Ok(()) }.boxed()
      }
    };
    if let Err(e) = teardown.await {
      warn!("{}", e);
    }
  }

  pub fn maybe_display_render(&self) {
    match *self.0.display.lock() {
      SessionDisplay::ConsoleUI(ref mut ui) => ui.render(),
      SessionDisplay::Logging {
        straggler_threshold,
        ref mut straggler_deadline,
      } => {
        if straggler_deadline
          .map(|sd| sd < Instant::now())
          .unwrap_or(false)
        {
          *straggler_deadline = Some(Instant::now() + STRAGGLER_LOGGING_INTERVAL);
          self
            .0
            .workunit_store
            .log_straggling_workunits(straggler_threshold);
        }
      }
    }
  }
}
