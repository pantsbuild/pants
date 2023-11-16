// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::Arc;

use parking_lot::Mutex;
use tokio::sync::watch;

///
/// An AsyncLatch is a simple condition that can be triggered once to release any threads that are
/// waiting for it.
///
/// Should be roughly equivalent to Java's CountDownLatch with a count of 1, or Python's Event
/// type (<https://docs.python.org/2/library/threading.html#event-objects>) without the ability to
/// "clear" the condition once it has been triggered.
///
#[derive(Clone)]
pub struct AsyncLatch {
    sender: Arc<Mutex<Option<watch::Sender<()>>>>,
    receiver: watch::Receiver<()>,
}

impl AsyncLatch {
    pub fn new() -> AsyncLatch {
        let (sender, receiver) = watch::channel(());
        AsyncLatch {
            sender: Arc::new(Mutex::new(Some(sender))),
            receiver,
        }
    }

    ///
    /// Mark this latch triggered, releasing all threads that are waiting for it to trigger.
    ///
    /// All calls to trigger after the first one are noops.
    ///
    pub fn trigger(&self) {
        // To trigger the latch, we drop the Sender.
        self.sender.lock().take();
    }

    ///
    /// Wait for another thread to trigger this latch.
    ///
    pub async fn triggered(&self) {
        // To see whether the latch is triggered, we clone the receiver, and then wait for our clone to
        // return an Err, indicating that the Sender has been dropped.
        let mut receiver = self.receiver.clone();
        while receiver.changed().await.is_ok() {}
    }

    ///
    /// Return true if the latch has been triggered.
    ///
    pub fn poll_triggered(&self) -> bool {
        self.sender.lock().is_none()
    }
}

#[cfg(test)]
mod tests;
