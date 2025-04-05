// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::borrow::Cow;
use std::cmp::{Ordering, Reverse, max, min};
use std::collections::VecDeque;
use std::fmt::{self, Debug};
use std::future::Future;
use std::sync::LazyLock;
use std::sync::{Arc, atomic};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use log::Level;
use parking_lot::Mutex;
use regex::Regex;
use task_executor::Executor;
use tokio::sync::{Notify, Semaphore, SemaphorePermit};
use tokio::time::sleep;
use workunit_store::{RunningWorkunit, in_workunit};

use crate::{
    Context, FallibleProcessResultWithPlatform, Process, ProcessConcurrency, ProcessError,
};

// TODO: Runtime formatting is unstable in Rust, so we imitate it.
static CONCURRENCY_TEMPLATE_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\{pants_concurrency\}").unwrap());

///
/// A CommandRunner wrapper which limits the number of concurrent requests and which provides
/// concurrency information to the process being executed.
///
/// If a Process sets a non-zero `concurrency_available` value, it may be preempted (i.e. canceled
/// and restarted) with a new concurrency value for a short period after starting.
///
/// If a Process provides a `concurrency` value with different min and max values,
/// it will occupy a minimum of `min` cores and a maximum of `max` cores on the semaphore and
/// may be preempted (i.e. canceled and restarted) with a new concurrency value for a short
/// period after starting.
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
            sema: AsyncSemaphore::new(
                executor,
                bound,
                // TODO: Make configurable.
                Duration::from_millis(200),
            ),
        }
    }
}

impl Debug for CommandRunner {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("bounded::CommandRunner")
            .field("inner", &self.inner)
            .finish_non_exhaustive()
    }
}

