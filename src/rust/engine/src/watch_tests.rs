use crate::nodes::{DigestFile, NodeKey, NodeResult};
use crate::watch::InvalidationWatcher;
use fs::File;
use graph::entry::{EntryResult, EntryState, Generation, RunToken};
use graph::{test_support::TestGraph, Graph};
use hashing::EMPTY_DIGEST;
use std::path::PathBuf;
use std::sync::Arc;
use std::thread::sleep;
use std::time::Duration;
use task_executor::Executor;
use testutil::{append_to_exisiting_file, make_file};

#[test]
fn receive_watch_event_on_file_change() {
  env_logger::init();
  // setup a build_root with a file in it to watch.
  let build_root = tempfile::TempDir::new().unwrap();
  let content = "contents".as_bytes().to_vec();
  let file_path = build_root.path().join("watch_me.txt");
  make_file(&file_path, &content, 0o600);

  // set up a node in the graph to check that it gets cleared by the invalidation watcher.
  let node = NodeKey::DigestFile(DigestFile(File {
    path: PathBuf::from("watch_me.txt"),
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
  // Instantiate a watcher and watch the file in question.
  let mut rt = tokio::runtime::Runtime::new().unwrap();
  let executor = Executor::new(rt.handle().clone());
  let watcher = InvalidationWatcher::new(
    Arc::downgrade(&graph),
    executor,
    build_root.path().to_path_buf(),
  )
  .expect("Couldn't create InvalidationWatcher");
  rt.block_on(watcher.watch(file_path.clone())).unwrap();
  // Update the content of the file being watched.
  let new_content = "stnetonc".as_bytes().to_vec();
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
