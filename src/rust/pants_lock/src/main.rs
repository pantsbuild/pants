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
// We use an "open file description" lock (F_OFD_SETLKW) rather than a traditional
// process-associated fcntl lock. The lock is owned by the open file description that the
// fd refers to, which is shared with the parent process, so the lock remains held after
// this process exits, and is released when the parent closes the fd (e.g., when the
// subshell above exits).
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

    let mut flock: libc::flock = unsafe { std::mem::zeroed() };
    flock.l_type = libc::F_WRLCK as libc::c_short;
    flock.l_whence = libc::SEEK_SET as libc::c_short;
    // l_start and l_len of 0 mean: lock the entire file. l_pid must be 0 for OFD locks,
    // which zeroing the struct already ensures.
    loop {
        let rc = unsafe { libc::fcntl(fd, libc::F_OFD_SETLKW, &flock) };
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
