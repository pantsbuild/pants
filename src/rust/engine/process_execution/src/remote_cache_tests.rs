use std::collections::{BTreeMap, HashSet};
use std::convert::TryInto;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use fs::{DirectoryDigest, RelativePath, EMPTY_DIRECTORY_DIGEST};
use grpc_util::tls;
use hashing::{Digest, EMPTY_DIGEST};
use maplit::hashset;
use mock::{StubActionCache, StubCAS};
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::ActionResult;
use store::Store;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory, TestTree};
use tokio::time::sleep;
use workunit_store::{RunId, RunningWorkunit, WorkunitStore};

use crate::remote::{ensure_action_stored_locally, make_execute_request};
use crate::{
  CommandRunner as CommandRunnerTrait, Context, FallibleProcessResultWithPlatform, Platform,
  Process, ProcessMetadata, ProcessResultMetadata, ProcessResultSource,
  RemoteCacheWarningsBehavior,
};

const CACHE_READ_TIMEOUT: Duration = Duration::from_secs(5);

/// A mock of the local runner used for better hermeticity of the tests.
#[derive(Clone)]
struct MockLocalCommandRunner {
  result: Result<FallibleProcessResultWithPlatform, String>,
  call_counter: Arc<AtomicUsize>,
  delay: Duration,
}

impl MockLocalCommandRunner {
  pub fn new(
    exit_code: i32,
    call_counter: Arc<AtomicUsize>,
    delay_ms: u64,
  ) -> MockLocalCommandRunner {
    MockLocalCommandRunner {
      result: Ok(FallibleProcessResultWithPlatform {
        stdout_digest: EMPTY_DIGEST,
        stderr_digest: EMPTY_DIGEST,
        exit_code,
        output_directory: EMPTY_DIRECTORY_DIGEST.clone(),
        platform: Platform::current().unwrap(),
        metadata: ProcessResultMetadata::new(None, ProcessResultSource::RanLocally, RunId(0)),
      }),
      call_counter,
      delay: Duration::from_millis(delay_ms),
    }
  }
}

#[async_trait]
impl CommandRunnerTrait for MockLocalCommandRunner {
  async fn run(
    &self,
    _context: Context,
    _workunit: &mut RunningWorkunit,
    _req: Process,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    sleep(self.delay).await;
    self.call_counter.fetch_add(1, Ordering::SeqCst);
    self.result.clone()
  }
}

// NB: We bundle these into a struct to ensure they share the same lifetime.
struct StoreSetup {
  pub store: Store,
  pub _store_temp_dir: TempDir,
  pub _cas: StubCAS,
  pub executor: task_executor::Executor,
}

impl StoreSetup {
  pub fn new() -> StoreSetup {
    let executor = task_executor::Executor::new();
    let cas = StubCAS::builder().build();
    let store_temp_dir = TempDir::new().unwrap();
    let store_dir = store_temp_dir.path().join("store_dir");
    let store = Store::local_only(executor.clone(), store_dir)
      .unwrap()
      .into_with_remote(
        &cas.address(),
        None,
        tls::Config::default(),
        BTreeMap::new(),
        10 * 1024 * 1024,
        Duration::from_secs(1),
        1,
        256,
        None,
        4 * 1024 * 1024,
      )
      .unwrap();
    StoreSetup {
      store,
      _store_temp_dir: store_temp_dir,
      _cas: cas,
      executor,
    }
  }
}

fn create_local_runner(
  exit_code: i32,
  delay_ms: u64,
) -> (Box<MockLocalCommandRunner>, Arc<AtomicUsize>) {
  let call_counter = Arc::new(AtomicUsize::new(0));
  let local_runner = Box::new(MockLocalCommandRunner::new(
    exit_code,
    call_counter.clone(),
    delay_ms,
  ));
  (local_runner, call_counter)
}

