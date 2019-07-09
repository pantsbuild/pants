use futures::Future;
use std::sync::Arc;
use tokio::runtime::Runtime;

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
      .spawn(Self::future_with_correct_logging_context(future))
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
    futures::sync::oneshot::spawn(
      Self::future_with_correct_logging_context(future),
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
      .block_on(Self::future_with_correct_logging_context(future))
  }

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
      .spawn(Self::future_with_correct_logging_context(future))
  }

  ///
  /// Copy our (thread-local or task-local) logging destination into the task.
  ///
  /// This helps us to ensure that when a pantsd thread kicks off a future, any logging done by it
  /// ends up in the pantsd log as we expect.
  ///
  fn future_with_correct_logging_context<Item, Error, F: Future<Item = Item, Error = Error>>(
    future: F,
  ) -> impl Future<Item = Item, Error = Error> {
    let logging_destination = crate::get_destination();
    futures::lazy(move || {
      crate::set_destination(logging_destination);
      future
    })
  }
}
