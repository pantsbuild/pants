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
use futures::future::{self, AbortHandle, Abortable};
use futures::FutureExt;
use graph::LastObserved;
use log::warn;
use parking_lot::{Mutex, RwLock};
use task_executor::Executor;
use tokio::signal::unix::{signal, SignalKind};
use ui::ConsoleUI;
use uuid::Uuid;
use workunit_store::{UserMetadataPyValue, WorkunitStore};

// When enabled, the interval at which all stragglers that have been running for longer than a
// threshold should be logged. The threshold might become configurable, but this might not need
// to be.
const STRAGGLER_LOGGING_INTERVAL: Duration = Duration::from_secs(30);

// Root requests are limited to Select nodes, which produce (python) Values.
pub type Root = Select;

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

impl SessionDisplay {
  fn new(
    workunit_store: &WorkunitStore,
    parallelism: usize,
    should_render_ui: bool,
  ) -> SessionDisplay {
    if should_render_ui {
      SessionDisplay::ConsoleUI(ConsoleUI::new(workunit_store.clone(), parallelism))
    } else {
      SessionDisplay::Logging {
        // TODO: This threshold should likely be configurable, but the interval we render at
        // probably does not need to be.
        straggler_threshold: Duration::from_secs(60),
        straggler_deadline: None,
      }
    }
  }
}

///
/// The portion of a Session that uniquely identifies it and holds metrics and the history of
/// requests made on it.
///
struct SessionState {
  // The Core that this Session is running on.
  core: Arc<Core>,
  // The total size of the graph at Session-creation time.
  preceding_graph_size: usize,
  // The set of roots that have been requested within this session, with associated LastObserved
  // times if they were polled.
  roots: Mutex<HashMap<Root, Option<LastObserved>>>,
  // A place to store info about workunits in rust part
  workunit_store: WorkunitStore,
  // Per-Session values that have been set for this session.
  session_values: Mutex<Value>,
  // An id used to control the visibility of uncacheable rules. Generally this is identical for an
  // entire Session, but in some cases (in particular, a `--loop`) the caller wants to retain the
  // same Session while still observing new values for uncacheable rules like Goals.
  //
  // TODO: Figure out how the `--loop` flag interplays with metrics. It's possible that for metrics
  // purposes, each iteration of a loop should be considered to be a new Session, but for now the
  // Session/build_id would be stable.
  run_id: Mutex<Uuid>,
  workunit_metadata_map: RwLock<HashMap<UserMetadataPyValue, Value>>,
}

///
/// A cancellable handle to a Session, with an optional associated UI.
///
struct SessionHandle {
  // The unique id for this Session: used for metrics gathering purposes.
  build_id: String,
  // Whether or not this Session has been cancelled. If a Session has been cancelled, all work that
  // it started should attempt to exit in an orderly fashion.
  cancelled: AsyncLatch,
  // The display mechanism to use in this Session.
  display: Mutex<SessionDisplay>,
}

impl SessionHandle {
  ///
  /// Cancels this Session.
  ///
  pub fn cancel(&self) {
    self.cancelled.trigger();
  }
}

impl Drop for SessionHandle {
  fn drop(&mut self) {
    self.cancelled.trigger();
  }
}

///
/// A Session represents a related series of requests (generally: one run of the pants CLI) on an
/// underlying Scheduler, and is a useful scope for metrics.
///
/// Both Scheduler and Session are exposed to python and expected to be used by multiple threads, so
/// they use internal mutability in order to avoid exposing locks to callers.
///
/// NB: The `SessionState` and `SessionHandle` structs are independent in order to allow for a
/// shallow clone of a Session with independent cancellation and display properties, but which
/// shares the same metrics and identity.
///
#[derive(Clone)]
pub struct Session {
  handle: Arc<SessionHandle>,
  state: Arc<SessionState>,
}