fn create_cached_runner(
  local: Box<dyn CommandRunnerTrait>,
  store_setup: &StoreSetup,
  read_delay_ms: u64,
  write_delay_ms: u64,
  eager_fetch: bool,
) -> (Box<dyn CommandRunnerTrait>, StubActionCache) {
  let action_cache = StubActionCache::new_with_delays(read_delay_ms, write_delay_ms).unwrap();
  let runner = Box::new(
    crate::remote_cache::CommandRunner::new(
      local.into(),
      ProcessMetadata::default(),
      store_setup.executor.clone(),
      store_setup.store.clone(),
      &action_cache.address(),
      None,
      BTreeMap::default(),
      Platform::current().unwrap(),
      true,
      true,
      RemoteCacheWarningsBehavior::FirstOnly,
      eager_fetch,
      256,
      CACHE_READ_TIMEOUT,
    )
    .expect("caching command runner"),
  );
  (runner, action_cache)
}

async fn create_process(store: &Store) -> (Process, Digest) {
  let process = Process::new(vec![
    "this process will not execute: see MockLocalCommandRunner".to_string(),
  ]);
  let (action, command, _exec_request) =
    make_execute_request(&process, ProcessMetadata::default()).unwrap();
  let (_command_digest, action_digest) = ensure_action_stored_locally(store, &command, &action)
    .await
    .unwrap();
  (process, action_digest)
}

fn insert_into_action_cache(
  action_cache: &StubActionCache,
  action_digest: &Digest,
  exit_code: i32,
  stdout_digest: Digest,
  stderr_digest: Digest,
) {
  let action_result = ActionResult {
    exit_code,
    stdout_digest: Some(stdout_digest.into()),
    stderr_digest: Some(stderr_digest.into()),
    ..ActionResult::default()
  };
  action_cache
    .action_map
    .lock()
    .insert(action_digest.hash, action_result);
}

#[tokio::test]
async fn cache_read_success() {
  let (_, mut workunit) = WorkunitStore::setup_for_tests();
  let store_setup = StoreSetup::new();
  let (local_runner, local_runner_call_counter) = create_local_runner(1, 1000);
  let (cache_runner, action_cache) = create_cached_runner(local_runner, &store_setup, 0, 0, false);

  let (process, action_digest) = create_process(&store_setup.store).await;
  insert_into_action_cache(&action_cache, &action_digest, 0, EMPTY_DIGEST, EMPTY_DIGEST);

  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 0);
  let remote_result = cache_runner
    .run(Context::default(), &mut workunit, process.clone().into())
    .await
    .unwrap();
  assert_eq!(remote_result.exit_code, 0);
  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 0);
}

/// If the cache has any issues during reads from the action cache, we should gracefully fallback
/// to the local runner.
#[tokio::test]
async fn cache_read_skipped_on_action_cache_errors() {
  let (workunit_store, mut workunit) = WorkunitStore::setup_for_tests();
  let store_setup = StoreSetup::new();
  let (local_runner, local_runner_call_counter) = create_local_runner(1, 500);
  let (cache_runner, action_cache) = create_cached_runner(local_runner, &store_setup, 0, 0, false);

  let (process, action_digest) = create_process(&store_setup.store).await;
  insert_into_action_cache(&action_cache, &action_digest, 0, EMPTY_DIGEST, EMPTY_DIGEST);
  action_cache.always_errors.store(true, Ordering::SeqCst);

  assert_eq!(
    workunit_store.get_metrics().get("remote_cache_read_errors"),
    None
  );
  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 0);
  let remote_result = cache_runner
    .run(Context::default(), &mut workunit, process.clone().into())
    .await
    .unwrap();
  assert_eq!(remote_result.exit_code, 1);
  assert_eq!(
    workunit_store.get_metrics().get("remote_cache_read_errors"),
    Some(&1)
  );
  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 1);
}

/// If the cache has any issues during reads from the store during eager_fetch, we should gracefully
/// fallback to the local runner.
#[tokio::test]
async fn cache_read_skipped_on_store_errors() {
  let (workunit_store, mut workunit) = WorkunitStore::setup_for_tests();
  let store_setup = StoreSetup::new();
  let (local_runner, local_runner_call_counter) = create_local_runner(1, 500);
  let (cache_runner, action_cache) = create_cached_runner(local_runner, &store_setup, 0, 0, true);

  // Claim that the process has a non-empty and not-persisted stdout digest.
  let (process, action_digest) = create_process(&store_setup.store).await;
  insert_into_action_cache(
    &action_cache,
    &action_digest,
    0,
    Digest::of_bytes("pigs flying".as_bytes()),
    EMPTY_DIGEST,
  );

  assert_eq!(
    workunit_store.get_metrics().get("remote_cache_read_errors"),
    None
  );
  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 0);
  let remote_result = cache_runner
    .run(Context::default(), &mut workunit, process.clone().into())
    .await
    .unwrap();
  assert_eq!(remote_result.exit_code, 1);
  assert_eq!(
    workunit_store.get_metrics().get("remote_cache_read_errors"),
    Some(&1)
  );
  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 1);
}

