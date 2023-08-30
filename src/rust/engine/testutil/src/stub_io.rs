// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::io::{Error, ErrorKind};
use std::pin::Pin;
use std::task::{Context, Poll};
use tokio::io::{AsyncRead, ReadBuf};

/// A reader that does 1-byte reads for a while and then starts (consistently) failing
pub struct EventuallyFailingReader {
  reads_before_failure: usize,
}
impl EventuallyFailingReader {
  pub fn new(reads_before_failure: usize) -> EventuallyFailingReader {
    EventuallyFailingReader {
      reads_before_failure,
    }
  }
}

impl AsyncRead for EventuallyFailingReader {
  fn poll_read(
    self: Pin<&mut Self>,
    _: &mut Context,
    buf: &mut ReadBuf,
  ) -> Poll<Result<(), Error>> {
    let self_ref = self.get_mut();
    if self_ref.reads_before_failure == 0 {
      Poll::Ready(Err(Error::new(
        ErrorKind::Other,
        "EventuallyFailingReader hit its limit",
      )))
    } else {
      self_ref.reads_before_failure -= 1;
      buf.put_slice(&[0]);
      Poll::Ready(Ok(()))
    }
  }
}
