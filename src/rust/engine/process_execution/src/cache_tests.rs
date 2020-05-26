use crate::{
  CommandRunner as CommandRunnerTrait, Context, FallibleProcessResultWithPlatform, NamedCaches,
  Process, ProcessMetadata,
};
use sharded_lmdb::ShardedLmdb;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use store::Store;
use tempfile::TempDir;
use testutil::data::TestData;
use tokio::runtime::Handle;

struct RoundtripResults {
  uncached: Result<FallibleProcessResultWithPlatform, String>,
  maybe_cached: Result<FallibleProcessResultWithPlatform, String>,
}

async fn run_roundtrip(script_exit_code: i8) -> RoundtripResults {
  let runtime = task_executor::Executor::new(Handle::current());
  let work_dir = TempDir::new().unwrap();
  let named_cache_dir = TempDir::new().unwrap();
  let store_dir = TempDir::new().unwrap();
  let store = Store::local_only(runtime.clone(), store_dir.path()).unwrap();
  let local = crate::local::CommandRunner::new(
    store.clone(),
    runtime.clone(),
    work_dir.path().to_owned(),
    NamedCaches::new(named_cache_dir.path().to_owned()),
    true,
  );

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

  let request = Process::new(vec![
    testutil::path::find_bash(),
    format!("{}", script_path.display()),
  ])
  .output_files(vec![PathBuf::from("roland")].into_iter().collect());

  let local_result = local.run(request.clone().into(), Context::default()).await;

  let cache_dir = TempDir::new().unwrap();
  let max_lmdb_size = 50 * 1024 * 1024; //50 MB - I didn't pick that number but it seems reasonable.

  let process_execution_store =
    ShardedLmdb::new(cache_dir.path().to_owned(), max_lmdb_size, runtime.clone()).unwrap();

  let metadata = ProcessMetadata {
    instance_name: None,
    cache_key_gen_version: None,
    platform_properties: vec![],
  };

  let caching = crate::cache::CommandRunner::new(
    Arc::new(local),
    process_execution_store,
    store.clone(),
    metadata,
  );

  let uncached_result = caching
    .run(request.clone().into(), Context::default())
    .await;

  assert_eq!(local_result, uncached_result);

  // Removing the file means that were the command to be run again without any caching, it would
  // fail due to a FileNotFound error. So, If the second run succeeds, that implies that the
  // cache was successfully used.
  std::fs::remove_file(&script_path).unwrap();
  let maybe_cached_result = caching.run(request.into(), Context::default()).await;

  RoundtripResults {
    uncached: uncached_result,
    maybe_cached: maybe_cached_result,
  }
}

#[tokio::test]
async fn cache_success() {
  let results = run_roundtrip(0).await;
  assert_eq!(results.uncached, results.maybe_cached);
}

#[tokio::test]
async fn failures_not_cached() {
  let results = run_roundtrip(1).await;
  assert_ne!(results.uncached, results.maybe_cached);
  assert_eq!(results.uncached.unwrap().exit_code, 1);
  assert_eq!(results.maybe_cached.unwrap().exit_code, 127); // aka the return code for file not found
}
