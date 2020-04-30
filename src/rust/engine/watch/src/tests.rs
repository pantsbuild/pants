use crate::{Invalidatable, InvalidationWatcher};

use std::collections::HashSet;
use std::fs::create_dir;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::thread::sleep;
use std::time::Duration;

use crossbeam_channel;
use fs::GitignoreStyleExcludes;
use notify;
use parking_lot::Mutex;
use task_executor::Executor;
use testutil::{append_to_existing_file, make_file};

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

fn setup_watch(
  ignorer: Arc<GitignoreStyleExcludes>,
  invalidatable: Arc<TestInvalidatable>,
  build_root: PathBuf,
  file_path: PathBuf,
) -> InvalidationWatcher {
  let mut rt = tokio::runtime::Runtime::new().unwrap();
  let executor = Executor::new(rt.handle().clone());
  let watcher = InvalidationWatcher::new(
    Arc::downgrade(&invalidatable),
    executor,
    build_root,
    ignorer,
    /*enabled*/ true,
  )
  .expect("Couldn't create InvalidationWatcher");
  rt.block_on(watcher.watch(file_path)).unwrap();
  watcher
}

#[test]
fn receive_watch_event_on_file_change() {
  // Instantiate a watcher and watch the file in question.
  let (tempdir, file_path) = setup_fs();
  let build_root = tempdir.path().to_path_buf();
  let file_path_rel = file_path
    .clone()
    .strip_prefix(build_root.clone())
    .unwrap()
    .to_path_buf();

  let invalidatable = Arc::new(TestInvalidatable::default());
  let ignorer = GitignoreStyleExcludes::empty();
  let _watcher = setup_watch(
    ignorer,
    invalidatable.clone(),
    build_root.clone(),
    file_path.clone(),
  );

  // Update the content of the file being watched.
  let new_content = "stnetnoc".as_bytes().to_vec();
  append_to_existing_file(&file_path, &new_content);

  // Wait for the watcher background thread to trigger a node invalidation, which will cause the
  // new salt to be used.
  for _ in 0..10 {
    sleep(Duration::from_millis(100));
    if invalidatable.was_invalidated(&file_path_rel) {
      // Observed invalidation.
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
  let (tempdir, file_path) = setup_fs();
  let build_root = tempdir.path().to_path_buf();
  let file_path_rel = file_path
    .clone()
    .strip_prefix(build_root.clone())
    .unwrap()
    .to_path_buf();

  let invalidatable = Arc::new(TestInvalidatable::default());
  let ignorer = GitignoreStyleExcludes::create(vec!["/foo".to_string()]).unwrap();
  let _watcher = setup_watch(
    ignorer,
    invalidatable.clone(),
    build_root.clone(),
    file_path.clone(),
  );

  // Update the content of the file being watched.
  let new_content = "stnetnoc".as_bytes().to_vec();
  append_to_existing_file(&file_path, &new_content);

  // Wait for the watcher background thread to trigger a node invalidation, which would cause the
  // new salt to be used.
  for _ in 0..10 {
    sleep(Duration::from_millis(100));
    if invalidatable.was_invalidated(&file_path_rel) {
      assert!(false, "Node was invalidated even though it was ignored")
    }
  }
}

#[test]
fn test_liveness() {
  let (tempdir, _) = setup_fs();
  let build_root = tempdir.path().to_path_buf();

  let invalidatable = Arc::new(TestInvalidatable::default());
  let ignorer = GitignoreStyleExcludes::empty();
  let (liveness_sender, liveness_receiver) = crossbeam_channel::unbounded();
  let (event_sender, event_receiver) = crossbeam_channel::unbounded();
  InvalidationWatcher::start_background_thread(
    Arc::downgrade(&invalidatable),
    ignorer,
    build_root,
    liveness_sender,
    event_receiver,
  );
  event_sender
    .send(Err(notify::Error::generic(
      "This should kill the background thread",
    )))
    .unwrap();
  assert!(liveness_receiver
    .recv_timeout(Duration::from_millis(100))
    .is_ok());
}

#[derive(Default)]
struct TestInvalidatable {
  pub calls: Mutex<Vec<HashSet<PathBuf>>>,
}

impl TestInvalidatable {
  fn was_invalidated(&self, path: &Path) -> bool {
    let calls = self.calls.lock();
    calls.iter().any(|call| call.contains(path))
  }
}

impl Invalidatable for TestInvalidatable {
  fn invalidate(&self, paths: &HashSet<PathBuf>, _caller: &str) -> usize {
    let invalidated = paths.len();
    let mut calls = self.calls.lock();
    calls.push(paths.clone());
    invalidated
  }
}
