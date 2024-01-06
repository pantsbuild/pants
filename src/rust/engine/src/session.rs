// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::future::Future;
use std::sync::atomic::{self, AtomicU32};
use std::sync::{Arc, Weak};
use std::time::{Duration, Instant};

use crate::context::{Core, SessionCore};
use crate::nodes::{NodeKey, Select};
use crate::python::{Failure, Value};

use async_latch::AsyncLatch;
use futures::future::{self, FutureExt};
use graph::{Context, LastObserved};
use log::warn;
use parking_lot::Mutex;
use pyo3::prelude::*;
use task_executor::{Executor, TailTasks};
use tokio::signal::unix::{signal, SignalKind};
use tokio::task::JoinHandle;
use ui::{ConsoleUI, LogStreamingLines, LogStreamingTopn};
use workunit_store::{format_workunit_duration_ms, RunId, WorkunitStore};

// When enabled, the interval at which all stragglers that have been running for longer than a
// threshold should be logged. The threshold might become configurable, but this might not need
// to be.
const STRAGGLER_LOGGING_INTERVAL: Duration = Duration::from_secs(30);

// Root requests are limited to Select nodes, which produce (python) Values.
pub type Root = Select;

pub type ObservedValueResult = (Result<Value, Failure>, Option<LastObserved>);

