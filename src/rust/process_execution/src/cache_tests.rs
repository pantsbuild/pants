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
    CacheContentBehavior, CacheKeyExcludedEnvVars, CommandRunner as CommandRunnerTrait, Context,
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

fn create_cached_runner(
    local: Box<dyn CommandRunnerTrait>,
    store: Store,
    cache_key_excluded_env_vars: CacheKeyExcludedEnvVars,
) -> (Box<dyn CommandRunnerTrait>, TempDir) {
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

    let runner = Box::new(crate::cache::CommandRunner::new(
        local.into(),
        cache,
        store,
        true,
        CacheContentBehavior::Fetch,
        None,
        cache_key_excluded_env_vars,
    ));

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

async fn run_roundtrip(script_exit_code: i8, workunit: &mut RunningWorkunit) -> RoundtripResults {
    let (local, store, _local_runner_dir) = create_local_runner();
    let (process, script_path, _script_dir) = create_script(script_exit_code);

    let local_result = local
        .run(Context::default(), workunit, process.clone())
        .await;

    let (caching, _cache_dir) =
        create_cached_runner(local, store.clone(), CacheKeyExcludedEnvVars::default());

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

/// Runs `process` with `env_var` set to two different values, hitting the cache on the second
/// run only if the value is not part of the cache key. The script is removed in between, so a
/// miss cannot succeed: it exits 127.
async fn exit_code_of_second_run_with_changed_env_var(
    cache_key_excluded_env_vars: CacheKeyExcludedEnvVars,
    env_var: &str,
    workunit: &mut RunningWorkunit,
) -> i32 {
    let (local, store, _local_runner_dir) = create_local_runner();
    let (caching, _cache_dir) = create_cached_runner(local, store, cache_key_excluded_env_vars);
    let (process, script_path, _script_dir) = create_script(0);

    let with_value = |value: &str| {
        process
            .clone()
            .env([(env_var.to_owned(), value.to_owned())].into())
    };

    caching
        .run(Context::default(), workunit, with_value("first"))
        .await
        .unwrap();

    std::fs::remove_file(&script_path).unwrap();

    caching
        .run(Context::default(), workunit, with_value("second"))
        .await
        .unwrap()
        .exit_code
}

#[tokio::test]
async fn excluded_env_var_value_does_not_key_the_cache() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    assert_eq!(
        0,
        exit_code_of_second_run_with_changed_env_var(
            CacheKeyExcludedEnvVars::new(vec!["BUILD_ID".to_owned()]),
            "BUILD_ID",
            &mut workunit,
        )
        .await
    );

    // A name the option does not match still keys the cache, so the assertion above cannot pass
    // vacuously if a future change stops `env` reaching the cache key at all.
    assert_eq!(
        127,
        exit_code_of_second_run_with_changed_env_var(
            CacheKeyExcludedEnvVars::new(vec!["BUILD_ID".to_owned()]),
            "OTHER_VAR",
            &mut workunit,
        )
        .await
    );
}

#[tokio::test]
async fn recover_from_missing_store_contents() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let (local, store, _local_runner_dir) = create_local_runner();
    let (caching, _cache_dir) =
        create_cached_runner(local, store.clone(), CacheKeyExcludedEnvVars::default());
    let (process, _script_path, _script_dir) = create_script(0);

    // Run once to cache the process.
    let first_result = caching
        .run(Context::default(), &mut workunit, process.clone())
        .await
        .unwrap();

    // Delete the first child of the output directory parent to confirm that we ensure that more
    // than just the root of the output is present when hitting the cache.
    {
        let output_dir_digest = first_result.output_directory;
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
