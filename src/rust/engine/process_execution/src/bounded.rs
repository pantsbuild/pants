use std::cmp::{min, Ordering, Reverse};
use std::collections::VecDeque;
use std::future::Future;
use std::sync::{atomic, Arc};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use log::Level;
use parking_lot::Mutex;
use task_executor::Executor;
use tokio::sync::{Notify, Semaphore, SemaphorePermit};
use tokio::time::sleep;
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
  pub fn new(
    executor: &Executor,
    inner: Box<dyn crate::CommandRunner>,
    bound: usize,
  ) -> CommandRunner {
    CommandRunner {
      inner: inner.into(),
      sema: AsyncSemaphore::new(executor, bound),
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

    loop {
      let concurrency_available = permit.concurrency();
      log::debug!(
        "Running {} under semaphore with concurrency id: {}, and concurrency: {}",
        process.description,
        permit.concurrency_slot(),
        concurrency_available,
      );

      if let Some(ref execution_slot_env_var) = process.execution_slot_variable {
        process.env.insert(
          execution_slot_env_var.clone(),
          format!("{}", permit.concurrency_slot()),
        );
      }

      let running_process = self.inner.run(context.clone(), workunit, process.clone());
      tokio::select! {
        _ = permit.notified_concurrency_changed() => {
          log::debug!(
            "Process {} was preempted, and went from concurrency {} to concurrency {}",
            process.description,
            concurrency_available,
            permit.concurrency(),
          );
          continue;
        },
        res = running_process => {
          // The process completed.
          return res;
        }
      }
    }
  }
}

/// A wrapped Semaphore which adds concurrency metadata which supports overcommit.
#[derive(Clone)]
pub(crate) struct AsyncSemaphore {
  sema: Arc<Semaphore>,
  state: Arc<Mutex<State>>,
  preemptible_duration: Duration,
}

struct State {
  available_ids: VecDeque<usize>,
  tasks: Vec<Arc<Task>>,
}

impl AsyncSemaphore {
  pub fn new(executor: &Executor, permits: usize) -> AsyncSemaphore {
    let mut available_ids = VecDeque::new();
    for id in 1..=permits {
      available_ids.push_back(id);
    }

    let state = Arc::new(Mutex::new(State {
      available_ids,
      tasks: Vec::new(),
    }));
    // TODO: Make configurable.
    let preemptible_duration = Duration::from_millis(200);

    // Spawn a task which will periodically balance Tasks.
    let _balancer_task = {
      let state = Arc::downgrade(&state);
      executor.spawn(async move {
        loop {
          sleep(preemptible_duration / 4).await;
          if let Some(state) = state.upgrade() {
            // Balance tasks.
            let state = state.lock();
            balance(
              permits,
              Instant::now(),
              state.tasks.iter().map(|t| t.as_ref()).collect(),
            );
          } else {
            // The AsyncSemaphore was torn down.
            break;
          }
        }
      })
    };

    AsyncSemaphore {
      sema: Arc::new(Semaphore::new(permits)),
      state,
      preemptible_duration,
    }
  }

  // TODO: https://github.com/rust-lang/rust/issues/46379
  #[allow(dead_code)]
  pub(crate) fn available_permits(&self) -> usize {
    self.sema.available_permits()
  }

  ///
  /// Runs the given Future-creating function (and the Future it returns) under the semaphore.
  ///
  // TODO: https://github.com/rust-lang/rust/issues/46379
  #[allow(dead_code)]
  pub(crate) async fn with_acquired<F, B, O>(self, f: F) -> O
  where
    F: FnOnce(usize) -> B,
    B: Future<Output = O>,
  {
    let permit = self.acquire().await;
    let res = f(permit.task.id).await;
    drop(permit);
    res
  }

  pub async fn acquire(&self) -> Permit<'_> {
    let permit = self.sema.acquire().await.expect("semaphore closed");
    let task = {
      let mut state = self.state.lock();
      let id = state
        .available_ids
        .pop_front()
        .expect("More permits were distributed than ids exist.");
      // TODO: Configure and calculate concurrency.
      let task = Arc::new(Task::new(
        id,
        1,
        1,
        Instant::now() + self.preemptible_duration,
      ));
      state.tasks.push(task.clone());
      task
    };
    Permit {
      state: self.state.clone(),
      _permit: permit,
      task,
    }
  }
}

pub struct Permit<'a> {
  state: Arc<Mutex<State>>,
  // NB: Kept for its `Drop` impl.
  _permit: SemaphorePermit<'a>,
  task: Arc<Task>,
}

