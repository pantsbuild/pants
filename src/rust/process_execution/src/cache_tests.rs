// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::convert::TryInto;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;

use cache::PersistentCache;
use sharded_lmdb::DEFAULT_LEASE_TIME;
use store::{ImmutableInputs, Store};
use tempfile::TempDir;
use testutil::data::TestData;
use testutil::relative_paths;
use tokio::sync::RwLock;
use workunit_store::{RunningWorkunit, WorkunitStore};

use crate::{
    CacheContentBehavior, CommandRunner as CommandRunnerTrait, Context,
    FallibleProcessResultWithPlatform, NamedCaches, Process, ProcessError,
};

struct RoundtripResults {
    uncached: Result<FallibleProcessResultWithPlatform, ProcessError>,
    maybe_cached: Result<FallibleProcessResultWithPlatform, ProcessError>,
}

fn create_local_runner() -> (Box<dyn CommandRunnerTrait>, Store, TempDir) {
    let runtime = task_executor::Executor::new();
    let base_dir = TempDir::new().unwrap();
    let named_cache_dir = base_dir.path().join("named_cache_dir");
    let store_dir = base_dir.path().join("store_dir");
    let store = Store::local_only(runtime.clone(), store_dir).unwrap();
    let runner = Box::new(crate::local::CommandRunner::new(
        store.clone(),
        None,
        runtime,
        base_dir.path().to_owned(),
        NamedCaches::new_local(named_cache_dir),
        ImmutableInputs::new(store.clone(), base_dir.path()).unwrap(),
        Arc::new(RwLock::new(())),
    ));
    (runner, store, base_dir)
}

fn create_cache() -> (PersistentCache, TempDir) {
    let runtime = task_executor::Executor::new();
    let cache_dir = TempDir::new().unwrap();
    let max_lmdb_size = 50 * 1024 * 1024; //50 MB - I didn't pick that number but it seems reasonable.

    let cache = PersistentCache::new(
        cache_dir.path(),
        max_lmdb_size,
        runtime,
        DEFAULT_LEASE_TIME,
        1,
    )
    .unwrap();

    (cache, cache_dir)
}

fn create_runner_with_cache(
    local: Arc<dyn CommandRunnerTrait>,
    cache: PersistentCache,
    store: Store,
    cache_read: bool,
) -> Box<dyn CommandRunnerTrait> {
    Box::new(crate::cache::CommandRunner::new(
        local,
        cache,
        store,
        cache_read,
        CacheContentBehavior::Fetch,
        None,
    ))
}

fn create_cached_runner(
    local: Box<dyn CommandRunnerTrait>,
    store: Store,
) -> (Box<dyn CommandRunnerTrait>, TempDir) {
    let (cache, cache_dir) = create_cache();
    let runner = create_runner_with_cache(local.into(), cache, store, true);
    (runner, cache_dir)
}

fn create_script(script_exit_code: i8) -> (Process, PathBuf, TempDir) {
    let script_dir = TempDir::new().unwrap();
    let script_path = script_dir.path().join("script");
    std::fs::File::create(&script_path)
        .and_then(|mut file| {
            writeln!(
                file,
                "echo -n {} > roland && echo Hello && echo >&2 World; exit {}",
                TestData::roland().string(),
                script_exit_code
            )
        })
        .unwrap();

    let process = Process::new(vec![
        testutil::path::find_bash(),
        format!("{}", script_path.display()),
    ])
    .output_files(relative_paths(&["roland"]).collect());

    (process, script_path, script_dir)
}

fn create_sandbox_path_script() -> (Process, PathBuf, TempDir) {
    let script_dir = TempDir::new().unwrap();
    let script_path = script_dir.path().join("script");
    std::fs::write(&script_path, "pwd > roland").unwrap();

    let process = Process::new(vec![
        testutil::path::find_bash(),
        format!("{}", script_path.display()),
    ])
    .output_files(relative_paths(&["roland"]).collect());

    (process, script_path, script_dir)
}

async fn remove_first_output_file(store: &Store, result: &FallibleProcessResultWithPlatform) {
    let output_dir_digest = result.output_directory.clone();
    store
        .ensure_directory_digest_persisted(output_dir_digest.clone())
        .await
        .unwrap();
    let output_dir = store
        .load_directory(output_dir_digest.as_digest())
        .await
        .unwrap();
    let output_child_digest = output_dir
        .files
        .first()
        .unwrap()
        .digest
        .as_ref()
        .unwrap()
        .try_into()
        .unwrap();
    let removed = store.remove_file(output_child_digest).await.unwrap();
    assert!(removed);
    assert!(
        store
            .contents_for_directory(output_dir_digest)
            .await
            .err()
            .is_some()
    )
}

