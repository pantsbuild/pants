// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::single_match_else,
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

use std::collections::VecDeque;
use std::sync::Arc;

use futures::future::Future;
use futures::task::{self, Task};
use futures::{Async, Poll};
use log::warn;
use parking_lot::Mutex;
use rand;

struct UniqueTask {
  id: u64,
  task: Task,
}

impl PartialEq<u64> for UniqueTask {
  fn eq(&self, other: &u64) -> bool {
    *other == self.id
  }
}

struct Inner {
  waiters: VecDeque<UniqueTask>,
  available_permits: usize,
}

#[derive(Clone)]
pub struct AsyncSemaphore {
  inner: Arc<Mutex<Inner>>,
}

impl AsyncSemaphore {
  pub fn new(permits: usize) -> AsyncSemaphore {
    AsyncSemaphore {
      inner: Arc::new(Mutex::new(Inner {
        waiters: VecDeque::new(),
        available_permits: permits,
      })),
    }
  }

  pub fn num_waiters(&self) -> usize {
    let inner = self.inner.lock();
    inner.waiters.len()
  }

  ///
  /// Runs the given Future-creating function (and the Future it returns) under the semaphore.
  ///
  pub fn with_acquired<F, B, T, E>(&self, f: F) -> Box<dyn Future<Item = T, Error = E> + Send>
  where
    F: FnOnce() -> B + Send + 'static,
    B: Future<Item = T, Error = E> + Send + 'static,
  {
    let permit = PermitFuture {
      inner: Some(self.inner.clone()),
      task_id: None,
    };
    Box::new(
      permit
        .map_err(|()| panic!("Acquisition is infalliable."))
        .and_then(|permit| {
          f().map(move |t| {
            drop(permit);
            t
          })
        }),
    )
  }
}

pub struct Permit {
  inner: Arc<Mutex<Inner>>,
}

impl Drop for Permit {
  fn drop(&mut self) {
    let task = {
      let mut inner = self.inner.lock();
      inner.available_permits += 1;
      if let Some(unique_task) = inner.waiters.pop_front() {
        warn!(
          "dropped permit notifying next task, queue length is {:?}",
          inner.waiters.len()
        );
        unique_task.task
      } else {
        return;
      }
    };
    warn!("notifying task {:?}", task);
    task.notify();
  }
}

#[derive(Clone)]
pub struct PermitFuture {
  inner: Option<Arc<Mutex<Inner>>>,
  task_id: Option<u64>,
}

impl Drop for PermitFuture {
  fn drop(&mut self) {
    // if task_id is Some then this PermitFuture was added to the waiters queue.
    // if inner is still Some then this task hasn't been popped and run yet.
    if self.task_id.is_some() {
      let task_id = self.task_id.unwrap();
      let inner = self.inner.take().unwrap();
      let mut inner = inner.lock();
      if let Some(task_index) = inner.waiters.iter().position(|task| task_id == task.id) {
        warn!("found index for task to drop {:?}", task_index);
        inner.waiters.remove(task_index);
      }
    }
  }
}

impl Future for PermitFuture {
  type Item = Permit;
  type Error = ();

  fn poll(&mut self) -> Poll<Permit, ()> {
    warn!("polling task {:?}", task::current());
    let inner = self.inner.clone().unwrap();
    let acquired = {
      let mut inner = inner.lock();
      if inner.available_permits == 0 {
        if self.task_id.is_none() {
          let task_id = rand::random::<u64>();
          let this_task = UniqueTask {
            id: task_id,
            task: task::current(),
          };
          self.task_id = Some(task_id);
          inner.waiters.push_back(this_task);
          warn!(
            "added task to waiters, queue length is {:?}.",
            inner.waiters.len()
          );
        }
        false
      } else {
        inner.available_permits -= 1;
        true
      }
    };
    if acquired {
      Ok(Async::Ready(Permit { inner }))
    } else {
      Ok(Async::NotReady)
    }
  }
}

#[cfg(test)]
mod tests {

  use super::AsyncSemaphore;
  use futures::{future, Future};
  use std::sync::mpsc;
  use std::thread;
  use std::time::Duration;

  #[test]
  fn acquire_and_release() {
    let sema = AsyncSemaphore::new(1);

    sema
      .with_acquired(|| future::ok::<_, ()>(()))
      .wait()
      .unwrap();
  }

  #[test]
  fn at_most_n_acquisitions() {
    let sema = AsyncSemaphore::new(1);
    let handle1 = sema.clone();
    let handle2 = sema.clone();

    let (tx_thread1, acquired_thread1) = mpsc::channel();
    let (unblock_thread1, rx_thread1) = mpsc::channel();
    let (tx_thread2, acquired_thread2) = mpsc::channel();

    thread::spawn(move || {
      handle1
        .with_acquired(move || {
          // Indicate that we've acquired, and then wait to be signaled to exit.
          tx_thread1.send(()).unwrap();
          rx_thread1.recv().unwrap();
          future::ok::<_, ()>(())
        })
        .wait()
        .unwrap();
    });

    // Wait for thread1 to acquire, and then launch thread2.
    acquired_thread1
      .recv_timeout(Duration::from_secs(5))
      .expect("thread1 didn't acquire.");

    thread::spawn(move || {
      handle2
        .with_acquired(move || {
          tx_thread2.send(()).unwrap();
          future::ok::<_, ()>(())
        })
        .wait()
        .unwrap();
    });

    // thread2 should not signal until we unblock thread1.
    match acquired_thread2.recv_timeout(Duration::from_millis(100)) {
      Err(_) => (),
      Ok(_) => panic!("thread2 should not have acquired while thread1 was holding."),
    }

    // Unblock thread1 and confirm that thread2 acquires.
    unblock_thread1.send(()).unwrap();
    acquired_thread2
      .recv_timeout(Duration::from_secs(5))
      .expect("thread2 didn't acquire.");
  }
}
