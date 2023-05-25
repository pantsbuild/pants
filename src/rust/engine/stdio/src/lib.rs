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

mod term;

pub use term::{TermReadDestination, TermWriteDestination, TryCloneAsFile};

use std::cell::RefCell;
use std::fmt;
use std::fs::File;
use std::future::Future;
use std::io::{Read, Write};
use std::os::unix::io::{AsRawFd, FromRawFd, IntoRawFd, RawFd};
use std::sync::Arc;

use parking_lot::Mutex;
use tokio::task_local;

///
/// A Console wraps some "borrowed" file handles: when it is dropped, we forget about the file
/// handles rather than closing them. The file handles are optional only so that they may be
/// "taken" during Drop.
///
#[derive(Debug)]
struct Console {
  stdin_handle: Option<File>,
  stdout_handle: Option<File>,
  stderr_handle: Option<File>,
  stderr_use_color: bool,
}

impl Console {
  fn new(stdin_fd: RawFd, stdout_fd: RawFd, stderr_fd: RawFd) -> Console {
    let (stdin, stdout, stderr) = unsafe {
      (
        File::from_raw_fd(stdin_fd),
        File::from_raw_fd(stdout_fd),
        File::from_raw_fd(stderr_fd),
      )
    };
    Console {
      stdin_handle: Some(stdin),
      stdout_handle: Some(stdout),
      stderr_handle: Some(stderr),
      stderr_use_color: false,
    }
  }

  fn read_stdin(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
    self.stdin_handle.as_ref().unwrap().read(buf)
  }

  fn write_stdout(&mut self, content: &[u8]) -> Result<(), std::io::Error> {
    let mut stdout = self.stdout_handle.as_ref().unwrap();
    stdout.write_all(content)?;
    stdout.flush()
  }

  fn write_stderr(&mut self, content: &[u8]) -> Result<(), std::io::Error> {
    let mut stderr = self.stderr_handle.as_ref().unwrap();
    stderr.write_all(content)?;
    stderr.flush()
  }

  fn stdin_as_raw_fd(&self) -> RawFd {
    self.stdin_handle.as_ref().unwrap().as_raw_fd()
  }

  fn stderr_set_use_color(&mut self, use_color: bool) {
    self.stderr_use_color = use_color;
  }

  fn stdout_as_raw_fd(&self) -> RawFd {
    self.stdout_handle.as_ref().unwrap().as_raw_fd()
  }

  fn stderr_as_raw_fd(&self) -> RawFd {
    self.stderr_handle.as_ref().unwrap().as_raw_fd()
  }
}

impl Drop for Console {
  fn drop(&mut self) {
    // "Forget" about our file handles without closing them.
    self.stdin_handle.take().unwrap().into_raw_fd();
    self.stdout_handle.take().unwrap().into_raw_fd();
    self.stderr_handle.take().unwrap().into_raw_fd();
  }
}

///
/// Thread- or task-local context for where stdio should go.
///
/// We do this in a per-thread way because we find that Pants threads generally are either:
/// 1. daemon-specific
/// 2. user-console bound
/// 3. directly/exclusively accessed
///
/// We make sure that every time we spawn a thread on the Python side, we set the thread-local
/// information, and every time we submit a Future to a tokio Runtime on the rust side, we set
/// the task-local information.
///
enum InnerDestination {
  Logging,
  Console(Console),
  Exclusive {
    stderr_handler: StdioHandler,
    stderr_use_color: bool,
  },
}

impl fmt::Debug for InnerDestination {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    match self {
      Self::Logging => f.debug_struct("Logging").finish(),
      Self::Console(c) => f.debug_struct("Console").field("console", c).finish(),
      Self::Exclusive { .. } => f
        .debug_struct("Exclusive")
        .field("stderr_handler", &"<elided>")
        .finish(),
    }
  }
}

#[derive(Debug)]
pub struct Destination(Mutex<InnerDestination>);

impl Destination {
  ///
  /// Clears the Destination, setting it back to Logging.
  ///
  pub fn console_clear(&self) {
    *self.0.lock() = InnerDestination::Logging;
  }

  ///
  /// Starts Exclusive access iff the Destination is currently a Console, and returns Read/Write
  /// instances for stdin, stdout, stderr (respectively).
  ///
  /// Dropping the TermDestination will restore direct Console access.
  ///
  pub fn exclusive_start(
    self: &Arc<Self>,
    stderr_handler: StdioHandler,
  ) -> Result<
    (
      TermReadDestination,
      TermWriteDestination,
      TermWriteDestination,
    ),
    String,
  > {
    let mut destination = self.0.lock();
    let stderr_use_color = match *destination {
      InnerDestination::Console(Console {
        stderr_use_color, ..
      }) => stderr_use_color,
      _ => {
        return Err(format!(
          "Cannot start Exclusive access on Destination {destination:?}"
        ))
      }
    };
    let console = std::mem::replace(
      &mut *destination,
      InnerDestination::Exclusive {
        stderr_handler,
        stderr_use_color,
      },
    );
    match console {
      InnerDestination::Console(console) => Ok(term::TermDestination::new(console, self.clone())),
      _ => unreachable!(),
    }
  }

