use std::collections::{BTreeMap, HashSet};
use std::convert::TryInto;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use fs::RelativePath;
use hashing::{Digest, EMPTY_DIGEST};
use maplit::hashset;
use mock::{StubActionCache, StubCAS};
use remexec::ActionResult;
use store::{BackoffConfig, Store};
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory, TestTree};
use testutil::relative_paths;
use workunit_store::WorkunitStore;

use crate::remote::{ensure_action_stored_locally, make_execute_request};
use crate::{
  CommandRunner as CommandRunnerTrait, Context, FallibleProcessResultWithPlatform,
  MultiPlatformProcess, NamedCaches, Platform, Process, ProcessMetadata,
};

struct RoundtripResults {
  uncached: Result<FallibleProcessResultWithPlatform, String>,
  maybe_cached: Result<FallibleProcessResultWithPlatform, String>,
}

/// A mock of the local runner used for better hermeticity of the tests.
struct MockLocalCommandRunner {
  result: Result<FallibleProcessResultWithPlatform, String>,
}

impl MockLocalCommandRunner {
  pub fn new(exit_code: i32) -> MockLocalCommandRunner {
    MockLocalCommandRunner {
      result: Ok(FallibleProcessResultWithPlatform {
        stdout_digest: EMPTY_DIGEST,
        stderr_digest: EMPTY_DIGEST,
        exit_code,
        output_directory: EMPTY_DIGEST,
        execution_attempts: vec![],
        platform: Platform::current().unwrap(),
      }),
    }
  }
}

#[async_trait]
impl CommandRunnerTrait for MockLocalCommandRunner {
  async fn run(
    &self,
    _req: MultiPlatformProcess,
    _context: Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    self.result.clone()
  }

  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    Some(req.0.get(&None).unwrap().clone())
  }
}