/// With eager_fetch enabled, we should skip the remote cache if any of the process result's
/// digests are invalid. This will force rerunning the process locally. Otherwise, we should use
/// the cached result with its non-existent digests.
#[tokio::test]
async fn cache_read_eager_fetch() {
  let (_, mut workunit) = WorkunitStore::setup_for_tests();

  async fn run_process(eager_fetch: bool, workunit: &mut RunningWorkunit) -> (i32, usize) {
    let store_setup = StoreSetup::new();
    let (local_runner, local_runner_call_counter) = create_local_runner(1, 1000);
    let (cache_runner, action_cache) =
      create_cached_runner(local_runner, &store_setup, 0, 0, eager_fetch);

    let (process, action_digest) = create_process(&store_setup.store).await;
    insert_into_action_cache(
      &action_cache,
      &action_digest,
      0,
      TestData::roland().digest(),
      TestData::roland().digest(),
    );

    assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 0);
    let remote_result = cache_runner
      .run(Context::default(), workunit, process.clone().into())
      .await
      .unwrap();

    let final_local_count = local_runner_call_counter.load(Ordering::SeqCst);
    (remote_result.exit_code, final_local_count)
  }

  let (lazy_exit_code, lazy_local_call_count) = run_process(false, &mut workunit).await;
  assert_eq!(lazy_exit_code, 0);
  assert_eq!(lazy_local_call_count, 0);

  let (eager_exit_code, eager_local_call_count) = run_process(true, &mut workunit).await;
  assert_eq!(eager_exit_code, 1);
  assert_eq!(eager_local_call_count, 1);
}

#[tokio::test]
async fn cache_read_speculation() {
  let (_, mut workunit) = WorkunitStore::setup_for_tests();

  async fn run_process(
    local_delay_ms: u64,
    remote_delay_ms: u64,
    cache_hit: bool,
    workunit: &mut RunningWorkunit,
  ) -> (i32, usize) {
    let store_setup = StoreSetup::new();
    let (local_runner, local_runner_call_counter) = create_local_runner(1, local_delay_ms);
    let (cache_runner, action_cache) =
      create_cached_runner(local_runner, &store_setup, remote_delay_ms, 0, false);

    let (process, action_digest) = create_process(&store_setup.store).await;
    if cache_hit {
      insert_into_action_cache(&action_cache, &action_digest, 0, EMPTY_DIGEST, EMPTY_DIGEST);
    }

    assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 0);
    let remote_result = cache_runner
      .run(Context::default(), workunit, process.clone().into())
      .await
      .unwrap();

    let final_local_count = local_runner_call_counter.load(Ordering::SeqCst);
    (remote_result.exit_code, final_local_count)
  }

  // Case 1: remote is faster than local.
  let (exit_code, local_call_count) = run_process(200, 0, true, &mut workunit).await;
  assert_eq!(exit_code, 0);
  assert_eq!(local_call_count, 0);

  // Case 2: local is faster than remote.
  let (exit_code, local_call_count) = run_process(0, 200, true, &mut workunit).await;
  assert_eq!(exit_code, 1);
  assert_eq!(local_call_count, 1);

  // Case 3: the remote lookup wins, but there is no cache entry so we fallback to local execution.
  let (exit_code, local_call_count) = run_process(200, 0, false, &mut workunit).await;
  assert_eq!(exit_code, 1);
  assert_eq!(local_call_count, 1);
}

