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

use std::future::Future;

use futures::future::FutureExt;
use tokio::runtime::{Handle, Runtime};

#[derive(Clone)]
pub struct Executor {
  handle: Handle,
}

impl Executor {
  pub fn new(handle: Handle) -> Executor {
    Executor { handle }
  }

  ///
  /// Enter the runtime context associated with this Executor. This should be used in situations
  /// where threads not started by the runtime need access to it via task-local variables.
  ///
  pub fn enter<F, R>(&self, f: F) -> R
  where
    F: FnOnce() -> R,
  {
    self.handle.enter(f)
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
    tokio::spawn(Self::future_with_correct_context(future))
      .map(|e| e.expect("Background task exited unsafely."))
  }

  ///
  /// Run a Future and return its resolved Result.
  ///
  /// This should never be called from in a Future context, and should only ever be called in
  /// something that resembles a main method.
  ///
  /// This method makes a new Runtime every time it runs, to ensure that the caller doesn't
  /// accidentally deadlock by using this when a Future attempts to itself call Executor::spawn.
  /// Because it should be used only in very limited situations, this overhead is viewed to be
  /// acceptable.
  ///
  pub fn block_on<F: Future + Send + 'static>(&self, future: F) -> F::Output {
    // Make sure to copy our (thread-local) logging destination into the task.
    // When a daemon thread kicks off a future, it should log like a daemon thread (and similarly
    // for a user-facing thread).
    Runtime::new()
      .unwrap()
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
    let logging_destination = logging::get_destination();
    let workunit_state = workunit_store::get_workunit_state();
    // NB: We unwrap here because the only thing that should cause an error in a spawned task is a
    // panic, in which case we want to propagate that.
    tokio::task::spawn_blocking(move || {
      logging::set_thread_destination(logging_destination);
      workunit_store::set_thread_workunit_state(workunit_state);
      f()
    })
    .map(|e| e.expect("Background task exited unsafely."))
  }

  ///
  /// Copy our (thread-local or task-local) logging destination and current workunit parent into
  /// the task. The former ensures that when a pantsd thread kicks off a future, any logging done
  /// by it ends up in the pantsd log as we expect. The latter ensures that when a new workunit
  /// is created it has an accurate handle to its parent.
  ///
  fn future_with_correct_context<F: Future>(future: F) -> impl Future<Output = F::Output> {
    let logging_destination = logging::get_destination();
    let workunit_state = workunit_store::get_workunit_state();

    // NB: It is important that the first portion of this method is synchronous (meaning that this
    // method cannot be `async`), because that means that it will run on the thread that calls it.
    // The second, async portion of the method will run in the spawned Task.

    logging::scope_task_destination(logging_destination, async move {
      workunit_store::scope_task_workunit_state(workunit_state, future).await
    })
  }
}
