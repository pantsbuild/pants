use std::convert::TryInto;
use std::io::Write;
use std::path::PathBuf;

use sharded_lmdb::{ShardedLmdb, DEFAULT_LEASE_TIME};
use store::Store;
use tempfile::TempDir;
use testutil::data::TestData;
use testutil::relative_paths;
use workunit_store::WorkunitStore;

use crate::{
  CommandRunner as CommandRunnerTrait, Context, FallibleProcessResultWithPlatform, NamedCaches,
  Process, ProcessMetadata,
};

struct RoundtripResults {
  uncached: Result<FallibleProcessResultWithPlatform, String>,
  maybe_cached: Result<FallibleProcessResultWithPlatform, String>,
}

fn create_local_runner() -> (Box<dyn CommandRunnerTrait>, Store, TempDir) {
  let runtime = task_executor::Executor::new();
  let base_dir = TempDir::new().unwrap();
  let named_cache_dir = base_dir.path().join("named_cache_dir");
  let store_dir = base_dir.path().join("store_dir");
  let store = Store::local_only(runtime.clone(), store_dir).unwrap();
  let runner = Box::new(crate::local::CommandRunner::new(
    store.clone(),
    runtime.clone(),
    base_dir.path().to_owned(),
    NamedCaches::new(named_cache_dir),
    true,
  ));
  (runner, store, base_dir)
}

fn create_cached_runner(
  local: Box<dyn CommandRunnerTrait>,
  store: Store,
) -> (Box<dyn CommandRunnerTrait>, TempDir) {
  let runtime = task_executor::Executor::new();
  let cache_dir = TempDir::new().unwrap();
  let max_lmdb_size = 50 * 1024 * 1024; //50 MB - I didn't pick that number but it seems reasonable.

  let process_execution_store = ShardedLmdb::new(
    cache_dir.path().to_owned(),
    max_lmdb_size,
    runtime.clone(),
    DEFAULT_LEASE_TIME,
  )
  .unwrap();

  let runner = Box::new(crate::cache::CommandRunner::new(
    local.into(),
    process_execution_store,
    store,
    ProcessMetadata::default(),
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

async fn run_roundtrip(script_exit_code: i8) -> RoundtripResults {
  let (local, store, _local_runner_dir) = create_local_runner();
  let (process, script_path, _script_dir) = create_script(script_exit_code);

  let local_result = local.run(process.clone().into(), Context::default()).await;

  let (caching, _cache_dir) = create_cached_runner(local, store.clone());

  let uncached_result = caching
    .run(process.clone().into(), Context::default())
    .await;

  assert_eq!(local_result, uncached_result);

  // Removing the file means that were the command to be run again without any caching, it would
  // fail due to a FileNotFound error. So, If the second run succeeds, that implies that the
  // cache was successfully used.
  std::fs::remove_file(&script_path).unwrap();
  let maybe_cached_result = caching.run(process.into(), Context::default()).await;

  RoundtripResults {
    uncached: uncached_result,
    maybe_cached: maybe_cached_result,
  }
}

#[tokio::test]
async fn cache_success() {
  WorkunitStore::setup_for_tests();
  let results = run_roundtrip(0).await;
  assert_eq!(results.uncached, results.maybe_cached);
}

#[tokio::test]
async fn failures_not_cached() {
  WorkunitStore::setup_for_tests();
  let results = run_roundtrip(1).await;
  assert_ne!(results.uncached, results.maybe_cached);
  assert_eq!(results.uncached.unwrap().exit_code, 1);
  assert_eq!(results.maybe_cached.unwrap().exit_code, 127); // aka the return code for file not found
}

#[tokio::test]
async fn recover_from_missing_store_contents() {
  WorkunitStore::setup_for_tests();

  let (local, store, _local_runner_dir) = create_local_runner();
  let (caching, _cache_dir) = create_cached_runner(local, store.clone());
  let (process, _script_path, _script_dir) = create_script(0);

  // Run once to cache the process.
  let first_result = caching
    .run(process.clone().into(), Context::default())
    .await
    .unwrap();

  // Delete the first child of the output directory parent to confirm that we ensure that more
  // than just the root of the output is present when hitting the cache.
  {
    let output_dir_digest = first_result.output_directory;
    let (output_dir, _) = store
      .load_directory(output_dir_digest)
      .await
      .unwrap()
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
    assert!(store
      .contents_for_directory(output_dir_digest)
      .await
      .err()
      .is_some())
  }

  // Ensure that we don't fail if we re-run.
  let second_result = caching
    .run(process.clone().into(), Context::default())
    .await
    .unwrap();

  // And that the entire output directory can be loaded.
  assert!(store
    .contents_for_directory(second_result.output_directory)
    .await
    .ok()
    .is_some())
}
