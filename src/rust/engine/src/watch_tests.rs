use crate::nodes::{DigestFile, NodeKey, NodeResult};
use crate::watch::InvalidationWatcher;
use fs::{File, GitignoreStyleExcludes};
use graph::entry::{EntryResult, EntryState, Generation, RunToken};
use graph::{test_support::TestGraph, EntryId, Graph};
use hashing::EMPTY_DIGEST;
use std::fs::create_dir;
use std::path::PathBuf;
use std::sync::Arc;
use std::thread::sleep;
use std::time::Duration;
use task_executor::Executor;
use testutil::{append_to_exisiting_file, make_file};

fn init_logger() -> () {
  match env_logger::try_init() {
    Ok(()) => (),
    Err(_) => (),
  }
}

fn setup_fs() -> (tempfile::TempDir, PathBuf) {
  // setup a build_root with a file in it to watch.
  let tempdir = tempfile::TempDir::new().unwrap();
  let build_root = tempdir.path();
  let content = "contents".as_bytes().to_vec();
  create_dir(build_root.join("foo")).unwrap();
  let file_path = build_root.join("foo/watch_me.txt");
  make_file(&file_path, &content, 0o600);
  (tempdir, file_path)
}

fn setup_graph(fs_subject: PathBuf) -> (Arc<Graph<NodeKey>>, EntryId) {
  let node = NodeKey::DigestFile(DigestFile(File {
    path: fs_subject,
    is_executable: false,
  }));
  let graph = Arc::new(Graph::new());
  let entry_id = graph.add_fixture_entry(node);
  let completed_state = EntryState::Completed {
    run_token: RunToken::initial(),
    generation: Generation::initial(),
    result: EntryResult::Clean(Ok(NodeResult::Digest(EMPTY_DIGEST))),
    dep_generations: vec![],
  };
  graph.set_fixture_entry_state_for_id(entry_id, completed_state);
  // Assert the nodes initial state is completed
  assert!(graph.entry_state(entry_id) == "completed");
  (graph, entry_id)
}

fn setup_watch(
  ignorer: Arc<GitignoreStyleExcludes>,
  graph: Arc<Graph<NodeKey>>,
  build_root: PathBuf,
  file_path: PathBuf,
) -> InvalidationWatcher {
  let mut rt = tokio::runtime::Runtime::new().unwrap();
  let executor = Executor::new(rt.handle().clone());
  let watcher = InvalidationWatcher::new(Arc::downgrade(&graph), executor, build_root, ignorer, /*enabled*/ true)
    .expect("Couldn't create InvalidationWatcher");
  rt.block_on(watcher.watch(file_path)).unwrap();
  watcher
}

#[test]
fn receive_watch_event_on_file_change() {
  // set up a node in the graph to check that it gets cleared by the invalidation watcher.
  // Instantiate a watcher and watch the file in question.
  init_logger();
  let (tempdir, file_path) = setup_fs();
  let build_root = tempdir.path().to_path_buf();
  let (graph, entry_id) = setup_graph(
    file_path
      .clone()
      .strip_prefix(build_root.clone())
      .unwrap()
      .to_path_buf(),
  );

  let ignorer = GitignoreStyleExcludes::create(&[]).unwrap();
  let _watcher = setup_watch(
    ignorer,
    graph.clone(),
    build_root.clone(),
    file_path.clone(),
  );
  // Update the content of the file being watched.
  let new_content = "stnetnoc".as_bytes().to_vec();
  append_to_exisiting_file(&file_path, &new_content);
  // Wait for watcher background thread to trigger a node invalidation,
  // by checking the entry state for the node. It will be reset to EntryState::NotStarted
  // when Graph::invalidate_from_roots calls clear on the node.
  for _ in 0..10 {
    sleep(Duration::from_millis(100));
    if graph.entry_state(entry_id) == "not started" {
      return;
    }
  }
  // If we didn't find a new state fail the test.
  assert!(
    false,
    "Nodes EntryState was not invalidated, or reset to NotStarted."
  )
}

#[test]
fn ignore_file_events_matching_patterns_in_pants_ignore() {
  init_logger();
  let (tempdir, file_path) = setup_fs();
  let build_root = tempdir.path().to_path_buf();
  let (graph, entry_id) = setup_graph(
    file_path
      .clone()
      .strip_prefix(build_root.clone())
      .unwrap()
      .to_path_buf(),
  );

  let ignorer = GitignoreStyleExcludes::create(&["/foo".to_string()]).unwrap();
  let _watcher = setup_watch(
    ignorer,
    graph.clone(),
    build_root.clone(),
    file_path.clone(),
  );
  // Update the content of the file being watched.
  let new_content = "stnetnoc".as_bytes().to_vec();
  append_to_exisiting_file(&file_path, &new_content);
  // Wait for watcher background thread to trigger a node invalidation,
  // by checking the entry state for the node. It will be reset to EntryState::NotStarted
  // when Graph::invalidate_from_roots calls clear on the node.
  for _ in 0..10 {
    sleep(Duration::from_millis(100));
    // If the state changed the node was invalidated so fail.
    if graph.entry_state(entry_id) != "completed" {
      assert!(false, "Node was invalidated even though it was ignored")
    }
  }
}
