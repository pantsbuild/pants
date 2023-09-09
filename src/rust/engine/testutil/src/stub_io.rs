// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::io::{Error, ErrorKind, SeekFrom};
use std::pin::Pin;
use std::task::{Context, Poll};
use tokio::io::{AsyncRead, AsyncSeek, ReadBuf};

/// A seekable reader that does 1-byte reads for a while and then starts (consistently) failing.
///
/// Failure is based on the number of individual operations, e.g. individual seek and read calls.
pub struct EventuallyFailingReader {
  operations_before_failure: usize,
  position: u64,
  end: u64,
}
impl EventuallyFailingReader {
  pub fn new(operations_before_failure: usize, size_bytes: usize) -> EventuallyFailingReader {
    EventuallyFailingReader {
      operations_before_failure,
      position: 0,
      end: size_bytes as u64,
    }
  }

  fn record_operation_and_check_error(&mut self) -> Result<(), Error> {
    if self.operations_before_failure == 0 {
      Err(Error::new(
        ErrorKind::Other,
        "EventuallyFailingReader hit its limit",
      ))
    } else {
      self.operations_before_failure -= 1;
      Ok(())
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
    let result = self_ref.record_operation_and_check_error();
    if result.is_ok() && self_ref.position < self_ref.end {
      buf.put_slice(&[0]);
      self_ref.position += 1;
    }
    Poll::Ready(result)
  }
}

impl AsyncSeek for EventuallyFailingReader {
  fn start_seek(self: Pin<&mut Self>, position: SeekFrom) -> Result<(), Error> {
    let self_ref = self.get_mut();
    let result = self_ref.record_operation_and_check_error();
    if result.is_ok() {
      let end = i64::try_from(self_ref.end).expect("end too large");
      let position_from_start: i64 = match position {
        SeekFrom::Start(offset) => offset.try_into().expect("offset too large"),
        SeekFrom::End(offset) => end + offset,
        SeekFrom::Current(offset) => {
          i64::try_from(self_ref.position).expect("position too large") + offset
        }
      };
      self_ref.position = position_from_start.clamp(0, end) as u64;
    }

    result
  }

  fn poll_complete(self: Pin<&mut Self>, _: &mut Context) -> Poll<Result<u64, Error>> {
    // the "operation" is recorded as part of the corresponding `poll_complete`
    Poll::Ready(Ok(self.get_mut().position))
  }
}