async fn run_roundtrip(script_exit_code: i8, workunit: &mut RunningWorkunit) -> RoundtripResults {
    let (local, store, _local_runner_dir) = create_local_runner();
    let (process, script_path, _script_dir) = create_script(script_exit_code);

    let local_result = local
        .run(Context::default(), workunit, process.clone())
        .await;

    let (caching, _cache_dir) = create_cached_runner(local, store.clone());

    let uncached_result = caching
        .run(Context::default(), workunit, process.clone())
        .await;

    assert_eq!(local_result, uncached_result);

    // Removing the file means that were the command to be run again without any caching, it would
    // fail due to a FileNotFound error. So, If the second run succeeds, that implies that the
    // cache was successfully used.
    std::fs::remove_file(&script_path).unwrap();
    let maybe_cached_result = caching.run(Context::default(), workunit, process).await;

    RoundtripResults {
        uncached: uncached_result,
        maybe_cached: maybe_cached_result,
    }
}

#[tokio::test]
async fn cache_success() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();
    let results = run_roundtrip(0, &mut workunit).await;
    assert_eq!(results.uncached, results.maybe_cached);
}

#[tokio::test]
async fn failures_not_cached() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();
    let results = run_roundtrip(1, &mut workunit).await;
    assert_ne!(results.uncached, results.maybe_cached);
    assert_eq!(results.uncached.unwrap().exit_code, 1);
    assert_eq!(results.maybe_cached.unwrap().exit_code, 127); // aka the return code for file not found
}

#[tokio::test]
async fn recover_from_missing_store_contents() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let (local, store, _local_runner_dir) = create_local_runner();
    let (caching, _cache_dir) = create_cached_runner(local, store.clone());
    let (process, _script_path, _script_dir) = create_script(0);

    // Run once to cache the process.
    let first_result = caching
        .run(Context::default(), &mut workunit, process.clone())
        .await
        .unwrap();

    // Delete the first child of the output directory parent to confirm that we ensure that more
    // than just the root of the output is present when hitting the cache.
    remove_first_output_file(&store, &first_result).await;

    // Ensure that we don't fail if we re-run.
    let second_result = caching
        .run(Context::default(), &mut workunit, process.clone())
        .await
        .unwrap();

    // And that the entire output directory can be loaded.
    assert!(
        store
            .contents_for_directory(second_result.output_directory)
            .await
            .ok()
            .is_some()
    )
}

#[tokio::test]
async fn replace_entry_with_missing_store_contents() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let (local, store, _local_runner_dir) = create_local_runner();
    let (caching, _cache_dir) = create_cached_runner(local, store.clone());
    let (process, script_path, _script_dir) = create_sandbox_path_script();

    let first_result = caching
        .run(Context::default(), &mut workunit, process.clone())
        .await
        .unwrap();
    remove_first_output_file(&store, &first_result).await;

    let second_result = caching
        .run(Context::default(), &mut workunit, process.clone())
        .await
        .unwrap();
    assert_ne!(
        first_result.output_directory.as_digest(),
        second_result.output_directory.as_digest()
    );

    // Without the script, only a cache hit can succeed.
    std::fs::remove_file(&script_path).unwrap();
    let third_result = caching
        .run(Context::default(), &mut workunit, process)
        .await
        .unwrap();
    assert_eq!(third_result.exit_code, 0);
    assert_eq!(
        second_result.output_directory.as_digest(),
        third_result.output_directory.as_digest()
    );
}

#[tokio::test]
async fn replace_entry_from_runner_without_cache_reads() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let (local, store, _local_runner_dir) = create_local_runner();
    let local: Arc<dyn CommandRunnerTrait> = local.into();
    let (cache, _cache_dir) = create_cache();
    let reading = create_runner_with_cache(local.clone(), cache.clone(), store.clone(), true);
    // Backtracking re-runs a process through a runner that writes the cache without reading it.
    let writing = create_runner_with_cache(local, cache, store.clone(), false);
    let (process, script_path, _script_dir) = create_sandbox_path_script();

    let first_result = reading
        .run(Context::default(), &mut workunit, process.clone())
        .await
        .unwrap();
    remove_first_output_file(&store, &first_result).await;

    let second_result = writing
        .run(Context::default(), &mut workunit, process.clone())
        .await
        .unwrap();

    // Without the script, only a cache hit can succeed.
    std::fs::remove_file(&script_path).unwrap();
    let third_result = reading
        .run(Context::default(), &mut workunit, process)
        .await
        .unwrap();
    assert_eq!(third_result.exit_code, 0);
    assert_eq!(
        second_result.output_directory.as_digest(),
        third_result.output_directory.as_digest()
    );
}
