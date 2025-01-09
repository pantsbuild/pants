// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::io;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::RwLock;

use crate::ManagedChild;

/// Spawn a subprocess safely given that binaries may be written by this process.
pub async fn spawn_process(
    spawn_lock: Arc<RwLock<()>>,
    exclusive: bool,
    mut fork_exec: impl FnMut() -> io::Result<ManagedChild>,
) -> Result<ManagedChild, String> {
    // See the documentation of the `CapturedWorkdir::run_in_workdir` method, but `exclusive_spawn`
    // indicates the binary we're spawning was written out by the current thread, and, as such,
    // there may be open file handles against it. This will occur whenever a concurrent call of this
    // method proceeds through its fork point
    // (https://pubs.opengroup.org/onlinepubs/009695399/functions/fork.html) while the current
    // thread is in the middle of writing the binary and thus captures a clone of the open file
    // handle, but that concurrent call has not yet gotten to its exec point
    // (https://pubs.opengroup.org/onlinepubs/009695399/functions/exec.html) where the operating
    // system will close the cloned file handle (via O_CLOEXEC being set on all files opened by
    // Rust). To prevent a race like this holding this thread's binary open leading to an ETXTBSY
    // (https://pubs.opengroup.org/onlinepubs/9699919799/functions/V2_chap02.html) error, we
    // maintain RwLock that allows non-`exclusive_spawn` binaries to spawn concurrently but ensures
    // all such concurrent spawns have completed (and thus closed any cloned file handles) before
    // proceeding to spawn the `exclusive_spawn` binary this thread has written.
    //
    // See: https://github.com/golang/go/issues/22315 for an excellent description of this generic
    // unix problem.

    if exclusive {
        let _write_locked = spawn_lock.write().await;

        // Despite the mitigations taken against racing our own forks, forks can happen in our
        // process but outside of our control (in libraries). As such, we back-stop by sleeping and
        // trying again for a while if we do hit one of these fork races we do not control.
        const MAX_ETXTBSY_WAIT: Duration = Duration::from_millis(100);
        let mut retries: u32 = 0;
        let mut sleep_millis = 1;

        let start_time = std::time::Instant::now();
        loop {
            match fork_exec() {
                Err(e) => {
                    if e.raw_os_error() == Some(libc::ETXTBSY)
                        && start_time.elapsed() < MAX_ETXTBSY_WAIT
                    {
                        tokio::time::sleep(std::time::Duration::from_millis(sleep_millis)).await;
                        retries += 1;
                        sleep_millis *= 2;
                        continue;
                    } else if retries > 0 {
                        break Err(format!(
            "Error launching process after {} {} for ETXTBSY. Final error was: {:?}",
            retries,
            if retries == 1 { "retry" } else { "retries" },
            e
        ));
                    } else {
                        break Err(format!("Error launching process: {e:?}"));
                    }
                }
                Ok(child) => break Ok(child),
            }
        }
    } else {
        let _read_locked = spawn_lock.read().await;
        fork_exec().map_err(|e| format!("Error launching process: {e:?}"))
    }
}
