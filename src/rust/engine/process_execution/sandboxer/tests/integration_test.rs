// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use ::fs::DirectoryDigest;
use sandboxer::SandboxerService;
use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::path::Path;
use std::thread;
use tempfile::TempDir;

use sandboxer::Sandboxer;

// Integration tests do not compile with `cfg(test)`, so we can't import this util
// normally, and instead include it here via explicit path.
#[path = "../src/test_util.rs"]
mod test_util;

#[tokio::test]
async fn test_sandboxer_process() {
    // Tests the process management wrapping. Implemented as an integration test under `tests/`
    // because cargo will automatically build the sandboxer binary, which this test needs,
    // for integration tests, but not for unit tests under `src/`.
    let sandboxer_bin = env::current_exe()
        .unwrap()
        .parent()
        .and_then(Path::parent)
        .unwrap()
        .join("sandboxer");

    let dir = TempDir::new().unwrap();
    let dir_path = dir.path();
    let (store_cli_opt, dir_digest) = test_util::prep_store(&dir_path).await;
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

    // Assert that removing the socket file causes the sandboxer process to shut down.
    fs::remove_file(sandboxer.socket_path()).unwrap();
    thread::sleep(SandboxerService::POLLING_INTERVAL * 5);

    assert!(!sandboxer.is_alive().await.unwrap());
}
