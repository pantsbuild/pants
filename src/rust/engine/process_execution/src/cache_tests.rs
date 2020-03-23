use crate::{
  CommandRunner as CommandRunnerTrait, Context, ExecuteProcessRequest,
  ExecuteProcessRequestMetadata, FallibleExecuteProcessResult, PlatformConstraint,
};
use futures::compat::Future01CompatExt;
use hashing::EMPTY_DIGEST;
use sharded_lmdb::ShardedLmdb;
use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use store::Store;
use tempfile::TempDir;
use testutil::data::TestData;
use tokio::runtime::Handle;

struct RoundtripResults {
  uncached: Result<FallibleExecuteProcessResult, String>,
  maybe_cached: Result<FallibleExecuteProcessResult, String>,
}

async fn run_roundtrip(script_exit_code: i8) -> RoundtripResults {
  let runtime = task_executor::Executor::new(Handle::current());
  let work_dir = TempDir::new().unwrap();
  let store_dir = TempDir::new().unwrap();
  let store = Store::local_only(runtime.clone(), store_dir.path()).unwrap();
  let local = crate::local::CommandRunner::new(
    store.clone(),
    runtime.clone(),
    work_dir.path().to_owned(),
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

  let request = ExecuteProcessRequest {
    argv: vec![
      testutil::path::find_bash(),
      format!("{}", script_path.display()),
    ],
    env: BTreeMap::new(),
    working_directory: None,
    input_files: EMPTY_DIGEST,
    output_files: vec![PathBuf::from("roland")].into_iter().collect(),
    output_directories: BTreeSet::new(),
    timeout: Duration::from_millis(1000),
    description: "bash".to_string(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: PlatformConstraint::None,
    is_nailgunnable: false,
  };

  let local_result = local
    .run(request.clone().into(), Context::default())
    .compat()
    .await;

  let cache_dir = TempDir::new().unwrap();
  let caching = crate::cache::CommandRunner {
    underlying: Arc::new(local),
    file_store: store.clone(),
    process_execution_store: ShardedLmdb::new(
      cache_dir.path().to_owned(),
      50 * 1024 * 1024,
      runtime.clone(),
    )
    .unwrap(),
    metadata: ExecuteProcessRequestMetadata {
      instance_name: None,
      cache_key_gen_version: None,
      platform_properties: vec![],
    },
  };

  let uncached_result = caching.run(request.clone().into(), Context::default()).compat().await;

  assert_eq!(local_result, uncached_result);

  // Removing the file means that were the command to be run again without any caching, it would
  // fail due to a FileNotFound error. So, If the second run succeeds, that implies that the
  // cache was successfully used.
  std::fs::remove_file(&script_path).unwrap();
  let maybe_cached_result = caching
    .run(request.into(), Context::default())
    .compat()
    .await;

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