impl Permit<'_> {
  pub fn concurrency_slot(&self) -> usize {
    self.task.id
  }

  pub fn concurrency(&self) -> usize {
    self.task.concurrency()
  }

  pub async fn notified_concurrency_changed(&self) {
    self.task.notify_concurrency_changed.notified().await
  }
}

impl<'a> Drop for Permit<'a> {
  fn drop(&mut self) {
    let mut state = self.state.lock();
    state.available_ids.push_back(self.task.id);
    let tasks_position = state
      .tasks
      .iter()
      .position(|t| t.id == self.task.id)
      .unwrap();
    state.tasks.swap_remove(tasks_position);
  }
}

pub(crate) struct Task {
  id: usize,
  concurrency_desired: usize,
  pub(crate) concurrency_actual: atomic::AtomicUsize,
  notify_concurrency_changed: Notify,
  preemptible_until: Instant,
}

impl Task {
  pub(crate) fn new(
    id: usize,
    concurrency_desired: usize,
    concurrency_actual: usize,
    preemptible_until: Instant,
  ) -> Self {
    assert!(concurrency_actual <= concurrency_desired);
    Self {
      id,
      concurrency_desired,
      concurrency_actual: atomic::AtomicUsize::new(concurrency_actual),
      notify_concurrency_changed: Notify::new(),
      preemptible_until,
    }
  }

  pub(crate) fn concurrency(&self) -> usize {
    self.concurrency_actual.load(atomic::Ordering::SeqCst)
  }

  fn preemptible(&self, now: Instant) -> bool {
    self.preemptible_until > now
  }
}

/// Given a set of Tasks with their desired and actual concurrency, balance the concurrency levels
/// of any preemptible tasks, and notify them of the changes.
///
/// Returns the number of Tasks that were preempted.
pub(crate) fn balance(concurrency_limit: usize, now: Instant, tasks: Vec<&Task>) -> usize {
  let concurrency_used: usize = tasks.iter().map(|t| t.concurrency()).sum();
  let mut desired_change_in_commitment = concurrency_limit as isize - concurrency_used as isize;
  let mut prempted = 0;

  // To reduce the number of tasks that we preempty, we preempt them in order by the amount of
  // concurrency that they desire or can relinquish.
  match desired_change_in_commitment.cmp(&0) {
    Ordering::Equal => {
      // Nothing to do! Although some tasks might not have their desired concurrency levels, it's
      // probably not worth preempting any tasks to fix that.
    }
    Ordering::Less => {
      // We're overcommitted: order by the amount that they can relinquish.
      let mut preemptible_tasks = tasks
        .iter()
        .filter_map(|t| {
          // A task may never have less than one slot.
          let relinquishable = t.concurrency() - 1;
          if relinquishable > 0 && t.preemptible(now) {
            Some((relinquishable, t))
          } else {
            None
          }
        })
        .collect::<Vec<_>>();
      preemptible_tasks.sort_by_key(|(relinquishable, _)| Reverse(*relinquishable));

      for (relinquishable, task) in preemptible_tasks {
        if desired_change_in_commitment == 0 {
          break;
        }

        let relinquish = min(relinquishable, (-desired_change_in_commitment) as usize);
        desired_change_in_commitment += relinquish as isize;
        task
          .concurrency_actual
          .fetch_sub(relinquish, atomic::Ordering::SeqCst);
        task.notify_concurrency_changed.notify_one();
        prempted += 1;
      }
    }
    Ordering::Greater => {
      // We're undercommitted: order by the amount that they are owed.
      let mut preemptible_tasks = tasks
        .iter()
        .filter_map(|t| {
          let desired = t.concurrency_desired - t.concurrency();
          if desired > 0 && t.preemptible(now) {
            Some((desired, t))
          } else {
            None
          }
        })
        .collect::<Vec<_>>();
      preemptible_tasks.sort_by_key(|(desired, _)| Reverse(*desired));

      for (desired, task) in preemptible_tasks {
        if desired_change_in_commitment == 0 {
          break;
        }

        let acquire = min(desired, desired_change_in_commitment as usize);
        desired_change_in_commitment -= acquire as isize;
        task
          .concurrency_actual
          .fetch_add(acquire, atomic::Ordering::SeqCst);
        task.notify_concurrency_changed.notify_one();
        prempted += 1;
      }
    }
  }

  prempted
}