///
/// An enum for the two cases of `--[no-]dynamic-ui`.
///
enum SessionDisplay {
    // The dynamic UI is enabled, and the ConsoleUI should interact with a TTY.
    ConsoleUI(Box<ConsoleUI>),
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
        dynamic_ui: bool,
        dynamic_ui_log_streaming: bool,
        dynamic_ui_log_streaming_lines: LogStreamingLines,
        dynamic_ui_log_streaming_topn: LogStreamingTopn,
        ui_use_prodash: bool,
    ) -> SessionDisplay {
        if dynamic_ui {
            SessionDisplay::ConsoleUI(Box::new(ConsoleUI::new(
                workunit_store.clone(),
                parallelism,
                dynamic_ui_log_streaming,
                dynamic_ui_log_streaming_lines,
                dynamic_ui_log_streaming_topn,
                ui_use_prodash,
            )))
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
    session_values: Mutex<PyObject>,
    // An id used to control the visibility of uncacheable rules. Generally this is identical for an
    // entire Session, but in some cases (in particular, a `--loop`) the caller wants to retain the
    // same Session while still observing new values for uncacheable rules like Goals.
    run_id: AtomicU32,
    /// Tasks to await at the "tail" of the session.
    tail_tasks: TailTasks,
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
    // True if this Session should be shielded from keyboard interrupts (which cancel all
    // non-isolated Sessions).
    isolated: bool,
    // The display mechanism to use in this Session.
    display: tokio::sync::Mutex<SessionDisplay>,
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
        core: Arc<Core>,
        dynamic_ui: bool,
        dynamic_ui_log_streaming: bool,
        dynamic_ui_log_streaming_lines: LogStreamingLines,
        dynamic_ui_log_streaming_topn: LogStreamingTopn,
        ui_use_prodash: bool,
        mut max_workunit_level: log::Level,
        build_id: String,
        session_values: PyObject,
        cancelled: AsyncLatch,
    ) -> Result<Session, String> {
        // We record workunits with the maximum level of:
        // 1. the given `max_workunit_verbosity`, which should be computed from:
        //     * the log level, to ensure that workunit events are logged
        //     * the levels required by any consumers who will call `with_latest_workunits`.
        // 2. the level required by the ConsoleUI (if any): currently, DEBUG.
        if dynamic_ui {
            max_workunit_level = std::cmp::max(max_workunit_level, log::Level::Debug);
        }
        let workunit_store = WorkunitStore::new(
            !dynamic_ui,
            max_workunit_level,
            dynamic_ui && dynamic_ui_log_streaming,
        );
        let display = tokio::sync::Mutex::new(SessionDisplay::new(
            &workunit_store,
            core.local_parallelism,
            dynamic_ui,
            dynamic_ui_log_streaming,
            dynamic_ui_log_streaming_lines,
            dynamic_ui_log_streaming_topn,
            ui_use_prodash,
        ));

        let handle = Arc::new(SessionHandle {
            build_id,
            cancelled,
            isolated: false,
            display,
        });
        core.sessions.add(&handle)?;
        let run_id = core.graph.generate_run_id();
        let preceding_graph_size = core.graph.len();
        Ok(Session {
            handle,
            state: Arc::new(SessionState {
                core,
                preceding_graph_size,
                roots: Mutex::new(HashMap::new()),
                workunit_store,
                session_values: Mutex::new(session_values),
                run_id: AtomicU32::new(run_id.0),
                tail_tasks: TailTasks::new(),
            }),
        })
    }

    ///
    /// Return a `graph::Context` for this Session.
    ///
    pub fn graph_context(&self) -> Context<NodeKey> {
        self.core()
            .graph
            .context_with_run_id(SessionCore::new(self.clone()), self.run_id())
    }

    ///
    /// Creates a shallow clone of this Session which is independently cancellable, but which shares
    /// metrics, identity, and state with the original.
    ///
    /// Useful when executing background work "on behalf of a Session" which should not be torn down
    /// when a client disconnects, or killed by Ctrl+C.
    ///
    pub fn isolated_shallow_clone(&self, build_id: String) -> Result<Session, String> {
        let display = tokio::sync::Mutex::new(SessionDisplay::new(
            &self.state.workunit_store,
            self.state.core.local_parallelism,
            false,
            false,
            LogStreamingLines::Auto,
            LogStreamingTopn::Auto,
            false,
        ));
        let handle = Arc::new(SessionHandle {
            build_id,
            isolated: true,
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
    /// Returns true if this Session has been cancelled.
    ///
    pub fn is_cancelled(&self) -> bool {
        self.handle.cancelled.poll_triggered()
    }

    ///
    /// Returns only if this Session has been cancelled.
    ///
    pub async fn cancelled(&self) {
        self.handle.cancelled.triggered().await;
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

    pub fn session_values(&self) -> PyObject {
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

    pub fn run_id(&self) -> RunId {
        RunId(self.state.run_id.load(atomic::Ordering::SeqCst))
    }

    pub fn new_run_id(&self) {
        self.state.run_id.store(
            self.state.core.graph.generate_run_id().0,
            atomic::Ordering::SeqCst,
        );
    }

    pub async fn with_console_ui_disabled<T>(&self, f: impl Future<Output = T>) -> T {
        match *self.handle.display.lock().await {
            SessionDisplay::ConsoleUI(ref mut ui) => ui.with_console_ui_disabled(f).await,
            SessionDisplay::Logging { .. } => f.await,
        }
    }

    pub async fn maybe_display_initialize(&self, executor: &Executor) {
        let result = match *self.handle.display.lock().await {
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
        let teardown = match *self.handle.display.lock().await {
            SessionDisplay::ConsoleUI(ref mut ui) => ui.teardown(),
            SessionDisplay::Logging {
                ref mut straggler_deadline,
                ..
            } => {
                *straggler_deadline = None;
                futures::future::ready(()).boxed()
            }
        };
        // NB: We await teardown outside of the display lock to remove a lock interleaving. See
        // `ConsoleUI::teardown`.
        teardown.await;
    }

    pub fn maybe_display_render(&self) {
        let mut display = if let Ok(display) = self.handle.display.try_lock() {
            display
        } else {
            // Else, the UI is currently busy: skip rendering.
            return;
        };
        match *display {
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
                    let straggling_workunits = self
                        .state
                        .workunit_store
                        .straggling_workunits(straggler_threshold);
                    if !straggling_workunits.is_empty() {
                        log::info!(
                            "Long running tasks:\n  {}",
                            straggling_workunits
                                .into_iter()
                                .map(|(duration, desc)| format!(
                                    "{}\t{}",
                                    format_workunit_duration_ms!(duration.as_millis()),
                                    desc
                                ))
                                .collect::<Vec<_>>()
                                .join("\n  ")
                        );
                    }
                }
            }
        }
    }

    /// Return a reference to `TailTasks` for this session which monitors tasks representing
    /// asynchronous "tail" tasks that should not block individual nodes in the build graph but
    /// should block the ending of this `Session` (when the `.wait` method is called).
    pub fn tail_tasks(&self) -> TailTasks {
        self.state.tail_tasks.clone()
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
    signal_task_handle: JoinHandle<()>,
}

impl Sessions {
    pub fn new(executor: &Executor) -> Result<Sessions, String> {
        let sessions: Arc<Mutex<Option<Vec<Weak<SessionHandle>>>>> =
            Arc::new(Mutex::new(Some(Vec::new())));
        // A task that watches for keyboard interrupts arriving at this process, and cancels all
        // non-isolated Sessions.
        let signal_task_handle = {
            let mut signal_stream = signal(SignalKind::interrupt())
                .map_err(|err| format!("Failed to install interrupt handler: {err}"))?;
            let sessions = sessions.clone();
            executor.native_spawn(async move {
                loop {
                    let _ = signal_stream.recv().await;
                    let cancellable_sessions = {
                        let sessions = sessions.lock();
                        if let Some(ref sessions) = *sessions {
                            sessions
                                .iter()
                                .flat_map(|session| session.upgrade())
                                .filter(|session| !session.isolated)
                                .collect::<Vec<_>>()
                        } else {
                            vec![]
                        }
                    };
                    for session in cancellable_sessions {
                        session.cancel();
                    }
                }
            })
        };
        Ok(Sessions {
            sessions,
            signal_task_handle,
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
        let sessions_opt = self.sessions.lock().take();
        if let Some(sessions) = sessions_opt {
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
                    .map_err(|_| format!("Some Sessions did not shutdown within {timeout:?}."))?;
            }
        }
        Ok(())
    }
}

impl Drop for Sessions {
    fn drop(&mut self) {
        self.signal_task_handle.abort();
    }
}