#[tokio::test]
async fn cache_write_success() {
  let (_, mut workunit) = WorkunitStore::setup_for_tests();
  let store_setup = StoreSetup::new();
  let (local_runner, local_runner_call_counter) = create_local_runner(0, 100);
  let (cache_runner, action_cache) = create_cached_runner(local_runner, &store_setup, 0, 0, false);
  let (process, action_digest) = create_process(&store_setup.store).await;

  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 0);
  assert!(action_cache.action_map.lock().is_empty());

  let local_result = cache_runner
    .run(Context::default(), &mut workunit, process.clone().into())
    .await
    .unwrap();
  assert_eq!(local_result.exit_code, 0);
  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 1);

  // Wait for the cache write block to finish.
  sleep(Duration::from_secs(1)).await;
  assert_eq!(action_cache.action_map.lock().len(), 1);
  let action_map_mutex_guard = action_cache.action_map.lock();
  assert_eq!(
    action_map_mutex_guard
      .get(&action_digest.hash)
      .unwrap()
      .exit_code,
    0
  );
}

#[tokio::test]
async fn cache_write_not_for_failures() {
  let (_, mut workunit) = WorkunitStore::setup_for_tests();
  let store_setup = StoreSetup::new();
  let (local_runner, local_runner_call_counter) = create_local_runner(1, 100);
  let (cache_runner, action_cache) = create_cached_runner(local_runner, &store_setup, 0, 0, false);
  let (process, _action_digest) = create_process(&store_setup.store).await;

  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 0);
  assert!(action_cache.action_map.lock().is_empty());

  let local_result = cache_runner
    .run(Context::default(), &mut workunit, process.clone().into())
    .await
    .unwrap();
  assert_eq!(local_result.exit_code, 1);
  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 1);

  // Wait for the cache write block to finish.
  sleep(Duration::from_millis(100)).await;
  assert!(action_cache.action_map.lock().is_empty());
}

/// Cache writes should be async and not block the CommandRunner from returning.
#[tokio::test]
async fn cache_write_does_not_block() {
  let (_, mut workunit) = WorkunitStore::setup_for_tests();
  let store_setup = StoreSetup::new();
  let (local_runner, local_runner_call_counter) = create_local_runner(0, 100);
  let (cache_runner, action_cache) =
    create_cached_runner(local_runner, &store_setup, 0, 100, false);
  let (process, action_digest) = create_process(&store_setup.store).await;

  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 0);
  assert!(action_cache.action_map.lock().is_empty());

  let local_result = cache_runner
    .run(Context::default(), &mut workunit, process.clone().into())
    .await
    .unwrap();
  assert_eq!(local_result.exit_code, 0);
  assert_eq!(local_runner_call_counter.load(Ordering::SeqCst), 1);

  // We expect the cache write to have not finished yet, even though we already finished
  // CommandRunner::run().
  assert!(action_cache.action_map.lock().is_empty());

  sleep(Duration::from_secs(1)).await;
  assert_eq!(action_cache.action_map.lock().len(), 1);
  let action_map_mutex_guard = action_cache.action_map.lock();
  assert_eq!(
    action_map_mutex_guard
      .get(&action_digest.hash)
      .unwrap()
      .exit_code,
    0
  );
}

#[tokio::test]
async fn make_tree_from_directory() {
  let store_dir = TempDir::new().unwrap();
  let executor = task_executor::Executor::new();
  let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

  // Prepare the store to contain /pets/cats/roland.ext. We will then extract various pieces of it
  // into Tree protos.
  store
    .store_file_bytes(TestData::roland().bytes(), false)
    .await
    .expect("Error saving file bytes");
  let input_tree = TestTree::double_nested();

  let (tree, file_digests) = crate::remote_cache::CommandRunner::make_tree_for_output_directory(
    &input_tree.digest_trie(),
    RelativePath::new("pets").unwrap(),
  )
  .unwrap()
  .unwrap();

  // Note that we do not store the `pets/` prefix in the Tree, per the REAPI docs on
  // `OutputDirectory`.
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
  assert_eq!(file_node.name, "roland.ext");
  let file_digest: Digest = file_node.digest.as_ref().unwrap().try_into().unwrap();
  assert_eq!(file_digest, TestData::roland().digest());
  assert_eq!(file_digests, vec![TestData::roland().digest()]);

  // Test that extracting non-existent output directories fails gracefully.
  assert!(
    crate::remote_cache::CommandRunner::make_tree_for_output_directory(
      &input_tree.digest_trie(),
      RelativePath::new("animals").unwrap(),
    )
    .unwrap()
    .is_none()
  );
  assert!(
    crate::remote_cache::CommandRunner::make_tree_for_output_directory(
      &input_tree.digest_trie(),
      RelativePath::new("pets/xyzzy").unwrap(),
    )
    .unwrap()
    .is_none()
  );
}

