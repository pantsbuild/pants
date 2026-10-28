// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use ::fs::DirectoryDigest;
use sandboxer::SandboxerService;
use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::Duration;
use tempfile::TempDir;

use sandboxer::Sandboxer;

// Integration tests do not compile with `cfg(test)`, so we can't import this util
// normally, and instead include it here via explicit path.
#[path = "../src/test_util.rs"]
mod test_util;

fn sandboxer_bin() -> PathBuf {
    // Cargo will automatically build the sandboxer binary for integration tests under `tests/`,
    // but not for unit tests under `src/`.
    env::current_exe()
        .unwrap()
        .parent()
        .and_then(Path::parent)
        .unwrap()
        .join("sandboxer")
}

fn wait_for(desc: &str, cond: impl Fn() -> bool) {
    let mut n = 100;
    while !cond() {
        n -= 1;
        thread::sleep(SandboxerService::POLLING_INTERVAL);
        if n == 0 {
            panic!("Waited too long for {desc}.");
        }
    }
}

#[tokio::test]
async fn test_sandboxer_process() {
    // Tests the process management wrapping. Implemented as an integration test under `tests/`
    // because it needs the sandboxer binary.
    let sandboxer_bin = sandboxer_bin();

    let dir = TempDir::new().unwrap();
    let dir_path = dir.path();
    let (store_cli_opt, dir_digest) = test_util::prep_store(dir_path).await;
    let pants_workdir = dir_path.join("workdir");
    let sandbox_path = dir_path.join("sandbox");

    let sandboxer = Sandboxer::new(sandboxer_bin, pants_workdir, store_cli_opt)
        .await
        .unwrap();

    // We haven't started the process yet.
    assert!(!sandboxer.is_alive().await.unwrap());

    // Sandboxer::materialize_directory() will spawn the sandboxer process as needed (and of
    // course here it is needed, since we haven't done so separately).
    // Note that the process is kill_on_drop, so tokio will kill it if the test doesn't. This
    // may leave a zombie process, since tokio doesn't guarantee timely reaping, but the test
    // process will exit shortly after anyway, leaving the zombie to be reaped by the system.
    let res = sandboxer
        .materialize_directory(
            &sandbox_path,
            &sandbox_path,
            &DirectoryDigest::from_persisted_digest(dir_digest.as_digest()),
            &BTreeSet::new(),
        )
        .await;
    // The process was started as a byproduct of materialize_directory().
    assert!(sandboxer.is_alive().await.unwrap());

    assert_eq!(Ok(()), res);
    let materialized_content =
        fs::read_to_string(sandbox_path.join("subdir").join("greeting.txt")).unwrap();
    assert_eq!("Hello, world!", materialized_content);

    // Assert that removing the socket file causes the sandboxer process to shut down:

    // Remove the file.
    fs::remove_file(sandboxer.socket_path()).unwrap();
    // Wait for that removal to actually manifest on the filesystem.
    let mut n = 50;
    while sandboxer.socket_path().try_exists().unwrap() {
        n -= 1;
        thread::sleep(Duration::from_millis(10));
        if n == 0 {
            panic!("Waited too long for socket path deletion to take effect.");
        }
    }
    // Give the sandboxer a chance to notice that the socket is gone, and shut down.
    thread::sleep(SandboxerService::POLLING_INTERVAL * 10);

    assert!(!sandboxer.is_alive().await.unwrap());
}

#[tokio::test]
async fn test_orphaned_sandboxer_exits() {
    let dir = TempDir::new().unwrap();
    let dir_path = dir.path();
    let (store_cli_opt, _) = test_util::prep_store(dir_path).await;
    let socket_path = dir_path.join("sandboxer.sock");

    // Spawn the sandboxer via an intermediate shell that exits shortly after, orphaning it.
    // Note that the shell may exit before the sandboxer has even started up.
    let shell = Command::new("sh")
        .arg("-c")
        .arg("\"$@\" --parent-pid $$ & echo $!; sleep 1")
        .arg("sh")
        .arg(sandboxer_bin())
        .arg("--socket-path")
        .arg(&socket_path)
        .args(store_cli_opt.to_cli_args())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let output = shell.wait_with_output().unwrap();
    let sandboxer_pid = String::from_utf8(output.stdout).unwrap().trim().to_owned();

    // The orphaned sandboxer should notice its parent exited, shut down, and clean up its socket.
    wait_for("orphaned sandboxer to exit", || {
        !Command::new("kill")
            .arg("-0")
            .arg(&sandboxer_pid)
            .stderr(Stdio::null())
            .status()
            .unwrap()
            .success()
    });
    assert!(!socket_path.exists());
}
