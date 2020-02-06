// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Weak};
use std::thread;
use std::time::Duration;

use crossbeam_channel::{self, Receiver, RecvTimeoutError, TryRecvError};
use log::{error, warn};
use notify::{Event, RecommendedWatcher, RecursiveMode, Watcher};
use parking_lot::Mutex;

use graph::Graph;
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
  pub fn new(graph: Weak<Graph<NodeKey>>) -> Result<InvalidationWatcher, String> {
    // TODO: Get the logging destination properly after it has been setup
    // let logging_destination = logging::get_destination();
    let logging_destination = logging::Destination::Pantsd;
    let (watch_sender, watch_receiver) = crossbeam_channel::unbounded();
    let watcher = Arc::new(Mutex::new(
      Watcher::new(watch_sender, Duration::from_millis(50))
        .map_err(|e| format!("Failed to begin watching the filesystem: {}", e))?),
    );

    let (thread_liveness_sender, thread_liveness_receiver) = crossbeam_channel::unbounded();
    thread::spawn(move || {
      logging::set_destination(logging_destination);
      loop {
        let event_res = watch_receiver.recv_timeout(Duration::from_millis(100));
        let graph = if let Some(g) = graph.upgrade() {
          g
        } else {
          // The Graph has been dropped: we're done.
          break;
        };
        match event_res {
          Ok(Ok(ev)) => invalidate(&graph, ev),
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

  pub fn internal_watcher(&self) -> Arc<Mutex<RecommendedWatcher>> {
    Arc::clone(&self.watcher)
  }

  ///
  /// Watch the given path non-recursively.
  ///
  pub fn watch(watcher: Arc<Mutex<RecommendedWatcher>>, path : PathBuf) -> Result<(), ()> {
    warn!("watching {:?}", path);
    let mut watcher = watcher.lock();
      watcher
      .watch(&path, RecursiveMode::NonRecursive)
      .map_err(|_| warn!("watch failed for {:?}", path))
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
}

fn invalidate(graph: &Graph<NodeKey>, ev: Event) {
  let paths: HashSet<_> = ev.paths.into_iter().collect();
  warn!("notify invalidating {:?}", paths);
  graph.invalidate_from_roots(move |node| {
    if let Some(fs_subject) = node.fs_subject() {
      paths.contains(fs_subject)
    } else {
      false
    }
  });
}
