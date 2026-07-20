// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::env;
use std::process::ExitCode;

// A very simple version of the linux `flock` utility, used to serialize critical
// sections in shell scripts:
//
//   (
//     pants_lock 200  # Grab an exclusive lock on FD 200.
//     echo "Critical section running..."
//   ) 200>/var/lock/mylockfile
//
// Grabs an exclusive lock on the given file descriptor, which must be inherited from the
// parent process, blocking until the lock is acquired, then exits.
//
// We use flock(2), just as the flock utility does. flock(2) locks are owned by the open
// file description that the fd refers to, which is shared with the parent process, so the
// lock remains held after this process exits, and is released when the parent closes the
// fd (e.g., when the subshell above exits).
fn main() -> ExitCode {
    const USAGE: &str = "Usage: pants_lock <fd>";
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        eprintln!("{USAGE}");
        return ExitCode::FAILURE;
    }
    let fd: libc::c_int = match args[1].parse() {
        Ok(fd) => fd,
        Err(_) => {
            eprintln!("{USAGE}");
            return ExitCode::FAILURE;
        }
    };

    loop {
        let rc = unsafe { libc::flock(fd, libc::LOCK_EX) };
        if rc == 0 {
            return ExitCode::SUCCESS;
        }
        let err = std::io::Error::last_os_error();
        if err.kind() == std::io::ErrorKind::Interrupted {
            continue;
        }
        eprintln!("Failed to lock fd {fd}: {err}");
        return ExitCode::FAILURE;
    }
}
