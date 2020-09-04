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
  clippy::unseparated_literal_suffix,
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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
use std::future::Future;
use std::sync::Arc;

use parking_lot::Mutex;
use tokio::sync::{Semaphore, SemaphorePermit};

struct Inner {
  sema: Semaphore,
  available_ids: Mutex<VecDeque<usize>>,
}

#[derive(Clone)]
pub struct AsyncSemaphore {
  inner: Arc<Inner>,
}

impl AsyncSemaphore {
  pub fn new(permits: usize) -> AsyncSemaphore {
    let mut available_ids = VecDeque::new();
    for id in 1..=permits {
      available_ids.push_back(id);
    }

    AsyncSemaphore {
      inner: Arc::new(Inner {
        sema: Semaphore::new(permits),
        available_ids: Mutex::new(available_ids),
      }),
    }
  }

  pub fn available_permits(&self) -> usize {
    self.inner.sema.available_permits()
  }

  ///
  /// Runs the given Future-creating function (and the Future it returns) under the semaphore.
  ///
  pub async fn with_acquired<F, B, O>(self, f: F) -> O
  where
    F: FnOnce(usize) -> B + Send + 'static,
    B: Future<Output = O> + Send + 'static,
  {
    let permit = self.acquire().await;
    let res = f(permit.id).await;
    drop(permit);
    res
  }

  async fn acquire(&self) -> Permit<'_> {
    let permit = self.inner.sema.acquire().await;
    let id = {
      let mut available_ids = self.inner.available_ids.lock();
      available_ids
        .pop_front()
        .expect("More permits were distributed than ids exist.")
    };
    Permit {
      inner: self.inner.clone(),
      _permit: permit,
      id,
    }
  }
}

pub struct Permit<'a> {
  inner: Arc<Inner>,
  // NB: Kept for its `Drop` impl.
  _permit: SemaphorePermit<'a>,
  id: usize,
}

impl<'a> Drop for Permit<'a> {
  fn drop(&mut self) {
    let mut available_ids = self.inner.available_ids.lock();
    available_ids.push_back(self.id);
  }
}

#[cfg(test)]
mod tests;