fn create_remote_store() -> Store {
  let runtime = task_executor::Executor::new();
  let stub_cas = StubCAS::builder().build();
  let store_dir = TempDir::new().unwrap().path().join("store_dir");
  Store::with_remote(
    runtime,
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
  .unwrap()
}

fn create_local_runner() -> (Box<dyn CommandRunnerTrait>, Store) {
  let runtime = task_executor::Executor::new();
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
  (runner, store)
}

fn create_cached_runner(
  local: Box<dyn CommandRunnerTrait>,
  store: Store,
  eager_fetch: bool,
) -> (Box<dyn CommandRunnerTrait>, StubActionCache) {
  let action_cache = StubActionCache::new().unwrap();
  let runner = Box::new(
    crate::remote_cache::CommandRunner::new(
      local.into(),
      ProcessMetadata::default(),
      store,
      &action_cache.address(),
      None,
      None,
      BTreeMap::default(),
      Platform::current().unwrap(),
      true,
      true,
      eager_fetch,
    )
    .expect("caching command runner"),
  );
  (runner, action_cache)
}

fn create_process() -> Process {
  Process::new(vec![
    testutil::path::find_bash(),
    "echo -n hello world".to_string(),
  ])
}

fn create_script(script_exit_code: i8) -> (Process, PathBuf) {
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

  (process, script_path)
}

async fn run_roundtrip(script_exit_code: i8) -> RoundtripResults {
  let (local, store) = create_local_runner();
  let (process, script_path) = create_script(script_exit_code);

  let local_result = local.run(process.clone().into(), Context::default()).await;

  let (caching, _stub_action_cache) = create_cached_runner(local, store.clone(), false);

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
async fn cache_read_success() {
  WorkunitStore::setup_for_tests();
  let store = create_remote_store();
  let local_runner = Box::new(MockLocalCommandRunner::new(1));
  let (cache_runner, action_cache) = create_cached_runner(local_runner, store.clone(), false);

  let process = create_process();
  action_cache.insert(&process, &store, 0, EMPTY_DIGEST, EMPTY_DIGEST);

  let result = cache_runner
    .run(process.clone().into(), Context::default())
    .await
    .unwrap();
  assert_eq!(result.exit_code, 0);
}

/// If the cache has any issues during reads, we should gracefully fallback to the local runner.
#[tokio::test]
async fn cache_read_skipped_on_errors() {
  WorkunitStore::setup_for_tests();
  let store = create_remote_store();
  let local_runner = Box::new(MockLocalCommandRunner::new(1));
  let (cache_runner, action_cache) = create_cached_runner(local_runner, store.clone(), false);

  let process = create_process();
  action_cache.insert(&process, &store, 0, EMPTY_DIGEST, EMPTY_DIGEST);
  action_cache.always_errors.store(true, Ordering::SeqCst);

  let result = cache_runner
    .run(process.clone().into(), Context::default())
    .await
    .unwrap();
  assert_eq!(result.exit_code, 1);
}

// #[tokio::test]
// async fn cache_write_success() {
//   WorkunitStore::setup_for_tests();
//   let store = create_remote_store();
//   let local_runner = Box::new(MockLocalCommandRunner::new(1));
//   let (cache_runner, action_cache) = create_cached_runner(local, store, false);
//
//   let result = cache_runner.run().await.unwrap();
//
//   let results = run_roundtrip(0).await;
//   assert_eq!(results.uncached, results.maybe_cached);
// }
//
// #[tokio::test]
// async fn cache_write_not_for_failures() {
//   WorkunitStore::setup_for_tests();
//   let store = create_remote_store();
//   let local_runner = Box::new(MockLocalCommandRunner::new(1));
//   let (cache_runner, action_cache) = create_cached_runner(local, store, false);
//
//   let result = cache_runner.run().await.unwrap();
//
//   let results = run_roundtrip(0).await;
//   assert_eq!(results.uncached, results.maybe_cached);
// }

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
async fn skip_cache_on_error() {
  WorkunitStore::setup_for_tests();

  let (local, store) = create_local_runner();
  let (caching, stub_action_cache) = create_cached_runner(local, store.clone(), false);
  let (process, _script_path) = create_script(0);

  stub_action_cache
    .always_errors
    .store(true, Ordering::SeqCst);

  // Run once to ensure the cache is skipped on errors.
  let result = caching
    .run(process.clone().into(), Context::default())
    .await
    .unwrap();

  assert_eq!(result.exit_code, 0);
}

/// With eager_fetch enabled, we should skip the remote cache if any of the process result's
/// digests are invalid. This will force rerunning the process locally. Otherwise, we should use
/// the cached result with its non-existent digests.
#[tokio::test]
async fn eager_fetch() {
  WorkunitStore::setup_for_tests();

  async fn run_process(eager_fetch: bool) -> FallibleProcessResultWithPlatform {
    let (local, store) = create_local_runner();
    let (caching, stub_action_cache) = create_cached_runner(local, store.clone(), eager_fetch);

    // Get the `action_digest` for the Process that we're going to run. This will allow us to
    // insert a bogus value into the `stub_action_cache`.
    let (process, _script_path) = create_script(1);
    let (action, command, _exec_request) =
      make_execute_request(&process, ProcessMetadata::default()).unwrap();
    let (_command_digest, action_digest) = ensure_action_stored_locally(&store, &command, &action)
      .await
      .unwrap();

    // Insert an ActionResult with missing digests and a return code of 0 (instead of 1).
    let bogus_action_result = ActionResult {
      exit_code: 0,
      stdout_digest: Some(TestData::roland().digest().into()),
      stderr_digest: Some(TestData::roland().digest().into()),
      ..ActionResult::default()
    };
    stub_action_cache
      .action_map
      .lock()
      .insert(action_digest.0, bogus_action_result);

    // Run the process, possibly by pulling from the `ActionCache`.
    caching
      .run(process.clone().into(), Context::default())
      .await
      .unwrap()
  }

  let lazy_result = run_process(false).await;
  assert_eq!(lazy_result.exit_code, 0);
  assert_eq!(lazy_result.stdout_digest, TestData::roland().digest());
  assert_eq!(lazy_result.stderr_digest, TestData::roland().digest());

  let eager_result = run_process(true).await;
  assert_eq!(eager_result.exit_code, 1);
  assert_ne!(eager_result.stdout_digest, TestData::roland().digest());
  assert_ne!(eager_result.stderr_digest, TestData::roland().digest());
}

#[tokio::test]
async fn make_tree_from_directory() {
  let store_dir = TempDir::new().unwrap();
  let executor = task_executor::Executor::new();
  let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

  // Prepare the store to contain /pets/cats/roland. We will then extract varios pieces of it
  // into Tree protos.

  store
    .store_file_bytes(TestData::roland().bytes(), false)
    .await
    .expect("Error saving file bytes");
  store
    .record_directory(&TestDirectory::containing_roland().directory(), true)
    .await
    .expect("Error saving directory");
  store
    .record_directory(&TestDirectory::nested().directory(), true)
    .await
    .expect("Error saving directory");
  let directory_digest = store
    .record_directory(&TestDirectory::double_nested().directory(), true)
    .await
    .expect("Error saving directory");

  let tree = crate::remote_cache::CommandRunner::make_tree_for_output_directory(
    directory_digest,
    RelativePath::new("pets").unwrap(),
    &store,
  )
  .await
  .unwrap();

  let root_dir = tree.root.unwrap();
  assert_eq!(root_dir.files.len(), 0);
  assert_eq!(root_dir.directories.len(), 1);
  let dir_node = &root_dir.directories[0];
  assert_eq!(dir_node.name, "cats");
  let dir_digest: Digest = dir_node.digest.as_ref().unwrap().try_into().unwrap();
  assert_eq!(dir_digest, TestDirectory::containing_roland().digest());
  let children = tree.children;
  assert_eq!(children.len(), 1);
  let child_dir = &children[0];
  assert_eq!(child_dir.files.len(), 1);
  assert_eq!(child_dir.directories.len(), 0);
  let file_node = &child_dir.files[0];
  assert_eq!(file_node.name, "roland");
  let file_digest: Digest = file_node.digest.as_ref().unwrap().try_into().unwrap();
  assert_eq!(file_digest, TestData::roland().digest());

  // Test that extracting a non-existent output directory fails.
  crate::remote_cache::CommandRunner::make_tree_for_output_directory(
    directory_digest,
    RelativePath::new("animals").unwrap(),
    &store,
  )
  .await
  .unwrap_err();
}

#[tokio::test]
async fn extract_output_file() {
  let store_dir = TempDir::new().unwrap();
  let executor = task_executor::Executor::new();
  let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

  // Prepare the store to contain /pets/cats/roland. We will then extract varios pieces of it
  // into Tree protos.

  store
    .store_file_bytes(TestData::roland().bytes(), false)
    .await
    .expect("Error saving file bytes");
  store
    .record_directory(&TestDirectory::containing_roland().directory(), true)
    .await
    .expect("Error saving directory");
  let directory_digest = store
    .record_directory(&TestDirectory::nested().directory(), true)
    .await
    .expect("Error saving directory");

  let file_node = crate::remote_cache::CommandRunner::extract_output_file(
    directory_digest,
    RelativePath::new("cats/roland").unwrap(),
    &store,
  )
  .await
  .unwrap();

  assert_eq!(file_node.name, "roland");
  let file_digest: Digest = file_node.digest.unwrap().try_into().unwrap();
  assert_eq!(file_digest, TestData::roland().digest());
}

#[tokio::test]
async fn make_action_result_basic() {
  struct MockCommandRunner;

  #[async_trait]
  impl CommandRunnerTrait for MockCommandRunner {
    async fn run(
      &self,
      _req: MultiPlatformProcess,
      _context: Context,
    ) -> Result<FallibleProcessResultWithPlatform, String> {
      unimplemented!()
    }

    fn extract_compatible_request(&self, _req: &MultiPlatformProcess) -> Option<Process> {
      None
    }
  }

  WorkunitStore::setup_for_tests();

  let store_dir = TempDir::new().unwrap();
  let executor = task_executor::Executor::new();
  let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

  store
    .store_file_bytes(TestData::roland().bytes(), false)
    .await
    .expect("Error saving file bytes");

  store
    .store_file_bytes(TestData::robin().bytes(), false)
    .await
    .expect("Error saving file bytes");

  store
    .record_directory(&TestDirectory::containing_roland().directory(), true)
    .await
    .expect("Error saving directory");

  store
    .record_directory(&TestDirectory::nested().directory(), true)
    .await
    .expect("Error saving directory");

  let directory_digest = store
    .record_directory(&TestDirectory::double_nested().directory(), true)
    .await
    .expect("Error saving directory");

  let mock_command_runner = Arc::new(MockCommandRunner);
  let action_cache = StubActionCache::new().unwrap();
  let runner = crate::remote_cache::CommandRunner::new(
    mock_command_runner.clone(),
    ProcessMetadata::default(),
    store.clone(),
    &action_cache.address(),
    None,
    None,
    BTreeMap::default(),
    Platform::current().unwrap(),
    true,
    true,
    false,
  )
  .expect("caching command runner");

  let command = remexec::Command {
    arguments: vec!["this is a test".into()],
    output_files: vec!["pets/cats/roland".into()],
    output_directories: vec!["pets/cats".into()],
    ..Default::default()
  };

  let process_result = FallibleProcessResultWithPlatform {
    stdout_digest: TestData::roland().digest(),
    stderr_digest: TestData::robin().digest(),
    exit_code: 102,
    platform: Platform::Linux,
    output_directory: directory_digest,
    execution_attempts: Vec::new(),
  };

  let (action_result, digests) = runner
    .make_action_result(&command, &process_result, &store)
    .await
    .unwrap();

  assert_eq!(action_result.exit_code, process_result.exit_code);

  let stdout_digest: Digest = action_result.stdout_digest.unwrap().try_into().unwrap();
  assert_eq!(stdout_digest, process_result.stdout_digest);

  let stderr_digest: Digest = action_result.stderr_digest.unwrap().try_into().unwrap();
  assert_eq!(stderr_digest, process_result.stderr_digest);

  let actual_digests_set = digests.into_iter().collect::<HashSet<_>>();
  let expected_digests_set = hashset! {
    TestData::roland().digest(),
    TestData::robin().digest(),
    TestTree::roland_at_root().digest(),
  };
  assert_eq!(expected_digests_set, actual_digests_set);
}
