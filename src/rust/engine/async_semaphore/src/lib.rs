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
use parking_lot::Mutex;

struct Waiter {
  id: usize,
  task: Task,
}

struct Inner {
  waiters: VecDeque<Waiter>,
  available_permits: usize,
  // Used as the source of id in Waiters's because
  // it is monotonically increasing, and only incremented under the mutex lock.
  next_waiter_id: usize,
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
        next_waiter_id: 0,
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
    Box::new(
      self
        .acquire()
        .map_err(|()| panic!("Acquisition is infalliable."))
        .and_then(|permit| {
          f().map(move |t| {
            drop(permit);
            t
          })
        }),
    )
  }

  fn acquire(&self) -> PermitFuture {
    PermitFuture {
      inner: self.inner.clone(),
      waiter_id: None,
    }
  }
}

pub struct Permit {
  inner: Arc<Mutex<Inner>>,
}

impl Drop for Permit {
  fn drop(&mut self) {
    let mut inner = self.inner.lock();
    inner.available_permits += 1;
    if let Some(waiter) = inner.waiters.front() {
      waiter.task.notify()
    }
  }
}

#[derive(Clone)]
pub struct PermitFuture {
  inner: Arc<Mutex<Inner>>,
  waiter_id: Option<usize>,
}

impl Drop for PermitFuture {
  fn drop(&mut self) {
    // if task_id is Some then this PermitFuture was added to the waiters queue.
    if let Some(waiter_id) = self.waiter_id {
      let mut inner = self.inner.lock();
      if let Some(waiter_index) = inner
        .waiters
        .iter()
        .position(|waiter| waiter_id == waiter.id)
      {
        inner.waiters.remove(waiter_index);
      }
    }
  }
}

impl Future for PermitFuture {
  type Item = Permit;
  type Error = ();

  fn poll(&mut self) -> Poll<Permit, ()> {
    let inner = self.inner.clone();
    let acquired = {
      let mut inner = inner.lock();
      if self.waiter_id.is_none() {
        let waiter_id = inner.next_waiter_id;
        let this_waiter = Waiter {
          id: waiter_id,
          task: task::current(),
        };
        self.waiter_id = Some(waiter_id);
        inner.next_waiter_id += 1;
        inner.waiters.push_back(this_waiter);
      }
      if inner.available_permits == 0 {
        false
      } else {
        let will_issue_permit = {
          if let Some(front_waiter) = inner.waiters.front() {
            // This task is the one we notified, so remove it. Otherwise keep it on the
            // waiters queue so that it doesn't get forgotten.
            if front_waiter.id == self.waiter_id.unwrap() {
              inner.waiters.pop_front();
              // Set the task_id none to indicate that the task is no longer in the
              // queue, so we don't have to waste time searching for it in the Drop
              // handler.
              self.waiter_id = None;
              true
            } else {
              // Don't issue a permit to this task if it isn't at the head of the line,
              // we added it as a waiter above.
              false
            }
          } else {
            false
          }
        };
        if will_issue_permit {
          inner.available_permits -= 1;
        }
        will_issue_permit
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
mod tests;
