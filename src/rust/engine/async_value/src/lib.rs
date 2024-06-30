// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::pin::pin;
use std::sync::{Arc, Weak};

use tokio::sync::{mpsc, watch};

///
/// A cancellable value computed by one sender, and broadcast to multiple receivers.
///
/// Supports canceling the work associated with the value either:
///   1. explicitly if the value is dropped
///   2. implicitly if all receivers go away
///
/// NB: This is currently a `tokio::sync::watch` (which supports the second case), plus a
/// separate channel to support the first case, and to support other types of feedback to the
/// process producing the value.
///
#[derive(Debug)]
pub struct AsyncValue<T: Clone + Send + Sync + 'static, I> {
    item_receiver: Weak<watch::Receiver<Option<T>>>,
    interrupt_sender: mpsc::UnboundedSender<I>,
}

impl<T: Clone + Send + Sync + 'static, I> AsyncValue<T, I> {
    pub fn new() -> (
        AsyncValue<T, I>,
        AsyncValueSender<T, I>,
        AsyncValueReceiver<T>,
    ) {
        let (interrupt_sender, interrupt_receiver) = mpsc::unbounded_channel();
        let (item_sender, item_receiver) = watch::channel(None);
        let item_receiver = Arc::new(item_receiver);
        (
            AsyncValue {
                item_receiver: Arc::downgrade(&item_receiver),
                interrupt_sender,
            },
            AsyncValueSender {
                item_sender,
                interrupt_receiver,
            },
            AsyncValueReceiver { item_receiver },
        )
    }

    ///
    /// Returns an AsyncValueReceiver for this value if the associated work has not already been
    /// canceled.
    ///
    pub fn receiver(&self) -> Option<AsyncValueReceiver<T>> {
        self.item_receiver
            .upgrade()
            .map(|item_receiver| AsyncValueReceiver { item_receiver })
    }

    pub fn try_interrupt(&mut self, i: I) -> Result<(), I> {
        self.interrupt_sender
            .send(i)
            .map_err(|send_error| send_error.0)
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
            if let Some(ref value) = *item_receiver.borrow() {
                return Some(value.clone());
            }

            // TODO: Remove the `allow` once https://github.com/rust-lang/rust-clippy/issues/8281
            // is fixed upstream.
            #[allow(clippy::question_mark)]
            if item_receiver.changed().await.is_err() {
                return None;
            }
        }
    }
}

pub struct AsyncValueSender<T: Clone + Send + Sync + 'static, I> {
    item_sender: watch::Sender<Option<T>>,
    interrupt_receiver: mpsc::UnboundedReceiver<I>,
}

impl<T: Clone + Send + Sync + 'static, I> AsyncValueSender<T, I> {
    pub fn send(self, item: T) {
        let _ = self.item_sender.send(Some(item));
    }

    pub async fn interrupted(&mut self) -> Option<I> {
        let mut recv = pin!(self.interrupt_receiver.recv());
        tokio::select! {
          res = &mut recv => {
            res
          }
          _ = self.item_sender.closed() => { None }
        }
    }
}

#[cfg(test)]
mod tests;
