use std::ops::{Deref, DerefMut};
use std::sync::atomic::{AtomicBool, Ordering};

use nix::sys::signal;
use nix::unistd::getpgid;
use nix::unistd::Pid;
use tokio::process::{Child, Command};

/// A child process running in its own PGID, with a drop implementation that will kill that
/// PGID.
///
/// TODO: If this API is useful, we should consider extending it to parented Nailgun processes
/// and to all local execution in general. It could also be adjusted for sending other posix
/// signals in sequence for https://github.com/pantsbuild/pants/issues/13230.
pub struct ManagedChild {
  child: Child,
  killed: AtomicBool,
}

impl ManagedChild {
  pub fn spawn(mut command: Command) -> Result<Self, String> {
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
            format!("Could not create new pgid: {}", e),
          )
        })
      });
    };

    // Then spawn.
    let child = command
      .spawn()
      .map_err(|e| format!("Error executing interactive process: {}", e))?;
    Ok(Self {
      child,
      killed: AtomicBool::new(false),
    })
  }

  fn get_pgid(&self) -> Result<Pid, String> {
    let pid = self.id().ok_or_else(|| "Process had no PID.".to_owned())?;
    let pgid = getpgid(Some(Pid::from_raw(pid as i32)))
      .map_err(|e| format!("Could not get process group id of child process: {}", e))?;
    Ok(pgid)
  }

  /// Send an interrupt signal to the process group
  // fn send_interrupt(&mut self) -> Result<(), String> {
  //   let pgid = self.get_pgid()?;
  //   // Kill the negative PGID to kill the entire process group.
  //   signal::kill(Pid::from_raw(-pgid.as_raw()), signal::Signal::SIGINT)
  //     .map_err(|e| format!("Failed to interrupt child process group: {}", e))?;
  //   Ok(())
  // }

  /// Kill the process's unique PGID or return an error if we don't have a PID or cannot kill.
  pub fn kill_pgid(&mut self) -> Result<(), String> {
    let pgid = self.get_pgid()?;
    // Kill the negative PGID to kill the entire process group.
    signal::kill(Pid::from_raw(-pgid.as_raw()), signal::Signal::SIGKILL)
      .map_err(|e| format!("Failed to interrupt child process group: {}", e))?;
    self.killed.store(true, Ordering::SeqCst);
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
    if !self.killed.load(Ordering::SeqCst) {
      let _ = self.kill_pgid();
    }
  }
}
