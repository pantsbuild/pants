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

use std::env;
use std::future::Future;
use std::sync::Arc;

use arc_swap::ArcSwapOption;
use futures::future::FutureExt;
use lazy_static::lazy_static;
use tokio::runtime::{Builder, Handle, Runtime};

lazy_static! {
    // Lazily initialized in Executor::global.
    static ref GLOBAL_EXECUTOR: ArcSwapOption<Runtime> = ArcSwapOption::from_pointee(None);
}

#[derive(Debug, Clone)]
pub struct Executor {
    _runtime: Option<Arc<Runtime>>,
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
        Executor {
            _runtime: None,
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
    pub fn global<F>(
        num_worker_threads: usize,
        max_threads: usize,
        on_thread_start: F,
    ) -> Result<Executor, String>
    where
        F: Fn() + Send + Sync + Clone + 'static,
    {
        let global = GLOBAL_EXECUTOR.load();
        if let Some(ref runtime) = *global {
            return Ok(Executor {
                _runtime: Some(runtime.clone()),
                handle: runtime.handle().clone(),
            });
        }

        let mut runtime_builder = Builder::new_multi_thread();

        runtime_builder
            .worker_threads(num_worker_threads)
            .max_blocking_threads(max_threads - num_worker_threads)
            .enable_all();

        if env::var("PANTS_DEBUG").is_ok() {
            runtime_builder.on_thread_start(on_thread_start.clone());
        };

        let runtime = runtime_builder
            .build()
            .map_err(|e| format!("Failed to start the runtime: {}", e))?;

        // Attempt to swap, then recurse to retry.
        GLOBAL_EXECUTOR.compare_and_swap(global, Some(Arc::new(runtime)));
        Self::global(num_worker_threads, max_threads, on_thread_start)
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
    /// Unlike tokio::spawn, if the background Task panics, the returned Future will too.
    ///
    /// If the returned Future is dropped, the computation will still continue to completion: see
    /// https://docs.rs/tokio/0.2.20/tokio/task/struct.JoinHandle.html
    ///
    pub fn spawn<O: Send + 'static, F: Future<Output = O> + Send + 'static>(
        &self,
        future: F,
    ) -> impl Future<Output = O> {
        self.handle
            .spawn(Self::future_with_correct_context(future))
            .map(|r| r.expect("Background task exited unsafely."))
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
        self.handle
            .block_on(Self::future_with_correct_context(future))
    }

    ///
    /// Spawn a Future on a threadpool specifically reserved for I/O tasks which are allowed to be
    /// long-running.
    ///
    /// Unlike tokio::task::spawn_blocking, If the background Task panics, the returned Future will
    /// too.
    ///
    /// If the returned Future is dropped, the computation will still continue to completion: see
    /// https://docs.rs/tokio/0.2.20/tokio/task/struct.JoinHandle.html
    ///
    pub fn spawn_blocking<F: FnOnce() -> R + Send + 'static, R: Send + 'static>(
        &self,
        f: F,
    ) -> impl Future<Output = R> {
        let stdio_destination = stdio::get_destination();
        let workunit_store_handle = workunit_store::get_workunit_store_handle();
        // NB: We unwrap here because the only thing that should cause an error in a spawned task is a
        // panic, in which case we want to propagate that.
        self.handle
            .spawn_blocking(move || {
                stdio::set_thread_destination(stdio_destination);
                workunit_store::set_thread_workunit_store_handle(workunit_store_handle);
                f()
            })
            .map(|r| r.expect("Background task exited unsafely."))
    }

    ///
    /// Copy our (thread-local or task-local) stdio destination and current workunit parent into
    /// the task. The former ensures that when a pantsd thread kicks off a future, any stdio done
    /// by it ends up in the pantsd log as we expect. The latter ensures that when a new workunit
    /// is created it has an accurate handle to its parent.
    ///
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
}