#[tokio::test]
async fn extract_output_file() {
  let store_dir = TempDir::new().unwrap();
  let executor = task_executor::Executor::new();
  let store = Store::local_only(executor.clone(), store_dir.path()).unwrap();

  store
    .store_file_bytes(TestData::roland().bytes(), false)
    .await
    .expect("Error saving file bytes");
  let input_tree = TestTree::nested();

  let output_file = crate::remote_cache::CommandRunner::extract_output_file(
    &input_tree.digest_trie(),
    "cats/roland.ext",
  )
  .unwrap()
  .unwrap();

  assert_eq!(output_file.path, "cats/roland.ext");
  let file_digest: Digest = output_file.digest.unwrap().try_into().unwrap();
  assert_eq!(file_digest, TestData::roland().digest());

  // Extract non-existent files to make sure that Ok(None) is returned.
  assert!(crate::remote_cache::CommandRunner::extract_output_file(
    &input_tree.digest_trie(),
    "animals.ext",
  )
  .unwrap()
  .is_none());
  assert!(crate::remote_cache::CommandRunner::extract_output_file(
    &input_tree.digest_trie(),
    "cats/xyzzy",
  )
  .unwrap()
  .is_none());

  // Error if a path has been declared as a file but isn't.
  assert_eq!(
    crate::remote_cache::CommandRunner::extract_output_file(&input_tree.digest_trie(), "cats",),
    Err(format!(
      "Declared output file path \"cats\" in output digest {:?} contained a directory instead.",
      TestDirectory::nested().digest()
    ))
  );
}

#[tokio::test]
async fn make_action_result_basic() {
  struct MockCommandRunner;

  #[async_trait]
  impl CommandRunnerTrait for MockCommandRunner {
    async fn run(
      &self,
      _context: Context,
      _workunit: &mut RunningWorkunit,
      _req: Process,
    ) -> Result<FallibleProcessResultWithPlatform, String> {
      unimplemented!()
    }
  }

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
    executor.clone(),
    store.clone(),
    &action_cache.address(),
    None,
    BTreeMap::default(),
    Platform::current().unwrap(),
    true,
    true,
    RemoteCacheWarningsBehavior::FirstOnly,
    false,
    256,
    CACHE_READ_TIMEOUT,
  )
  .expect("caching command runner");

  let command = remexec::Command {
    arguments: vec!["this is a test".into()],
    output_files: vec!["pets/cats/roland.ext".into()],
    output_directories: vec!["pets/cats".into()],
    ..Default::default()
  };

  let process_result = FallibleProcessResultWithPlatform {
    stdout_digest: TestData::roland().digest(),
    stderr_digest: TestData::robin().digest(),
    output_directory: DirectoryDigest::from_persisted_digest(directory_digest),
    exit_code: 102,
    platform: Platform::Linux_x86_64,
    metadata: ProcessResultMetadata::new(None, ProcessResultSource::RanLocally, RunId(0)),
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

  assert_eq!(action_result.output_files.len(), 1);
  assert_eq!(
    action_result.output_files[0],
    remexec::OutputFile {
      digest: Some(TestData::roland().digest().into()),
      path: "pets/cats/roland.ext".to_owned(),
      is_executable: false,
      ..remexec::OutputFile::default()
    }
  );

  assert_eq!(action_result.output_directories.len(), 1);
  assert_eq!(
    action_result.output_directories[0],
    remexec::OutputDirectory {
      path: "pets/cats".to_owned(),
      tree_digest: Some(TestTree::roland_at_root().digest().into()),
    }
  );

  let actual_digests_set = digests.into_iter().collect::<HashSet<_>>();
  let expected_digests_set = hashset! {
    TestData::roland().digest(),  // stdout
    TestData::robin().digest(),  // stderr
    TestTree::roland_at_root().digest(),  // tree directory
  };
  assert_eq!(expected_digests_set, actual_digests_set);
}
