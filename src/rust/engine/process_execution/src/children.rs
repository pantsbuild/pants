// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::ops::{Deref, DerefMut};
use std::{thread, time};

use nix::sys::signal;
use nix::unistd::getpgid;
use nix::unistd::Pid;
use tokio::process::{Child, Command};

const GRACEFUL_SHUTDOWN_POLL_TIME: time::Duration = time::Duration::from_millis(50);

/// A child process running in its own PGID, with a drop implementation that will kill that
/// PGID.
///
/// Will optionally attempt a graceful shutdown first using `SIGINT`.
///
/// TODO: If this API is useful, we should consider extending it to parented Nailgun processes
/// and to all local execution in general. It could also be adjusted for sending other posix
/// signals in sequence for <https://github.com/pantsbuild/pants/issues/13230>.
pub struct ManagedChild {
  child: Child,
  graceful_shutdown_timeout: Option<time::Duration>,
  killed: bool,
}

impl ManagedChild {
  pub fn spawn(
    command: &mut Command,
    graceful_shutdown_timeout: Option<time::Duration>,
  ) -> std::io::Result<Self> {
    // Set `kill_on_drop` to encourage `tokio` to `wait` the process via its own "reaping"
    // mechanism:
    //   see https://docs.rs/tokio/1.14.0/tokio/process/struct.Command.html#method.kill_on_drop
    command.kill_on_drop(true);

    // Adjust the Command to create its own PGID as it starts, to make it safe to kill the PGID
    // later.
    unsafe {
      command.pre_exec(|| {
        nix::unistd::setsid().map(|_pgid| ()).map_err(|e| {
          std::io::Error::new(
            std::io::ErrorKind::Other,
            format!("Could not create new pgid: {e}"),
          )
        })
      });
    };

    // Then spawn.
    let child = command.spawn()?;
    Ok(Self {
      child,
      graceful_shutdown_timeout,
      killed: false,
    })
  }

  fn get_pgid(&self) -> Result<Pid, String> {
    let pid = self.id().ok_or_else(|| "Process had no PID.".to_owned())?;
    let pgid = getpgid(Some(Pid::from_raw(pid as i32)))
      .map_err(|e| format!("Could not get process group id of child process: {e}"))?;
    Ok(pgid)
  }

  /// Send a signal to the child process group.
  fn signal_pg<T: Into<Option<signal::Signal>>>(&mut self, signal: T) -> Result<(), String> {
    let pgid = self.get_pgid()?;
    // the negative PGID will signal the entire process group.
    signal::kill(Pid::from_raw(-pgid.as_raw()), signal)
      .map_err(|e| format!("Failed to interrupt child process group: {e}"))?;
    Ok(())
  }

  /// Check if the child has exited.
  ///
  /// This returns true if the child has exited with any return code, or false
  /// if the child has not yet exited. An error indicated a system error checking
  /// the result of the child process, and does not necessarily indicate that
  /// has exited or not.
  fn check_child_has_exited(&mut self) -> Result<bool, String> {
    self
      .child
      .try_wait()
      .map(|o| o.is_some())
      .map_err(|e| e.to_string())
  }

  /// Synchronously wait for the child to exit.
  ///
  /// This method will repeatedly poll the child process until it exits, an error occurrs
  /// or the timeout is reached.
  ///
  /// A return value of Ok(true) indicates that the child has terminated, Ok(false) indicates
  /// that we reached the max_wait_duration while waiting for the child to terminate.
  ///
  /// This method *will* block the current thread but will do so for a bounded amount of time.
  fn wait_for_child_exit_sync(
    &mut self,
    max_wait_duration: time::Duration,
  ) -> Result<bool, String> {
    let maybe_id = self.child.id();
    let deadline = time::Instant::now() + max_wait_duration;
    while time::Instant::now() <= deadline {
      if self.check_child_has_exited()? {
        return Ok(true);
      }
      log::debug!("Waiting for {:?} to exit...", maybe_id);
      thread::sleep(GRACEFUL_SHUTDOWN_POLL_TIME);
    }
    // If we get here we have timed-out.
    Ok(false)
  }

  /// Attempt to shutdown the process (gracefully, if was configured that way at creation).
  ///
  /// Graceful shutdown will send a SIGINT to the process and give it a chance to exit. If the
  /// process does not respond to the SIGINT within a fixed interval, a SIGKILL will be sent.
  ///
  /// NB: This method *will* block the current thread but it will do so for a bounded amount of time,
  /// as long as the operating system responds to `SIGKILL` in a bounded amount of time.
  ///
  /// TODO: Async drop might eventually allow for making this blocking more explicit.
  /// <https://rust-lang.github.io/async-fundamentals-initiative/roadmap/async_drop.html>
  pub fn attempt_shutdown_sync(&mut self) -> Result<(), String> {
    if let Some(graceful_shutdown_timeout) = self.graceful_shutdown_timeout {
      // If we fail to send SIGINT, then we will also fail to send SIGKILL, so we return eagerly
      // on error here.
      self.signal_pg(signal::Signal::SIGINT)?;
      match self.wait_for_child_exit_sync(graceful_shutdown_timeout) {
        Ok(true) => {
          // Process was gracefully shutdown: return.
          self.killed = true;
          return Ok(());
        }
        Ok(false) => {
          // We timed out waiting for the child to exit, so we need to kill it.
          log::warn!(
            "Timed out waiting for graceful shutdown of process group. Will try SIGKILL instead."
          );
        }
        Err(e) => {
          log::warn!("An error occurred while waiting for graceful shutdown of process group ({}). Will try SIGKILL instead.", e);
        }
      }
    }

    self.kill_pgid()
  }

  /// Kill the process's unique PGID or return an error if we don't have a PID or cannot kill.
  fn kill_pgid(&mut self) -> Result<(), String> {
    self.signal_pg(signal::Signal::SIGKILL)?;
    // NB: Since the SIGKILL was successfully delivered above, the only things that could cause the
    // child not to eventually exit would be if it had become a zombie (which shouldn't be possible,
    // because we are its parent process, and we are still alive).
    let _ = self.wait_for_child_exit_sync(time::Duration::from_secs(1800))?;
    self.killed = true;
    Ok(())
  }
}

impl Deref for ManagedChild {
  type Target = Child;

  fn deref(&self) -> &Child {
    &self.child
  }
}

impl DerefMut for ManagedChild {
  fn deref_mut(&mut self) -> &mut Child {
    &mut self.child
  }
}

/// Implements drop by killing the process group.
impl Drop for ManagedChild {
  fn drop(&mut self) {
    if !self.killed {
      let _ = self.attempt_shutdown_sync();
    }
  }
}