  ///
  /// Clears Exclusive access and restores the Console.
  ///
  fn exclusive_clear(&self, console: Console) {
    let mut destination = self.0.lock();
    if matches!(*destination, InnerDestination::Exclusive { .. }) {
      *destination = InnerDestination::Console(console);
    } else {
      // Exclusive access was torn down independently: drop the Console.
      *destination = InnerDestination::Logging;
    }
  }

  ///
  /// Set whether to use color for stderr.
  ///
  pub fn stderr_set_use_color(&self, use_color: bool) {
    let mut destination = self.0.lock();
    if let InnerDestination::Console(ref mut console) = *destination {
      console.stderr_set_use_color(use_color);
    }
  }

  ///
  /// True if color should be used with stderr.
  ///
  pub fn stderr_use_color(&self) -> bool {
    let destination = self.0.lock();
    match *destination {
      InnerDestination::Console(ref console) => console.stderr_use_color,
      InnerDestination::Exclusive {
        stderr_use_color, ..
      } => stderr_use_color,
      InnerDestination::Logging => false,
    }
  }

  ///
  /// Read from stdin if it is available on the current Destination.
  ///
  pub fn read_stdin(&self, buf: &mut [u8]) -> std::io::Result<usize> {
    let mut destination = self.0.lock();
    match *destination {
      InnerDestination::Console(ref mut console) => console.read_stdin(buf),
      InnerDestination::Exclusive { .. } => Err(std::io::Error::new(
        std::io::ErrorKind::UnexpectedEof,
        "stdin is currently Exclusive owned.",
      )),
      InnerDestination::Logging => Err(std::io::Error::new(
        std::io::ErrorKind::UnexpectedEof,
        "No stdin attached.",
      )),
    }
  }

  ///
  /// Write the given content to the current stdout destination, falling back to logging if none is
  /// available.
  ///
  pub fn write_stdout(&self, content: &[u8]) {
    let mut destination = self.0.lock();
    let error_res = match *destination {
      InnerDestination::Console(ref mut console) => {
        // Write to the underlying Console.
        let res = console.write_stdout(content);
        if res.is_ok() {
          return;
        }
        // If writing to the stdout handle fails, fall through to mutate self to drop it.
        res.map_err(|e| e.to_string())
      }
      InnerDestination::Logging | InnerDestination::Exclusive { .. } => {
        // Release the lock on the Destination before logging.
        std::mem::drop(destination);
        log::info!("stdout: {:?}", String::from_utf8_lossy(content));
        return;
      }
    };

    // Release the lock, clear the Console, log the error and retry.
    let error_str =
      format!("Failed to write stdout to {destination:?}, falling back to Logging: {error_res:?}");
    std::mem::drop(destination);
    self.console_clear();
    log::warn!("{}", error_str);
    self.write_stdout(content);
  }

  ///
  /// Write the given content to the current stdout Destination, without falling back to Logging.
  /// Returns an error if only Logging is available.
  ///
  /// NB: This method is used from the logging crate, where attempting to fall back to logging for
  /// written stdio might result in infinite recursion.
  ///
  pub fn write_stderr_raw(&self, content: &[u8]) -> Result<(), String> {
    let mut destination = self.0.lock();
    match *destination {
      InnerDestination::Console(ref mut console) => {
        console.write_stderr(content).map_err(|e| e.to_string())
      }
      InnerDestination::Exclusive {
        ref stderr_handler, ..
      } => stderr_handler(&String::from_utf8_lossy(content))
        .map_err(|()| "Exclusive handler failed.".to_owned()),
      InnerDestination::Logging => {
        Err("There is no 'real' stdio destination available.".to_owned())
      }
    }
  }

  ///
  /// Write the given content to the current stderr destination, falling back to logging if none is
  /// available.
  ///
  pub fn write_stderr(&self, content: &[u8]) {
    let mut destination = self.0.lock();
    let error_res = match *destination {
      InnerDestination::Console(ref mut console) => {
        // Write to the underlying Console.
        let res = console.write_stderr(content);
        if res.is_ok() {
          return;
        }
        // If writing to the stdout handle fails, fall through to mutate self to drop it.
        res.map_err(|e| e.to_string())
      }
      InnerDestination::Exclusive {
        ref stderr_handler, ..
      } => {
        // Write to the Exclusive handler.
        let res = stderr_handler(&String::from_utf8_lossy(content));
        if res.is_ok() {
          return;
        }
        // If writing to the stderr handler fails, fall through to clear it and try again.
        res.map_err(|()| "Failed to write stderr to Exclusive".to_owned())
      }
      InnerDestination::Logging => {
        // Release the lock on the Destination before logging.
        std::mem::drop(destination);
        log::info!("stderr: {:?}", String::from_utf8_lossy(content));
        return;
      }
    };

    // Release the lock, clear the Console, log the error and retry.
    let error_str =
      format!("Failed to write stderr to {destination:?}, falling back to Logging: {error_res:?}");
    std::mem::drop(destination);
    self.console_clear();
    log::warn!("{}", error_str);
    self.write_stderr(content);
  }

