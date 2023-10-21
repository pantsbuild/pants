// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
    clippy::all,
    clippy::default_trait_access,
    clippy::expl_impl_clone_on_copy,
    clippy::if_not_else,
    clippy::needless_continue,
    clippy::unseparated_literal_suffix,
    clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
    clippy::len_without_is_empty,
    clippy::redundant_field_names,
    clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use std::collections::HashMap;
use std::env;
use std::future::Future;
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures::future::FutureExt;
use itertools::Itertools;
use parking_lot::Mutex;
use tokio::runtime::{Builder, Handle, Runtime};
use tokio::task::{Id, JoinError, JoinHandle, JoinSet};

/// Copy our (thread-local or task-local) stdio destination and current workunit parent into
/// the task. The former ensures that when a pantsd thread kicks off a future, any stdio done
/// by it ends up in the pantsd log as we expect. The latter ensures that when a new workunit
/// is created it has an accurate handle to its parent.
fn future_with_correct_context<F: Future>(future: F) -> impl Future<Output = F::Output> {
    let stdio_destination = stdio::get_destination();
    let workunit_store_handle = workunit_store::get_workunit_store_handle();

    // NB: It is important that the first portion of this method is synchronous (meaning that this
    // method cannot be `async`), because that means that it will run on the thread that calls it.
    // The second, async portion of the method will run in the spawned Task.

    stdio::scope_task_destination(stdio_destination, async move {
        workunit_store::scope_task_workunit_store_handle(workunit_store_handle, future).await
    })
}

///
/// Executors come in two flavors:
/// * "borrowed"
///     * Created with `Self::new()`, or `self::to_borrowed()`.
///     * A borrowed Executor will not be shut down when all handles are dropped, and shutdown
///       methods will have no impact.
///     * Used when multiple runs of Pants will borrow a single Executor owned by `pantsd`, and in
///       unit tests where the Runtime is created by macros.
/// * "owned"
///     * Created with `Self::new_owned()`.
///     * When all handles of a owned Executor are dropped, its Runtime will be shut down.
///       Additionally, the explicit shutdown methods can be used to shut down the Executor for all
///       clones.
///
#[derive(Debug, Clone)]
pub struct Executor {
    runtime: Arc<Mutex<Option<Runtime>>>,
    handle: Handle,
}

impl Executor {
    ///
    /// Creates an Executor for an existing tokio::Runtime (generally provided by tokio's macros).
    ///
    /// The returned Executor will have a lifecycle independent of the Runtime, meaning that dropping
    /// all clones of the Executor will not cause the Runtime to be shut down. Likewise, the owner of
    /// the Runtime must ensure that it is kept alive longer than all Executor instances, because
    /// existence of a Handle does not prevent a Runtime from shutting down. This is guaranteed by
    /// the scope of the tokio::{test, main} macros.
    ///
    pub fn new() -> Executor {
        Self {
            runtime: Arc::new(Mutex::new(None)),
            handle: Handle::current(),
        }
    }

    ///
    /// Gets a reference to a global static Executor with an owned tokio::Runtime, initializing it
    /// with the given thread configuration if this is the first usage.
    ///
    /// NB: The global static Executor eases lifecycle issues when consumed from Python, where we
    /// need thread configurability, but also want to know reliably when the Runtime will shutdown
    /// (which, because it is static, will only be at the entire process' exit).
    ///
    pub fn new_owned<F>(
        num_worker_threads: usize,
        max_threads: usize,
        on_thread_start: F,
    ) -> Result<Executor, String>
    where
        F: Fn() + Send + Sync + 'static,
    {
        let mut runtime_builder = Builder::new_multi_thread();

        runtime_builder
            .worker_threads(num_worker_threads)
            .max_blocking_threads(max_threads - num_worker_threads)
            .enable_all();

        if env::var("PANTS_DEBUG").is_ok() {
            runtime_builder.on_thread_start(on_thread_start);
        };

        let runtime = runtime_builder
            .build()
            .map_err(|e| format!("Failed to start the runtime: {e}"))?;

        let handle = runtime.handle().clone();
        Ok(Executor {
            runtime: Arc::new(Mutex::new(Some(runtime))),
            handle,
        })
    }

