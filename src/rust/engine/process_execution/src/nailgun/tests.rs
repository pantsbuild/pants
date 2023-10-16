use std::path::PathBuf;

use store::Store;
use task_executor::Executor;
use tempfile::TempDir;
use testutil::owned_string_vec;
use workunit_store::WorkunitStore;

use crate::nailgun::NailgunPool;
use crate::{ImmutableInputs, NamedCaches, Process};

fn pool(size: usize) -> (NailgunPool, NamedCaches, ImmutableInputs) {
    let _ = WorkunitStore::setup_for_tests();
    let named_caches_dir = TempDir::new().unwrap();
    let store_dir = TempDir::new().unwrap();
    let executor = Executor::new();
    let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();
    let base_dir = std::env::temp_dir();

    let pool = NailgunPool::new(base_dir.clone(), size, store.clone(), executor);
    (
        pool,
        NamedCaches::new_local(named_caches_dir.path().to_owned()),
        ImmutableInputs::new(store, &base_dir).unwrap(),
    )
}

async fn run(pool: &(NailgunPool, NamedCaches, ImmutableInputs), port: u16) -> PathBuf {
    let mut p = pool
        .0
        .acquire(
            Process::new(owned_string_vec(&[
                "/bin/bash",
                "-c",
                &format!("echo Mock port {}.; sleep 10", port),
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
