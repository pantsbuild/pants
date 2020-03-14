// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::{Arc, Weak};
use std::thread;
use std::time::Duration;

use boxfuture::{BoxFuture, Boxable};
use crossbeam_channel::{self, Receiver, RecvTimeoutError, TryRecvError};
use futures01 as futures;
use futures01::future::Future;
use log::{error, warn};
use notify::{RecommendedWatcher, RecursiveMode, Result as NotifyResult, Watcher};
use parking_lot::Mutex;

use graph::{Graph, InvalidationResult};
use logging;

use crate::nodes::NodeKey;

///
/// An InvalidationWatcher maintains a Thread that receives events from a notify Watcher.
///
/// If the spawned Thread exits for any reason, InvalidationWatcher::running() will return False,
/// and the caller should create a new InvalidationWatcher (or shut down, in some cases). Generally
/// this will mean polling.
///
/// TODO: Need the above polling, and need to make the watch method async.
///
pub struct InvalidationWatcher {
  watcher: Arc<Mutex<RecommendedWatcher>>,
  liveness: Receiver<()>,
}

impl InvalidationWatcher {
  pub fn new(
    graph: Weak<Graph<NodeKey>>,
    build_root: PathBuf,
  ) -> Result<InvalidationWatcher, String> {
    let (watch_sender, watch_receiver) = crossbeam_channel::unbounded();
    let watcher = Arc::new(Mutex::new(
      Watcher::new(watch_sender, Duration::from_millis(50))
        .map_err(|e| format!("Failed to begin watching the filesystem: {}", e))?,
    ));

    let (thread_liveness_sender, thread_liveness_receiver) = crossbeam_channel::unbounded();
    thread::spawn(move || {
      logging::set_destination(logging::Destination::Pantsd);
      loop {
        let event_res = watch_receiver.recv_timeout(Duration::from_millis(100));
        let graph = if let Some(g) = graph.upgrade() {
          g
        } else {
          // The Graph has been dropped: we're done.
          break;
        };
        match event_res {
          Ok(Ok(ev)) => {
            let paths: HashSet<_> = ev
              .paths
              .into_iter()
              .map(|path| {
                // relativize paths to build root.
                if path.starts_with(&build_root) {
                  path.strip_prefix(&build_root).unwrap().into()
                } else {
                  path
                }
              })
              .collect();
            warn!("notify invalidating {:?} because of {:?}", paths, ev.kind);
            InvalidationWatcher::invalidate(&graph, &paths, "notify");
          }
          Ok(Err(err)) => {
            if let notify::ErrorKind::PathNotFound = err.kind {
              warn!("Path(s) did not exist: {:?}", err.paths);
              continue;
            } else {
              error!("File watcher failing with: {}", err);
              break;
            }
          }
          Err(RecvTimeoutError::Timeout) => continue,
          Err(RecvTimeoutError::Disconnected) => {
            // The Watcher is gone: we're done.
            break;
          }
        };
      }
      warn!("Watch thread exiting.");
      // Signal that we're exiting (which we would also do by just dropping the channel).
      let _ = thread_liveness_sender.send(());
    });

    Ok(InvalidationWatcher {
      watcher,
      liveness: thread_liveness_receiver,
    })
  }

  ///
  /// Watch the given path non-recursively.
  ///
  pub fn watch(&self, path: PathBuf) -> BoxFuture<(), ()> {
    WatchFuture::new(self.watcher.clone(), path.clone())
      .map_err(move |e| warn!("Failed to watch path {:?}, with error {:?}", path, e))
      .to_boxed()
  }

  ///
  /// Returns true if this InvalidationWatcher is still valid: if it is not valid, it will have
  /// already logged some sort of error, and will never restart on its own.
  ///
  pub fn running(&self) -> bool {
    match self.liveness.try_recv() {
      Ok(()) | Err(TryRecvError::Disconnected) => false,
      Err(TryRecvError::Empty) => true,
    }
  }

  pub fn invalidate(graph: &Graph<NodeKey>, paths: &HashSet<PathBuf>, caller: &str) -> usize {
    let InvalidationResult { cleared, dirtied } = graph.invalidate_from_roots(move |node| {
      if let Some(fs_subject) = node.fs_subject() {
        paths.contains(fs_subject)
      } else {
        false
      }
    });
    // TODO: The rust log level is not currently set correctly in a pantsd context. To ensure that
    // we see this even at `info` level, we set it to warn. #6004 should address this by making
    // rust logging re-configuration an explicit step in `src/python/pants/init/logging.py`.
    warn!(
      "{} invalidation: cleared {} and dirtied {} nodes for: {:?}",
      caller, cleared, dirtied, paths
    );
    cleared + dirtied
  }
}

struct WatchFuture {
  watcher: Arc<Mutex<RecommendedWatcher>>,
  path: PathBuf,
  watch_result: Arc<Mutex<Option<NotifyResult<()>>>>,
  thread_started: bool,
}

impl WatchFuture {
  fn new(watcher: Arc<Mutex<RecommendedWatcher>>, path: PathBuf) -> WatchFuture {
    WatchFuture {
      watcher,
      path,
      watch_result: Arc::new(Mutex::new(None)),
      thread_started: false,
    }
  }
}

impl Future for WatchFuture {
  type Item = ();
  type Error = String;

  fn poll(&mut self) -> futures::Poll<Self::Item, Self::Error> {
    if !self.thread_started {
      thread::spawn({
        let current_task = futures::task::current();
        let watcher = self.watcher.clone();
        let watch_result2 = self.watch_result.clone();
        let path = self.path.clone();
        move || {
          let mut watch_result2 = watch_result2.lock();
          let mut watcher = watcher.lock();
          *watch_result2 = Some(watcher.watch(path, RecursiveMode::NonRecursive));
          current_task.notify();
        }
      });
      self.thread_started = true;
      Ok(futures::Async::NotReady)
    } else if let Some(watch_result) = self.watch_result.try_lock() {
      match *watch_result {
        Some(Ok(_)) => Ok(futures::Async::Ready(())),
        Some(Err(ref watch_error)) => Err(format!("{:?}", watch_error)),
        None => unreachable!(), // We check if the watch result is None before reaching this block.
      }
    } else {
      Ok(futures::Async::NotReady)
    }
  }
}