#[async_trait]
impl crate::CommandRunner for CommandRunner {
    async fn run(
        &self,
        context: Context,
        workunit: &mut RunningWorkunit,
        process: Process,
    ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
        let total_concurrency = self.sema.state.lock().total_concurrency;

        let min_concurrency = match process.concurrency {
            Some(ProcessConcurrency::Exactly { count }) => count,
            Some(ProcessConcurrency::Range { min, .. }) => min.unwrap_or(1),
            Some(ProcessConcurrency::Exclusive) => total_concurrency,
            None => 1,
        };

        let max_concurrency = match process.concurrency {
            Some(ProcessConcurrency::Exactly { count }) => count,
            Some(ProcessConcurrency::Range { max, .. }) => max.unwrap_or(min_concurrency),
            Some(ProcessConcurrency::Exclusive) => total_concurrency,
            None => {
                if process.concurrency_available > 0 {
                    process.concurrency_available
                } else {
                    1
                }
            }
        };

        let min_concurrency = min(max(min_concurrency, 1), total_concurrency);
        let max_concurrency = min(max_concurrency, total_concurrency);

        log::debug!(
            "Acquiring semaphore for process {} with min_concurrency: {}, max_concurrency: {}",
            process.description,
            min_concurrency,
            max_concurrency
        );

        let semaphore_acquisition = self.sema.acquire(min_concurrency, max_concurrency);
        let permit = in_workunit!(
            "acquire_command_runner_slot",
            // TODO: The UI uses the presence of a blocked workunit below a parent as an indication that
            // the parent is blocked. If this workunit is filtered out, parents nodes which are waiting
            // for the semaphore will render, even though they are effectively idle.
            //
            // https://github.com/pantsbuild/pants/issues/14680 will likely allow for a more principled
            // solution to this problem, such as removing the mutable `blocking` flag, and then never
            // filtering blocked workunits at creation time, regardless of level.
            Level::Debug,
            |workunit| async move {
                let _blocking_token = workunit.blocking();
                semaphore_acquisition.await
            }
        )
        .await;

        loop {
            let mut process = process.clone();
            let concurrency_available = permit.concurrency();
            log::debug!(
                "Running {} under semaphore with concurrency id: {}, and concurrency: {}",
                process.description,
                permit.concurrency_slot(),
                concurrency_available,
            );

            // TODO: Both of these templating cases should be implemented at the lowest possible level:
            // they might currently be applied above a cache.
            if let Some(ref execution_slot_env_var) = process.execution_slot_variable {
                process.env.insert(
                    execution_slot_env_var.clone(),
                    format!("{}", permit.concurrency_slot()),
                );
            }

            let has_concurrency_template =
                matches!(process.concurrency, Some(ProcessConcurrency::Range { .. }))
                    || process.concurrency_available > 0;

            if has_concurrency_template {
                let concurrency = format!("{}", permit.concurrency());
                let mut matched = false;
                process.argv = std::mem::take(&mut process.argv)
                    .into_iter()
                    .map(
                        |arg| match CONCURRENCY_TEMPLATE_RE.replace_all(&arg, &concurrency) {
                            Cow::Owned(altered) => {
                                matched = true;
                                altered
                            }
                            Cow::Borrowed(_original) => arg,
                        },
                    )
                    .collect();
                if !matched {
                    if process.concurrency_available > 0 {
                        return Err(format!(
                            "Process {} set `concurrency_available={}`, but did not include \
                                 the `{}` template variable in its arguments.",
                            process.description, max_concurrency, *CONCURRENCY_TEMPLATE_RE
                        )
                        .into());
                    }
                    return Err(format!(
                        "Process {} set a `concurrency` type of range with the min {} and max {}, but did not include \
                                the `{}` template variable in its arguments.",
                        process.description,
                        min_concurrency,
                        max_concurrency,
                        *CONCURRENCY_TEMPLATE_RE
                    )
                    .into());
                }
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

    async fn shutdown(&self) -> Result<(), String> {
        self.inner.shutdown().await
    }
}

/// A wrapped Semaphore which adds concurrency metadata which supports overcommit.
#[derive(Clone)]
pub(crate) struct AsyncSemaphore {
    sema: Arc<Semaphore>,
    state: Arc<Mutex<State>>,
    preemptible_duration: Duration,
}

pub(crate) struct State {
    total_concurrency: usize,
    available_ids: VecDeque<usize>,
    tasks: Vec<Arc<Task>>,
}

impl State {
    #[cfg(test)]
    pub(crate) fn new_for_tests(total_concurrency: usize, tasks: Vec<Arc<Task>>) -> Self {
        Self {
            total_concurrency,
            available_ids: VecDeque::new(),
            tasks,
        }
    }
}

impl AsyncSemaphore {
    pub fn new(
        executor: &Executor,
        permits: usize,
        preemptible_duration: Duration,
    ) -> AsyncSemaphore {
        let mut available_ids = VecDeque::new();
        for id in 1..=permits {
            available_ids.push_back(id);
        }

        let state = Arc::new(Mutex::new(State {
            total_concurrency: permits,
            available_ids,
            tasks: Vec::new(),
        }));

        // Spawn a task which will periodically balance Tasks.
        let _balancer_task = {
            let state = Arc::downgrade(&state);
            executor.native_spawn(async move {
                loop {
                    sleep(preemptible_duration / 4).await;
                    if let Some(state) = state.upgrade() {
                        // Balance tasks.
                        let mut state = state.lock();
                        balance(Instant::now(), &mut state);
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

    #[cfg(test)]
    pub(crate) fn available_permits(&self) -> usize {
        self.sema.available_permits()
    }

    ///
    /// Runs the given Future-creating function (and the Future it returns) under the semaphore.
    ///
    /// NB: This method does not support preemption, or controlling concurrency.
    ///
    // TODO: https://github.com/rust-lang/rust/issues/46379
    #[allow(dead_code)]
    pub(crate) async fn with_acquired<F, B, O>(self, f: F) -> O
    where
        F: FnOnce(usize) -> B,
        B: Future<Output = O>,
    {
        let permit = self.acquire(1, 1).await;
        let res = f(permit.task.id).await;
        drop(permit);
        res
    }

    ///
    /// Runs the given Future-creating function (and the Future it returns) under the semaphore.
    ///
    // TODO: https://github.com/rust-lang/rust/issues/46379
    #[allow(dead_code)]
    pub(crate) async fn with_acquired_range<F, B, O>(
        self,
        min_concurrency: usize,
        max_concurrency: usize,
        f: F,
    ) -> O
    where
        F: FnOnce(usize) -> B,
        B: Future<Output = O>,
    {
        let permit = self.acquire(min_concurrency, max_concurrency).await;
        let res = f(permit.task.id).await;
        drop(permit);
        res
    }

    ///
    /// Acquire a slot on the semaphore when it becomes available. Additionally, attempt to acquire
    /// the given amount of concurrency. The amount actually acquired will be reported on the
    /// returned Permit.
    ///
    pub async fn acquire(&self, min_concurrency: usize, max_concurrency: usize) -> Permit<'_> {
        let permit = self
            .sema
            .acquire_many(min_concurrency as u32)
            .await
            .expect("semaphore closed");
        let task = {
            let mut state = self.state.lock();
            let id = state
                .available_ids
                .pop_front()
                .expect("More permits were distributed than ids exist.");

            // A Task is initially given its fair share of the available concurrency: i.e., the first
            // arriving task gets all of the slots, and the second arriving gets half, even though that
            // means that we overcommit. Balancing will adjust concurrency later, to the extent that it
            // can given preemption timeouts.
            //
            // This is because we cannot anticipate the number of inbound processes, and we never want to
            // delay a process from starting.
            let mut concurrency_actual = min(
                max_concurrency,
                state.total_concurrency / (state.tasks.len() + 1),
            );

            // We've acquired a minimum level of concurrency
            concurrency_actual = max(concurrency_actual, min_concurrency);

            let task = Arc::new(Task::new(
                id,
                min_concurrency,
                max_concurrency,
                concurrency_actual,
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

impl Drop for Permit<'_> {
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
    concurrency_min: usize,
    concurrency_max: usize,
    pub(crate) concurrency_actual: atomic::AtomicUsize,
    notify_concurrency_changed: Notify,
    preemptible_until: Instant,
}

impl Task {
    pub(crate) fn new(
        id: usize,
        concurrency_min: usize,
        concurrency_max: usize,
        concurrency_actual: usize,
        preemptible_until: Instant,
    ) -> Self {
        assert!(concurrency_min >= 1);
        assert!(concurrency_min <= concurrency_max);
        assert!(concurrency_actual >= concurrency_min);
        assert!(concurrency_actual <= concurrency_max);

        Self {
            id,
            concurrency_min,
            concurrency_max,
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
/// of any preemptible tasks, and notify them of the changes. Returns the number of Tasks that were
/// preempted.
///
/// This method only internally mutates tasks (by adjusting their concurrency levels and notifying
/// them), but takes State as mutable in order to guarantee that it gets an atomic view of the
/// tasks.
pub(crate) fn balance(now: Instant, state: &mut State) -> usize {
    let concurrency_used: usize = state.tasks.iter().map(|t| t.concurrency()).sum();
    let mut desired_change_in_commitment =
        state.total_concurrency as isize - concurrency_used as isize;
    let mut prempted = 0;

    // To reduce the number of tasks that we preempt, we preempt them in order by the amount of
    // concurrency that they desire or can relinquish.
    match desired_change_in_commitment.cmp(&0) {
        Ordering::Equal => {
            // Nothing to do! Although some tasks might not have their desired concurrency levels, it's
            // probably not worth preempting any tasks to fix that.
        }
        Ordering::Less => {
            // We're overcommitted: order by the amount that they can relinquish.
            let mut preemptible_tasks = state
                .tasks
                .iter()
                .filter_map(|t| {
                    // A task may never have less than one slot.
                    let relinquishable = t.concurrency() - t.concurrency_min;
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
                task.concurrency_actual
                    .fetch_sub(relinquish, atomic::Ordering::SeqCst);
                task.notify_concurrency_changed.notify_one();
                prempted += 1;
            }
        }
        Ordering::Greater => {
            // We're undercommitted: order by the amount that they are owed.
            let mut preemptible_tasks = state
                .tasks
                .iter()
                .filter_map(|t| {
                    let desired = t.concurrency_max - t.concurrency();
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
                task.concurrency_actual
                    .fetch_add(acquire, atomic::Ordering::SeqCst);
                task.notify_concurrency_changed.notify_one();
                prempted += 1;
            }
        }
    }

    prempted
}