impl Session {
  pub fn new(
    scheduler: &Scheduler,
    should_render_ui: bool,
    build_id: String,
    session_values: Value,
    cancelled: AsyncLatch,
  ) -> Result<Session, String> {
    let workunit_store = WorkunitStore::new(!should_render_ui);
    let display = Mutex::new(SessionDisplay::new(
      &workunit_store,
      scheduler.core.local_parallelism,
      should_render_ui,
    ));

    let handle = Arc::new(SessionHandle {
      cancelled,
      build_id,
      display,
    });
    scheduler.core.sessions.add(&handle)?;
    Ok(Session {
      handle,
      state: Arc::new(SessionState {
        core: scheduler.core.clone(),
        preceding_graph_size: scheduler.core.graph.len(),
        roots: Mutex::new(HashMap::new()),
        workunit_store,
        session_values: Mutex::new(session_values),
        run_id: Mutex::new(Uuid::new_v4()),
        workunit_metadata_map: RwLock::new(HashMap::new()),
      }),
    })
  }

  ///
  /// Creates a shallow clone of this Session which is independently cancellable, but which shares
  /// metrics, identity, and state with the original.
  ///
  /// Useful when executing background work "on behalf of a Session" which should not be torn down
  /// when a client disconnects.
  ///
  pub fn isolated_shallow_clone(&self, build_id: String) -> Result<Session, String> {
    let display = Mutex::new(SessionDisplay::new(
      &self.state.workunit_store,
      self.state.core.local_parallelism,
      false,
    ));
    let handle = Arc::new(SessionHandle {
      build_id,
      cancelled: AsyncLatch::new(),
      display,
    });
    self.state.core.sessions.add(&handle)?;
    Ok(Session {
      handle,
      state: self.state.clone(),
    })
  }

  pub fn core(&self) -> &Arc<Core> {
    &self.state.core
  }

  ///
  /// Cancels this Session.
  ///
  pub fn cancel(&self) {
    self.handle.cancel();
  }

  ///
  /// Returns only if this Session has been cancelled.
  ///
  pub async fn cancelled(&self) {
    self.handle.cancelled.triggered().await;
  }

  pub fn with_metadata_map<F, T>(&self, f: F) -> T
  where
    F: Fn(&mut HashMap<UserMetadataPyValue, Value>) -> T,
  {
    f(&mut self.state.workunit_metadata_map.write())
  }

  pub fn roots_extend(&self, new_roots: Vec<(Root, Option<LastObserved>)>) {
    let mut roots = self.state.roots.lock();
    roots.extend(new_roots);
  }

  pub fn roots_zip_last_observed(&self, inputs: &[Root]) -> Vec<(Root, Option<LastObserved>)> {
    let roots = self.state.roots.lock();
    inputs
      .iter()
      .map(|root| {
        let last_observed = roots.get(root).cloned().unwrap_or(None);
        (root.clone(), last_observed)
      })
      .collect()
  }

  pub fn roots_nodes(&self) -> Vec<NodeKey> {
    let roots = self.state.roots.lock();
    roots.keys().map(|r| r.clone().into()).collect()
  }

  pub fn session_values(&self) -> Value {
    self.state.session_values.lock().clone()
  }

  pub fn preceding_graph_size(&self) -> usize {
    self.state.preceding_graph_size
  }

  pub fn workunit_store(&self) -> WorkunitStore {
    self.state.workunit_store.clone()
  }

  pub fn build_id(&self) -> &String {
    &self.handle.build_id
  }

  pub fn run_id(&self) -> Uuid {
    let run_id = self.state.run_id.lock();
    *run_id
  }

  pub fn new_run_id(&self) {
    let mut run_id = self.state.run_id.lock();
    *run_id = Uuid::new_v4();
  }

  pub async fn with_console_ui_disabled<T>(&self, f: impl Future<Output = T>) -> T {
    match *self.handle.display.lock() {
      SessionDisplay::ConsoleUI(ref mut ui) => ui.with_console_ui_disabled(f).await,
      SessionDisplay::Logging { .. } => f.await,
    }
  }

