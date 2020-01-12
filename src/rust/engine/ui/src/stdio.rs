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

use boxfuture::{BoxFuture, Boxable};
use futures::future::{self, Future};
use futures_locks::Mutex;
use lazy_static::lazy_static;
use std::io::Write;

///
/// A singleton token (NB: currently*) representing access to stdio within a Pants process.
///
/// Rather than using `std::io::{stderr, stdout, stdin}` directly, a codepath that needs access to
/// stdio would acquire this token. In practice, this generally means that ownership of stdio moves
/// between the following exclusive holders:
///   1) a Logger
///   2) a Console
///   3) a spawned process
///
/// Some usecases that access stdio are not natively async (in particular: see `PausableStdioWriter`
/// below). To ensure that data is flushed in a timely manner, usecases that acquire StdioAccess
/// should ensure be aware of other acquirers, and ensure that relevant equivalents of `flush` are
/// called in a timely manner after release of StdioAccess.
///
/// * NB: This token is currently a singleton, but in the presence of pantsd, this is not an accurate
/// representation: each pantsd client should have its own stdio token.
///
pub struct StdioAccess {
  prevents_construction_outside_this_module: std::marker::PhantomData<()>,
}

impl StdioAccess {
  #[cfg(test)]
  pub fn new_for_tests() -> StdioAccess {
    StdioAccess {
      prevents_construction_outside_this_module: std::marker::PhantomData,
    }
  }
}

lazy_static! {
  pub static ref STDIO_ACCESS: Mutex<StdioAccess> = Mutex::new(StdioAccess {
    prevents_construction_outside_this_module: std::marker::PhantomData,
  });
}

///
/// A `Write` implementation that supports buffering output to its underlying destination (presumed
/// to be either stdout or stderr).
///
/// No extra threads are involved, so buffered data waits until the next un-paused calls to write or
/// flush.
///
/// NB: It would be nice to be able to implement this cooperatively with `BufWriter`, but
/// unfortunately `Write` implementations generally interpret an `Ok(0)` write as an error, rather
/// than as backpressure.
///
pub struct PausableStdioWriter<'s, W: Write + Send + 'static> {
  inner: W,
  buffer: Vec<u8>,
  stdio_provider: &'s Mutex<StdioAccess>,
}

impl<'s, W: Write + Send + 'static> PausableStdioWriter<'s, W> {
  pub fn new(inner: W) -> PausableStdioWriter<'static, W> {
    PausableStdioWriter {
      inner,
      buffer: Vec::new(),
      stdio_provider: &STDIO_ACCESS,
    }
  }

  #[cfg(test)]
  pub fn new_for_tests(
    inner: W,
    stdio_provider: &'s Mutex<StdioAccess>,
  ) -> PausableStdioWriter<'s, W> {
    PausableStdioWriter {
      inner,
      buffer: Vec::new(),
      stdio_provider,
    }
  }

  fn flush_buffer(&mut self) -> std::io::Result<()> {
    let mut buffer_idx = 0;
    while buffer_idx < self.buffer.len() {
      buffer_idx += self.inner.write(&self.buffer[buffer_idx..])?;
    }
    self.buffer.clear();
    Ok(())
  }

  #[cfg(test)]
  pub fn to_inner(self) -> W {
    self.inner
  }
}

impl<'s, W: Write + Send + 'static> Write for PausableStdioWriter<'s, W> {
  fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
    if let Ok(_stdio_guard) = self.stdio_provider.try_lock() {
      if self.buffer.is_empty() {
        // If our buffer is already empty, directly write.
        self.inner.write(buf)
      } else {
        // Otherwise (for simplicity), copy the entire input to the buffer and flush it.
        self.buffer.write_all(buf).unwrap();
        self.flush_buffer()?;
        // NB: We consumed the entire input, so that is the written amount in this case.
        Ok(buf.len())
      }
    } else {
      // Output is paused: buffer instead.
      self.buffer.write(buf)
    }
  }

  fn flush(&mut self) -> std::io::Result<()> {
    if let Ok(_stdio_guard) = self.stdio_provider.try_lock() {
      self.flush_buffer()
    } else {
      Ok(())
    }
  }
}

///
/// Allows a holder of stdio to temporarily relinquish it to another user, which can avoid boundary
/// conditions during the transition.
///
/// A provider implements `pause`/`unpause`, and a consumer uses `acquire`/`release`.
///
/// TODO: The pause/unpause and acquire/release pattern is required because `self` cannot be
/// both `Clone` and "object safe", so we can't directly expose the Drop-guard pattern.
///
pub trait StdioHolder: Send + Sync {
  fn stdio_pause(&self) -> Option<futures_locks::MutexGuard<StdioAccess>>;

  fn stdio_unpause(&self, maybe_stdio_access: Option<futures_locks::MutexGuard<StdioAccess>>);

  fn stdio_acquire(&self) -> BoxFuture<BorrowedStdioAccess, ()> {
    if let Some(guard) = self.stdio_pause() {
      future::ok(BorrowedStdioAccess::FromHolder(guard)).to_boxed()
    } else {
      STDIO_ACCESS
        .lock()
        .map(BorrowedStdioAccess::FromGlobal)
        .to_boxed()
    }
  }

  fn stdio_release(&self, stdio_access: BorrowedStdioAccess) {
    match stdio_access {
      BorrowedStdioAccess::FromGlobal(guard) => {
        drop(guard);
        self.stdio_unpause(None)
      }
      BorrowedStdioAccess::FromHolder(guard) => self.stdio_unpause(Some(guard)),
    }
  }
}

#[must_use]
pub enum BorrowedStdioAccess {
  FromGlobal(futures_locks::MutexGuard<StdioAccess>),
  FromHolder(futures_locks::MutexGuard<StdioAccess>),
}

impl std::ops::Deref for BorrowedStdioAccess {
  type Target = futures_locks::MutexGuard<StdioAccess>;

  fn deref(&self) -> &Self::Target {
    match self {
      BorrowedStdioAccess::FromGlobal(ref i) => i,
      BorrowedStdioAccess::FromHolder(ref i) => i,
    }
  }
}

pub struct NoStdioHolder;

impl StdioHolder for NoStdioHolder {
  fn stdio_pause(&self) -> Option<futures_locks::MutexGuard<StdioAccess>> {
    None
  }

  fn stdio_unpause(&self, _maybe_stdio_access: Option<futures_locks::MutexGuard<StdioAccess>>) {}
}
