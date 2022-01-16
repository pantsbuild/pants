use std::collections::VecDeque;
use std::future::Future;
use std::sync::Arc;

use async_trait::async_trait;
use log::Level;
use parking_lot::Mutex;
use tokio::sync::{Semaphore, SemaphorePermit};
use workunit_store::{in_workunit, RunningWorkunit, WorkunitMetadata};

use crate::{Context, FallibleProcessResultWithPlatform, Process};

///
/// A CommandRunner wrapper which limits the number of concurrent requests and which provides
/// concurrency information to the process being executed.
///
#[derive(Clone)]
pub struct CommandRunner {
  inner: Arc<dyn crate::CommandRunner>,
  sema: AsyncSemaphore,
}

impl CommandRunner {
  pub fn new(inner: Box<dyn crate::CommandRunner>, bound: usize) -> CommandRunner {
    CommandRunner {
      inner: inner.into(),
      sema: AsyncSemaphore::new(bound),
    }
  }
}

#[async_trait]
impl crate::CommandRunner for CommandRunner {
  async fn run(
    &self,
    context: Context,
    workunit: &mut RunningWorkunit,
    mut process: Process,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    let semaphore_acquisition = self.sema.acquire();
    let permit = in_workunit!(
      context.workunit_store.clone(),
      "acquire_command_runner_slot".to_owned(),
      WorkunitMetadata {
        level: Level::Trace,
        ..WorkunitMetadata::default()
      },
      |workunit| async move {
        let _blocking_token = workunit.blocking();
        semaphore_acquisition.await
      }
    )
    .await;

    log::debug!(
      "Running {} under semaphore with concurrency id: {}",
      process.description,
      permit.concurrency_slot()
    );

    if let Some(ref execution_slot_env_var) = process.execution_slot_variable {
      process.env.insert(
        execution_slot_env_var.clone(),
        format!("{}", permit.concurrency_slot()),
      );
    }

    self.inner.run(context, workunit, process).await
  }
}

/// A wrapped Semaphore which adds concurrency metadata which supports overcommit.
#[derive(Clone)]
pub(crate) struct AsyncSemaphore {
  sema: Arc<Semaphore>,
  state: Arc<Mutex<State>>,
}

struct State {
  available_ids: VecDeque<usize>,
}

impl AsyncSemaphore {
  pub fn new(permits: usize) -> AsyncSemaphore {
    let mut available_ids = VecDeque::new();
    for id in 1..=permits {
      available_ids.push_back(id);
    }

    AsyncSemaphore {
      sema: Arc::new(Semaphore::new(permits)),
      state: Arc::new(Mutex::new(State { available_ids })),
    }
  }

  // TODO: Used in tests, but not detected for some reason.
  #[allow(dead_code)]
  pub(crate) fn available_permits(&self) -> usize {
    self.sema.available_permits()
  }

  ///
  /// Runs the given Future-creating function (and the Future it returns) under the semaphore.
  ///
  /// TODO: Used in tests, but not detected for some reason.
  #[allow(dead_code)]
  pub(crate) async fn with_acquired<F, B, O>(self, f: F) -> O
  where
    F: FnOnce(usize) -> B,
    B: Future<Output = O>,
  {
    let permit = self.acquire().await;
    let res = f(permit.id).await;
    drop(permit);
    res
  }

  pub async fn acquire(&self) -> Permit<'_> {
    let permit = self.sema.acquire().await.expect("semaphore closed");
    let id = {
      let mut state = self.state.lock();
      state
        .available_ids
        .pop_front()
        .expect("More permits were distributed than ids exist.")
    };
    Permit {
      state: self.state.clone(),
      _permit: permit,
      id,
    }
  }
}

pub struct Permit<'a> {
  state: Arc<Mutex<State>>,
  // NB: Kept for its `Drop` impl.
  _permit: SemaphorePermit<'a>,
  id: usize,
}

impl Permit<'_> {
  pub fn concurrency_slot(&self) -> usize {
    self.id
  }
}

impl<'a> Drop for Permit<'a> {
  fn drop(&mut self) {
    let mut state = self.state.lock();
    state.available_ids.push_back(self.id);
  }
}
