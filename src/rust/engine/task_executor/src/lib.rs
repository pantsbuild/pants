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

use futures::future::{BoxFuture, FutureExt};

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
  /// Drive running of a Future on a tokio Runtime as a new Task.
  ///
  /// The future will be driven to completion, but the result can't be accessed directly.
  ///
  /// This may be useful e.g. if you want to kick off a potentially long-running task, which will
  /// notify dependees of its completion over an mpsc channel.
  ///
  pub fn spawn_and_ignore<F: Future<Output = ()> + Send + 'static>(&self, future: F) {
    tokio::spawn(Self::future_with_correct_context(future));
  }

  ///
  /// Run a Future on a tokio Runtime as a new Task, and return a Future handle to it.
  ///
  /// If the returned Future is dropped, the computation will still continue to completion: see the
  /// tokio::task::JoinHandle docs.
  ///
  /// This may be useful for tokio tasks which use the tokio blocking feature (unrelated to the
  /// Executor::block_on method). When tokio blocking tasks run, they prevent progress on any
  /// futures running in the same task. e.g. if you run f1.select(f2) and f1 and f2 are
  /// tokio blocking futures, f1 and f2 will not run in parallel, defeating the point of select.
  ///
  /// On the other hand, if you run:
  /// spawn_oneshot(f1).select(spawn_oneshot(f2))
  /// those futures will run in parallel.
  ///
  /// Using spawn_oneshot allows for selecting the granularity when using tokio blocking.
  ///
  /// See https://docs.rs/tokio-threadpool/0.1.15/tokio_threadpool/fn.blocking.html for details of
  /// tokio blocking.
  ///
  pub async fn spawn_oneshot<O: Send + 'static, F: Future<Output = O> + Send + 'static>(
    &self,
    future: F,
  ) -> O {
    // NB: We unwrap here because the only thing that should cause an error in a spawned task is a
    // panic, in which case we want to propagate that.
    tokio::spawn(Self::future_with_correct_context(future))
      .await
      .unwrap()
  }

  ///
  /// Run a Future and return its resolved Result.
  ///
  /// This should never be called from in a Future context, and should only ever be called in
  /// something that resembles a main method.
  ///
  /// This method makes a new Runtime every time it runs, to ensure that the caller doesn't
  /// accidentally deadlock by using this when a Future attempts to itself call
  /// Executor::spawn_and_ignore or Executor::spawn_oneshot. Because it should be used only in very
  /// limited situations, this overhead is viewed to be acceptable.
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
  /// At some point in the future we may want to migrate to use tokio-threadpool's blocking
  /// functionality instead of this threadpool, but we've run into teething issues where introducing
  /// it has caused significant performance regressions, so for how we continue to use our legacy
  /// I/O CpuPool. Hopefully we can delete this method at some point.
  ///
  /// TODO: See the note on references in ASYNC.md.
  ///
  pub fn spawn_blocking<'a, 'b, F: FnOnce() -> R + Send + 'static, R: Send + 'static>(
    &'a self,
    f: F,
  ) -> BoxFuture<'b, R> {
    let logging_destination = logging::get_destination();
    let workunit_parent_id = workunit_store::get_parent_id();
    // NB: We unwrap here because the only thing that should cause an error in a spawned task is a
    // panic, in which case we want to propagate that.
    tokio::task::spawn_blocking(move || {
      logging::set_thread_destination(logging_destination);
      workunit_store::set_thread_parent_id(workunit_parent_id);
      f()
    })
    .map(|res| res.unwrap())
    .boxed()
  }

  ///
  /// Copy our (thread-local or task-local) logging destination and current workunit parent into
  /// the task. The former ensures that when a pantsd thread kicks off a future, any logging done
  /// by it ends up in the pantsd log as we expect. The latter ensures that when a new workunit
  /// is created it has an accurate handle to its parent.
  ///
  fn future_with_correct_context<F: Future>(future: F) -> impl Future<Output = F::Output> {
    let logging_destination = logging::get_destination();
    let workunit_parent_id = workunit_store::get_parent_id();

    // NB: It is important that the first portion of this method is synchronous (meaning that this
    // method cannot be `async`), because that means that it will run on the thread that calls it.
    // The second, async portion of the method will run in the spawned Task.

    logging::scope_task_destination(logging_destination, async move {
      workunit_store::scope_task_parent_id(workunit_parent_id, future).await
    })
  }
}