  ///
  /// If stdin is backed by a real file, returns it as a RawFd. All usage of `RawFd` is unsafe,
  /// but this method is additionally unsafe because the real file might have been closed by the
  /// time the caller interacts with it.
  ///
  pub fn stdin_as_raw_fd(&self) -> Result<RawFd, String> {
    match &*self.0.lock() {
      InnerDestination::Console(console) => Ok(console.stdin_as_raw_fd()),
      InnerDestination::Logging => {
        Err("No associated file descriptor for the Logging destination".to_owned())
      }
      InnerDestination::Exclusive { .. } => {
        Err("A UI or process has exclusive access, and must be stopped before stdio is directly accessible.".to_owned())
      }
    }
  }

  ///
  /// If stdout is backed by a real file, returns it as a RawFd. All usage of `RawFd` is unsafe,
  /// but this method is additionally unsafe because the real file might have been closed by the
  /// time the caller interacts with it.
  ///
  pub fn stdout_as_raw_fd(&self) -> Result<RawFd, String> {
    match &*self.0.lock() {
      InnerDestination::Console(console) => Ok(console.stdout_as_raw_fd()),
      InnerDestination::Logging => {
        Err("No associated file descriptor for the Logging destination".to_owned())
      }
      InnerDestination::Exclusive { .. } => {
        Err("A UI or process has exclusive access, and must be stopped before stdio is directly accessible.".to_owned())
      }
    }
  }

  ///
  /// If stdout is backed by a real file, returns it as a RawFd. All usage of `RawFd` is unsafe,
  /// but this method is additionally unsafe because the real file might have been closed by the
  /// time the caller interacts with it.
  ///
  pub fn stderr_as_raw_fd(&self) -> Result<RawFd, String> {
    match &*self.0.lock() {
      InnerDestination::Console(console) => Ok(console.stderr_as_raw_fd()),
      InnerDestination::Logging => {
        Err("No associated file descriptor for the Logging destination".to_owned())
      }
      InnerDestination::Exclusive { .. } => {
        Err("A UI or process has exclusive access, and must be stopped before stdio is directly accessible.".to_owned())
      }
    }
  }
}

thread_local! {
  ///
  /// See set_thread_destination.
  ///
  static THREAD_DESTINATION: RefCell<Arc<Destination>> = RefCell::new(Arc::new(Destination(Mutex::new(InnerDestination::Logging))))
}

// Note: The behavior of this task_local! invocation is affected by the `tokio_no_const_thread_local`
// config set in `src/rust/engine/.cargo/config`. Without that config, this item triggers the
// `clippy::declare_interior_mutable_const` lint.
task_local! {
  static TASK_DESTINATION: Arc<Destination>;
}

///
/// Creates a Console that borrows the given file handles, and which can be set for a Thread
/// using `set_thread_destination`.
///
pub fn new_console_destination(
  stdin_fd: RawFd,
  stdout_fd: RawFd,
  stderr_fd: RawFd,
) -> Arc<Destination> {
  Arc::new(Destination(Mutex::new(InnerDestination::Console(
    Console::new(stdin_fd, stdout_fd, stderr_fd),
  ))))
}

///
/// Set the stdio Destination for the current Thread (which will propagate to spawned Tasks).
///
/// Setting the Destination on the current Thread will cause it to be propagated to any Tasks
/// spawned by this Thread using the `scope_task_destination` helper (via task_executor::Executor).
///
/// Note that `set_thread_destination` "replaces" the Destination for a Thread without affecting
/// work that was previously spawned by it, whereas `get_destination().console_clear()` would clear
/// the console for all previously spawned Thread/Tasks.
///
/// See InnerDestination for more info.
///
pub fn set_thread_destination(destination: Arc<Destination>) {
  THREAD_DESTINATION.with(|thread_destination| {
    thread_destination.replace(destination);
  })
}

///
/// Propagate the current stdio Destination to a Future representing a newly spawned Task. Usage of
/// this method should mostly be contained to task_executor::Executor.
///
/// See InnerDestination for more info.
///
pub async fn scope_task_destination<F>(destination: Arc<Destination>, f: F) -> F::Output
where
  F: Future,
{
  TASK_DESTINATION.scope(destination, f).await
}

///
/// Get the current stdio Destination.
///
pub fn get_destination() -> Arc<Destination> {
  if let Ok(destination) = TASK_DESTINATION.try_with(|destination| destination.clone()) {
    destination
  } else {
    THREAD_DESTINATION.with(|destination| destination.borrow().clone())
  }
}

pub type StdioHandler = Box<dyn Fn(&str) -> Result<(), ()> + Send>;
