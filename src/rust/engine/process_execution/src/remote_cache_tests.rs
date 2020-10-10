use std::collections::BTreeMap;
use std::convert::TryInto;
use std::io::Write;
use std::path::PathBuf;
use std::time::Duration;

use futures::compat::Future01CompatExt;
use mock::{StubActionCache, StubCAS};
use store::{BackoffConfig, Store};
use tempfile::TempDir;
use testutil::data::TestData;
use testutil::relative_paths;
use tokio::runtime::Handle;
use workunit_store::WorkunitStore;

use crate::{
  CommandRunner as CommandRunnerTrait, Context, FallibleProcessResultWithPlatform, NamedCaches,
  Platform, Process, ProcessMetadata,
};

struct RoundtripResults {
  uncached: Result<FallibleProcessResultWithPlatform, String>,
  maybe_cached: Result<FallibleProcessResultWithPlatform, String>,
}

fn create_local_runner() -> (Box<dyn CommandRunnerTrait>, Store, TempDir, StubCAS) {
  let runtime = task_executor::Executor::new(Handle::current());
  let base_dir = TempDir::new().unwrap();
  let named_cache_dir = base_dir.path().join("named_cache_dir");
  let stub_cas = StubCAS::builder().build();
  let store_dir = base_dir.path().join("store_dir");
  let store = Store::with_remote(
    runtime.clone(),
    store_dir,
    vec![stub_cas.address()],
    None,
    None,
    None,
    1,
    10 * 1024 * 1024,
    Duration::from_secs(1),
    BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .unwrap();
  let runner = Box::new(crate::local::CommandRunner::new(
    store.clone(),
    runtime.clone(),
    base_dir.path().to_owned(),
    NamedCaches::new(named_cache_dir),
    true,
  ));
  (runner, store, base_dir, stub_cas)
}

fn create_cached_runner(
  local: Box<dyn CommandRunnerTrait>,
  store: Store,
) -> (Box<dyn CommandRunnerTrait>, TempDir, StubActionCache) {
  let cache_dir = TempDir::new().unwrap();

  let metadata = ProcessMetadata {
    instance_name: None,
    cache_key_gen_version: None,
    platform_properties: vec![],
  };

  let action_cache = StubActionCache::new().unwrap();

  let runner = Box::new(
    crate::remote_cache::CommandRunner::new(
      local.into(),
      metadata,
      store,
      &action_cache.address(),
      None,
      None,
      BTreeMap::default(),
      Platform::current().unwrap(),
      true,
      true,
    )
    .expect("caching command runner"),
  );

  (runner, cache_dir, action_cache)
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
  let (local, store, _local_runner_dir, _stub_cas) = create_local_runner();
  let (process, script_path, _script_dir) = create_script(script_exit_code);

  let local_result = local.run(process.clone().into(), Context::default()).await;

  let (caching, _cache_dir, _stub_action_cache) = create_cached_runner(local, store.clone());

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
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

  let results = run_roundtrip(0).await;
  assert_eq!(results.uncached, results.maybe_cached);
}

#[tokio::test]
async fn failures_not_cached() {
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

  let results = run_roundtrip(1).await;
  assert_ne!(results.uncached, results.maybe_cached);
  assert_eq!(results.uncached.unwrap().exit_code, 1);
  assert_eq!(results.maybe_cached.unwrap().exit_code, 127); // aka the return code for file not found
}

#[tokio::test]
async fn recover_from_missing_store_contents() {
  env_logger::init();
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

  let (local, store, _local_runner_dir, _stub_cas) = create_local_runner();
  let (caching, _cache_dir, _stub_action_cache) = create_cached_runner(local, store.clone());
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
      .get_files()
      .first()
      .unwrap()
      .get_digest()
      .try_into()
      .unwrap();
    let removed = store.remove_file(output_child_digest).await.unwrap();
    assert!(removed);
    let result = store
      .contents_for_directory(output_dir_digest)
      .compat()
      .await;
    log::info!("{:?}", &result);
    assert!(result.err().is_some());
  }

  // Ensure that we don't fail if we re-run.
  let second_result = caching
    .run(process.clone().into(), Context::default())
    .await
    .unwrap();

  // And that the entire output directory can be loaded.
  assert!(store
    .contents_for_directory(second_result.output_directory)
    .compat()
    .await
    .ok()
    .is_some())
}
