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

use futures01::{future, Future};
use std::sync::Arc;
use tokio::runtime::Runtime;

// TODO: It's strange that this is an exposed interface from the logging crate, rather than an
// implementation of a trait that lives elsewhere. This can't currently be a trait because its
// methods have generic types, which isn't allowed on traits. If we can move the API somewhere else
// in the future, that could be nice.

#[derive(Clone)]
pub struct Executor {
  runtime: Arc<Runtime>,
  io_pool: futures_cpupool::CpuPool,
}

impl Executor {
  pub fn new() -> Executor {
    Executor {
      runtime: Arc::new(
        Runtime::new().unwrap_or_else(|e| panic!("Could not initialize Runtime: {:?}", e)),
      ),
      io_pool: futures_cpupool::CpuPool::new_num_cpus(),
    }
  }

  ///
  /// Drive running of a Future on a tokio Runtime as a new Task.
  ///
  /// The future will be driven to completion, but the result can't be accessed directly.
  ///
  /// This may be useful e.g. if you want to kick off a potentially long-running task, which will
  /// notify dependees of its completion over an mpsc channel.
  ///
  pub fn spawn_and_ignore<F: Future<Item = (), Error = ()> + Send + 'static>(&self, future: F) {
    self
      .runtime
      .executor()
      .spawn(Self::future_with_correct_context(future))
  }

  ///
  /// Run a Future on a tokio Runtime as a new Task, and return a Future handle to it.
  ///
  /// The future will only be driven to completion if something drives the returned Future. If the
  /// returned Future is dropped, the computation may be cancelled.
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
  pub fn spawn_oneshot<
    Item: Send + 'static,
    Error: Send + 'static,
    F: Future<Item = Item, Error = Error> + Send + 'static,
  >(
    &self,
    future: F,
  ) -> impl Future<Item = Item, Error = Error> {
    futures01::sync::oneshot::spawn(
      Self::future_with_correct_context(future),
      &self.runtime.executor(),
    )
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
  pub fn block_on<
    Item: Send + 'static,
    Error: Send + 'static,
    F: Future<Item = Item, Error = Error> + Send + 'static,
  >(
    &self,
    future: F,
  ) -> Result<Item, Error> {
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
  pub fn spawn_on_io_pool<
    Item: Send + 'static,
    Error: Send + 'static,
    F: Future<Item = Item, Error = Error> + Send + 'static,
  >(
    &self,
    future: F,
  ) -> impl Future<Item = Item, Error = Error> {
    self
      .io_pool
      .spawn(Self::future_with_correct_context(future))
  }

  ///
  /// Copy our (thread-local or task-local) logging destination and current workunit parent into
  /// the task. The former ensures that when a pantsd thread kicks off a future, any logging done
  /// by it ends up in the pantsd log as we expect. The latter ensures that when a new workunit
  /// is created it has an accurate handle to its parent.
  ///
  fn future_with_correct_context<Item, Error, F: Future<Item = Item, Error = Error>>(
    future: F,
  ) -> impl Future<Item = Item, Error = Error> {
    let logging_destination = logging::get_destination();
    let workunit_parent_id = workunit_store::get_parent_id();
    future::lazy(move || {
      logging::set_destination(logging_destination);
      if let Some(parent_id) = workunit_parent_id {
        workunit_store::set_parent_id(parent_id);
      }
      future
    })
  }
}