    ///
    /// Creates a clone of this Executor which is disconnected from shutdown events. See the `Executor`
    /// rustdoc.
    ///
    pub fn to_borrowed(&self) -> Executor {
        Self {
            runtime: Arc::new(Mutex::new(None)),
            handle: self.handle.clone(),
        }
    }

    ///
    /// Enter the runtime context associated with this Executor. This should be used in situations
    /// where threads not started by the runtime need access to it via task-local variables.
    ///
    pub fn enter<F, R>(&self, f: F) -> R
    where
        F: FnOnce() -> R,
    {
        let _context = self.handle.enter();
        f()
    }

    ///
    /// Run a Future on a tokio Runtime as a new Task, and return a Future handle to it.
    ///
    /// If the background Task exits abnormally, the given closure will be called to recover: usually
    /// it should convert the resulting Error to a relevant error type.
    ///
    /// If the returned Future is dropped, the computation will still continue to completion: see
    /// <https://docs.rs/tokio/0.2.20/tokio/task/struct.JoinHandle.html>
    ///
    pub fn spawn<O: Send + 'static, F: Future<Output = O> + Send + 'static>(
        &self,
        future: F,
        rescue_join_error: impl FnOnce(JoinError) -> O,
    ) -> impl Future<Output = O> {
        self.native_spawn(future).map(|res| match res {
            Ok(o) => o,
            Err(e) => rescue_join_error(e),
        })
    }

    ///
    /// Run a Future on a tokio Runtime as a new Task, and return a JoinHandle.
    ///
    pub fn native_spawn<O: Send + 'static, F: Future<Output = O> + Send + 'static>(
        &self,
        future: F,
    ) -> JoinHandle<O> {
        self.handle.spawn(future_with_correct_context(future))
    }

    ///
    /// Run a Future and return its resolved Result.
    ///
    /// This should never be called from in a Future context, and should only ever be called in
    /// something that resembles a main method.
    ///
    /// Even after this method returns, work `spawn`ed into the background may continue to run on the
    /// threads owned by this Executor.
    ///
    pub fn block_on<F: Future>(&self, future: F) -> F::Output {
        // Make sure to copy our (thread-local) logging destination into the task.
        // When a daemon thread kicks off a future, it should log like a daemon thread (and similarly
        // for a user-facing thread).
        self.handle.block_on(future_with_correct_context(future))
    }

    ///
    /// Spawn a Future on a threadpool specifically reserved for I/O tasks which are allowed to be
    /// long-running.
    ///
    /// If the background Task exits abnormally, the given closure will be called to recover: usually
    /// it should convert the resulting Error to a relevant error type.
    ///
    /// If the returned Future is dropped, the computation will still continue to completion: see
    /// <https://docs.rs/tokio/0.2.20/tokio/task/struct.JoinHandle.html>
    ///
    pub fn spawn_blocking<F: FnOnce() -> R + Send + 'static, R: Send + 'static>(
        &self,
        f: F,
        rescue_join_error: impl FnOnce(JoinError) -> R,
    ) -> impl Future<Output = R> {
        self.native_spawn_blocking(f).map(|res| match res {
            Ok(o) => o,
            Err(e) => rescue_join_error(e),
        })
    }

    ///
    /// Spawn a Future on threads specifically reserved for I/O tasks which are allowed to be
    /// long-running and return a JoinHandle
    ///
    pub fn native_spawn_blocking<F: FnOnce() -> R + Send + 'static, R: Send + 'static>(
        &self,
        f: F,
    ) -> JoinHandle<R> {
        let stdio_destination = stdio::get_destination();
        let workunit_store_handle = workunit_store::get_workunit_store_handle();
        // NB: We unwrap here because the only thing that should cause an error in a spawned task is a
        // panic, in which case we want to propagate that.
        self.handle.spawn_blocking(move || {
            stdio::set_thread_destination(stdio_destination);
            workunit_store::set_thread_workunit_store_handle(workunit_store_handle);
            f()
        })
    }

