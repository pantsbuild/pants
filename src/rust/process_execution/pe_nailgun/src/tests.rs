// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::path::PathBuf;

use store::{ImmutableInputs, Store};
use task_executor::Executor;
use tempfile::TempDir;
use testutil::owned_string_vec;
use workunit_store::WorkunitStore;

use crate::NailgunPool;
use crate::{NamedCaches, Process};

fn pool(size: usize) -> (NailgunPool, NamedCaches, ImmutableInputs, TempDir) {
    let _ = WorkunitStore::setup_for_tests();
    let base_dir = TempDir::new().unwrap();
    let named_caches_dir = base_dir.path().join("named");
    let store_dir = base_dir.path().join("store");
    let executor = Executor::new();
    let store = Store::local_only(executor.clone(), store_dir).unwrap();

    let pool = NailgunPool::new(base_dir.path().to_owned(), size, store.clone(), executor);
    (
        pool,
        NamedCaches::new_local(named_caches_dir),
        ImmutableInputs::new(store, base_dir.path()).unwrap(),
        base_dir,
    )
}

async fn run(pool: &(NailgunPool, NamedCaches, ImmutableInputs, TempDir), port: u16) -> PathBuf {
    let mut p = pool
        .0
        .acquire(
            Process::new(owned_string_vec(&[
                "/bin/bash",
                "-c",
                &format!("echo Mock port {port}.; sleep 10"),
            ])),
            &pool.1,
            &pool.2,
        )
        .await
        .unwrap();
    assert_eq!(port, p.port());
    let workdir = p.workdir_path().to_owned();
    p.release().await.unwrap();
    workdir
}

#[tokio::test]
async fn acquire() {
    let pool = pool(1);

    // Sequential calls with the same fingerprint reuse the entry.
    let workdir_one = run(&pool, 100).await;
    let workdir_two = run(&pool, 100).await;
    assert_eq!(workdir_one, workdir_two);

    // A call with a different fingerprint launches in a new workdir and succeeds.
    let workdir_three = run(&pool, 200).await;
    assert_ne!(workdir_two, workdir_three);
}
