// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
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

use std::sync::{Arc, Weak};

use tokio::sync::{oneshot, watch};

///
/// A cancellable value computed by one sender, and broadcast to multiple receivers.
///
/// Supports canceling the work associated with the pool either:
///   1. explicitly if the pool is dropped
///   2. implicitly if all receivers go away
///
/// NB: This is currently a `tokio::sync::watch` (which supports the second case), plus a
/// separate cancellation signal via `tokio::sync::oneshot` (to support the first case).
///
#[derive(Debug)]
pub struct AsyncValue<T: Clone + Send + Sync + 'static> {
  item_receiver: Weak<watch::Receiver<Option<T>>>,
  // NB: Stored only for drop.
  #[allow(dead_code)]
  abort_sender: oneshot::Sender<()>,
}

impl<T: Clone + Send + Sync + 'static> AsyncValue<T> {
  pub fn new() -> (AsyncValue<T>, AsyncValueSender<T>, AsyncValueReceiver<T>) {
    let (abort_sender, abort_receiver) = oneshot::channel();
    let (item_sender, item_receiver) = watch::channel(None);
    let item_receiver = Arc::new(item_receiver);
    (
      AsyncValue {
        item_receiver: Arc::downgrade(&item_receiver),
        abort_sender,
      },
      AsyncValueSender {
        item_sender,
        abort_receiver,
      },
      AsyncValueReceiver { item_receiver },
    )
  }

  ///
  /// Returns an AsyncValueReceiver for this value if the associated work has not already been
  /// canceled.
  ///
  pub fn receiver(&self) -> Option<AsyncValueReceiver<T>> {
    self
      .item_receiver
      .upgrade()
      .map(|item_receiver| AsyncValueReceiver { item_receiver })
  }
}

pub struct AsyncValueReceiver<T: Clone + Send + Sync + 'static> {
  item_receiver: Arc<watch::Receiver<Option<T>>>,
}

impl<T: Clone + Send + Sync + 'static> AsyncValueReceiver<T> {
  ///
  /// Returns a Future that will wait for the result of this value, or None if the work was
  /// canceled.
  ///
  pub async fn recv(&self) -> Option<T> {
    let mut item_receiver = (*self.item_receiver).clone();
    loop {
      match item_receiver.recv().await {
        Some(None) => {
          // Observing the initial value of the channel.
          continue;
        }
        Some(t) => break t,
        None => break None,
      }
    }
  }
}

pub struct AsyncValueSender<T: Clone + Send + Sync + 'static> {
  item_sender: watch::Sender<Option<T>>,
  abort_receiver: oneshot::Receiver<()>,
}

impl<T: Clone + Send + Sync + 'static> AsyncValueSender<T> {
  pub fn send(self, item: T) {
    let _ = self.item_sender.broadcast(Some(item));
  }

  pub async fn closed(&mut self) {
    tokio::select! {
      _ = &mut self.abort_receiver => {}
      _ = self.item_sender.closed() => {}
    }
  }
}

#[cfg(test)]
mod tests;