    /// Return a reference to this executor's runtime handle.
    pub fn handle(&self) -> &Handle {
        &self.handle
    }

    ///
    /// A blocking call to shut down the Runtime associated with this "owned" Executor. If tasks do
    /// not shut down within the given timeout, they are leaked.
    ///
    /// This method has no effect for "borrowed" Executors: see the `Executor` rustdoc.
    ///
    pub fn shutdown(&self, timeout: Duration) {
        let Some(runtime) = self.runtime.lock().take() else { return };

        let start = Instant::now();
        runtime.shutdown_timeout(timeout + Duration::from_millis(250));
        if start.elapsed() > timeout {
            // Leaked tasks could lead to panics in some cases (see #16105), so warn for them.
            log::warn!("Executor shutdown took unexpectedly long: tasks were likely leaked!");
        }
    }

    /// Returns true if `shutdown` has been called for this Executor. Always returns true for
    /// borrowed Executors.
    pub fn is_shutdown(&self) -> bool {
        self.runtime.lock().is_none()
    }
}

/// Store "tail" tasks which are async tasks that can execute concurrently with regular
/// build actions. Tail tasks block completion of a session until all of them have been
/// completed (subject to a timeout).
#[derive(Clone)]
pub struct TailTasks {
    inner: Arc<Mutex<Option<TailTasksInner>>>,
}

struct TailTasksInner {
    id_to_name: HashMap<Id, String>,
    task_set: JoinSet<()>,
}

impl TailTasks {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(Some(TailTasksInner {
                id_to_name: HashMap::new(),
                task_set: JoinSet::new(),
            }))),
        }
    }

    /// Spawn a tail task with the given name.
    pub fn spawn_on<F>(&self, name: &str, handle: &Handle, task: F)
    where
        F: Future<Output = ()>,
        F: Send + 'static,
    {
        let task = future_with_correct_context(task);
        let mut guard = self.inner.lock();
        let inner = match &mut *guard {
            Some(inner) => inner,
            None => {
                log::warn!(
                    "Session end task `{}` submitted after session completed.",
                    name
                );
                return;
            }
        };

        let h = inner.task_set.spawn_on(task, handle);
        inner.id_to_name.insert(h.id(), name.to_string());
    }

    /// Wait for all tail tasks to complete subject to the given timeout. If tasks
    /// fail or do not complete, log that fact.
    pub async fn wait(self, timeout: Duration) {
        let mut inner = match self.inner.lock().take() {
            Some(inner) => inner,
            None => {
                log::debug!("Session end tasks awaited multiple times!");
                return;
            }
        };

        if inner.task_set.is_empty() {
            return;
        }

        log::debug!(
            "waiting for {} session end task(s) to complete",
            inner.task_set.len()
        );

        let mut timeout = tokio::time::sleep(timeout).boxed();

        loop {
            tokio::select! {
              // Use biased mode to prefer an expired timeout over joining on remaining tasks.
              biased;

              // Exit monitoring loop if timeout expires.
              _ = &mut timeout => break,

              next_result = inner.task_set.join_next_with_id() => {
                match next_result {
                  Some(Ok((id, _))) => {
                    if let Some(name) = inner.id_to_name.get(&id) {
                      log::trace!("Session end task `{name}` completed successfully");
                    } else {
                      log::debug!("Session end task completed successfully but name not found.");
                    }
                    inner.id_to_name.remove(&id);
                  },
                  Some(Err(err)) => {
                    let name = inner.id_to_name.get(&err.id());
                    log::error!("Session end task `{name:?}` failed: {err:?}");
                  }
                  None => break,
                }
              }
            }
        }

        if inner.task_set.is_empty() {
            log::debug!("all session end tasks completed successfully");
        } else {
            log::debug!(
                "{} session end task(s) failed to complete within timeout: {}",
                inner.task_set.len(),
                inner.id_to_name.values().join(", "),
            );
            inner.task_set.abort_all();
        }
    }
}
