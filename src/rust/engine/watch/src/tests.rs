// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::{Invalidatable, InvalidateCaller, InvalidationWatcher};

use std::collections::HashSet;
use std::fs::create_dir;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::thread::sleep;
use std::time::Duration;

use crossbeam_channel::{self, RecvTimeoutError};
use fs::GitignoreStyleExcludes;

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

/// Create (but don't start) an InvalidationWatcher.
async fn setup_watch(
  ignorer: Arc<GitignoreStyleExcludes>,
  build_root: PathBuf,
  file_path: PathBuf,
) -> Arc<InvalidationWatcher> {
  let executor = Executor::new();
  let watcher = InvalidationWatcher::new(executor, build_root, ignorer)
    .expect("Couldn't create InvalidationWatcher");
  watcher.watch(file_path).await.unwrap();
  watcher
}

#[tokio::test]
async fn receive_watch_event_on_file_change() {
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
  let watcher = setup_watch(ignorer, build_root.clone(), file_path.clone()).await;
  watcher.start(&invalidatable).unwrap();

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
  assert!(false, "Did not observe invalidation.")
}

#[tokio::test]
async fn ignore_file_events_matching_patterns_in_pants_ignore() {
  let (tempdir, file_path) = setup_fs();
  let build_root = tempdir.path().to_path_buf();
  let file_path_rel = file_path
    .clone()
    .strip_prefix(build_root.clone())
    .unwrap()
    .to_path_buf();

  let invalidatable = Arc::new(TestInvalidatable::default());
  let ignorer = GitignoreStyleExcludes::create(vec!["/foo".to_string()]).unwrap();
  let watcher = setup_watch(ignorer, build_root, file_path.clone()).await;
  watcher.start(&invalidatable).unwrap();

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

#[tokio::test]
async fn liveness_watch_error() {
  let (tempdir, file_path) = setup_fs();
  let build_root = tempdir.path().to_path_buf();

  let invalidatable = Arc::new(TestInvalidatable::default());
  let ignorer = GitignoreStyleExcludes::empty();
  // NB: We create this watcher, but we don't call start: instead we create the background thread
  // directly.
  let _watcher = setup_watch(ignorer.clone(), build_root.clone(), file_path.clone()).await;
  let (liveness_sender, liveness_receiver) = crossbeam_channel::unbounded();
  let (event_sender, event_receiver) = crossbeam_channel::unbounded();
  let join_handle = InvalidationWatcher::start_background_thread(
    Arc::downgrade(&invalidatable),
    ignorer,
    build_root,
    liveness_sender,
    event_receiver,
  )
  .unwrap();

  // Should not exit.
  assert_eq!(
    Err(RecvTimeoutError::Timeout),
    liveness_receiver.recv_timeout(Duration::from_millis(100))
  );
  event_sender
    .send(Err(notify::Error::generic(
      "This should kill the background thread",
    )))
    .unwrap();

  // Should exit.
  assert!(liveness_receiver
    .recv_timeout(Duration::from_millis(1000))
    .is_ok());
  join_handle.join().unwrap();
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
  fn invalidate(&self, paths: &HashSet<PathBuf>, _caller: InvalidateCaller) -> usize {
    let invalidated = paths.len();
    let mut calls = self.calls.lock();
    calls.push(paths.clone());
    invalidated
  }

  fn invalidate_all(&self, _caller: InvalidateCaller) -> usize {
    unimplemented!();
  }
}
