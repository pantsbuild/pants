use std::collections::{BTreeMap, HashSet};
use std::convert::TryInto;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use fs::RelativePath;
use hashing::Digest;
use maplit::hashset;
use mock::{StubActionCache, StubCAS};
use store::{BackoffConfig, Store};
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory, TestTree};
use testutil::relative_paths;
use workunit_store::WorkunitStore;

use crate::{
  CommandRunner as CommandRunnerTrait, Context, FallibleProcessResultWithPlatform,
  MultiPlatformProcess, NamedCaches, Platform, Process, ProcessMetadata,
};

struct RoundtripResults {
  uncached: Result<FallibleProcessResultWithPlatform, String>,
  maybe_cached: Result<FallibleProcessResultWithPlatform, String>,
}

fn create_local_runner() -> (Box<dyn CommandRunnerTrait>, Store, TempDir, StubCAS) {
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
async fn skip_cache_on_error() {
  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

  let (local, store, _local_runner_dir, _stub_cas) = create_local_runner();
  let (caching, _cache_dir, stub_action_cache) = create_cached_runner(local, store.clone());
  let (process, _script_path, _script_dir) = create_script(0);

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

  let root_dir = tree.get_root();
  assert_eq!(root_dir.get_files().len(), 0);
  assert_eq!(root_dir.get_directories().len(), 1);
  let dir_node = &root_dir.get_directories()[0];
  assert_eq!(dir_node.get_name(), "cats");
  let dir_digest: Digest = dir_node.get_digest().try_into().unwrap();
  assert_eq!(dir_digest, TestDirectory::containing_roland().digest());
  let children = tree.get_children();
  assert_eq!(children.len(), 1);
  let child_dir = &children[0];
  assert_eq!(child_dir.get_files().len(), 1);
  assert_eq!(child_dir.get_directories().len(), 0);
  let file_node = &child_dir.get_files()[0];
  assert_eq!(file_node.get_name(), "roland");
  let file_digest: Digest = file_node.get_digest().try_into().unwrap();
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

  assert_eq!(file_node.get_name(), "roland");
  let file_digest: Digest = file_node.get_digest().try_into().unwrap();
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

  let workunit_store = WorkunitStore::new(false);
  workunit_store.init_thread_state(None);

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

  let metadata = ProcessMetadata {
    instance_name: None,
    cache_key_gen_version: None,
    platform_properties: vec![],
  };

  let action_cache = StubActionCache::new().unwrap();

  let runner = crate::remote_cache::CommandRunner::new(
    mock_command_runner.clone(),
    metadata,
    store.clone(),
    &action_cache.address(),
    None,
    None,
    BTreeMap::default(),
    Platform::current().unwrap(),
    true,
    true,
  )
  .expect("caching command runner");

  let mut command = bazel_protos::remote_execution::Command::new();
  command.mut_arguments().push("this is a test".into());
  command.mut_output_files().push("pets/cats/roland".into());
  command.mut_output_directories().push("pets/cats".into());

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

  assert_eq!(action_result.get_exit_code(), process_result.exit_code);

  let stdout_digest: Digest = action_result.get_stdout_digest().try_into().unwrap();
  assert_eq!(stdout_digest, process_result.stdout_digest);

  let stderr_digest: Digest = action_result.get_stderr_digest().try_into().unwrap();
  assert_eq!(stderr_digest, process_result.stderr_digest);

  let actual_digests_set = digests.into_iter().collect::<HashSet<_>>();
  let expected_digests_set = hashset! {
    TestData::roland().digest(),
    TestData::robin().digest(),
    TestTree::roland_at_root().digest(),
  };
  assert_eq!(expected_digests_set, actual_digests_set);
}