  pub fn maybe_display_initialize(&self, executor: &Executor) {
    let result = match *self.handle.display.lock() {
      SessionDisplay::ConsoleUI(ref mut ui) => ui.initialize(executor.clone()),
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
    let teardown = match *self.handle.display.lock() {
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
    match *self.handle.display.lock() {
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
            .state
            .workunit_store
            .log_straggling_workunits(straggler_threshold);
        }
      }
    }
  }
}

///
/// A collection of all live Sessions.
///
/// The `Sessions` struct maintains a task monitoring SIGINT, and cancels all current Sessions each time
/// it arrives.
///
pub struct Sessions {
  /// Live sessions. Completed Sessions (i.e., those for which the Weak reference is dead) are
  /// removed from this collection on a best effort when new Sessions are created.
  ///
  /// If the wrapping Option is None, it is because `fn shutdown` is running, and the associated
  /// Core/Scheduler are being shut down.
  sessions: Arc<Mutex<Option<Vec<Weak<SessionHandle>>>>>,
  /// Handle to kill the signal monitoring task when this object is killed.
  signal_task_abort_handle: AbortHandle,
}

impl Sessions {
  pub fn new(executor: &Executor) -> Result<Sessions, String> {
    let sessions: Arc<Mutex<Option<Vec<Weak<SessionHandle>>>>> =
      Arc::new(Mutex::new(Some(Vec::new())));
    let signal_task_abort_handle = {
      let mut signal_stream = signal(SignalKind::interrupt())
        .map_err(|err| format!("Failed to install interrupt handler: {}", err))?;
      let (abort_handle, abort_registration) = AbortHandle::new_pair();
      let sessions = sessions.clone();
      let _ = executor.spawn(Abortable::new(
        async move {
          loop {
            let _ = signal_stream.recv().await;
            let sessions = sessions.lock();
            if let Some(ref sessions) = *sessions {
              for session in sessions {
                if let Some(session) = session.upgrade() {
                  session.cancel();
                }
              }
            }
          }
        },
        abort_registration,
      ));
      abort_handle
    };
    Ok(Sessions {
      sessions,
      signal_task_abort_handle,
    })
  }

  fn add(&self, handle: &Arc<SessionHandle>) -> Result<(), String> {
    let mut sessions = self.sessions.lock();
    if let Some(ref mut sessions) = *sessions {
      sessions.retain(|weak_handle| weak_handle.upgrade().is_some());
      sessions.push(Arc::downgrade(handle));
      Ok(())
    } else {
      Err("The scheduler is shutting down: no new sessions may be created.".to_string())
    }
  }

  ///
  /// Shuts down this Sessions instance by waiting for all existing Sessions to exit.
  ///
  /// Waits at most `timeout` for Sessions to complete.
  ///
  pub async fn shutdown(&self, timeout: Duration) -> Result<(), String> {
    if let Some(sessions) = self.sessions.lock().take() {
      // Collect clones of the cancellation tokens for each Session, which allows us to watch for
      // them to have been dropped.
      let (build_ids, cancellation_latches): (Vec<_>, Vec<_>) = sessions
        .into_iter()
        .filter_map(|weak_handle| weak_handle.upgrade())
        .map(|handle| {
          let build_id = handle.build_id.clone();
          let cancelled = handle.cancelled.clone();
          let cancellation_triggered = async move {
            cancelled.triggered().await;
            log::info!("Shutdown completed: {:?}", build_id)
          };
          (handle.build_id.clone(), cancellation_triggered)
        })
        .unzip();

      if !build_ids.is_empty() {
        log::info!("Waiting for shutdown of: {:?}", build_ids);
        tokio::time::timeout(timeout, future::join_all(cancellation_latches))
          .await
          .map_err(|_| format!("Some Sessions did not shutdown within {:?}.", timeout))?;
      }
    }
    Ok(())
  }
}

impl Drop for Sessions {
  fn drop(&mut self) {
    self.signal_task_abort_handle.abort();
  }
}
