// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::{Arc, Weak};
use std::thread;
use std::time::Duration;

use boxfuture::{BoxFuture, Boxable};
use crossbeam_channel::{self, Receiver, RecvTimeoutError, TryRecvError};
use futures01::future::{Future, IntoFuture};
use futures_locks::Mutex;
use log::{debug, error, info, warn};
use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use task_executor::Executor;

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
/// TODO: Need the above polling
///
/// TODO: To simplify testing the InvalidationWatcher we could create  a trait which
/// has an `invalidate_from_roots` method  and impl it on the Graph. Then we could make the InvalidationWatcher
/// take an argument that implements the trait.
/// Then we wouldn't have to mock out a Graph object in watch_tests.rs. This will probably
/// only be possible when we remove watchman invalidation, when the one code path for invaldation will be
/// the notify background thread.
/// Potential impl here: https://github.com/pantsbuild/pants/pull/9318#discussion_r396005978 
///
pub struct InvalidationWatcher {
  watcher: Arc<Mutex<RecommendedWatcher>>,
  executor: Executor,
  liveness: Receiver<()>,
}

impl InvalidationWatcher {
  pub fn new(
    graph: Weak<Graph<NodeKey>>,
    executor: Executor,
    build_root: PathBuf,
  ) -> Result<InvalidationWatcher, String> {
    // Inotify events contain canonical paths to the files being watched.
    // If the build_root contains a symlink the paths returned in notify events
    // wouldn't have the build_root as a prefix, and so we would miss invalidating certain nodes.
    // We canonicalize the build_root once so this isn't a problem.
    let canonical_build_root =
      std::fs::canonicalize(build_root.as_path()).map_err(|e| format!("{:?}", e))?;
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
                let mut paths_to_invalidate: Vec<PathBuf> = vec![];
                let path_relative_to_build_root = {
                  if path.starts_with(&canonical_build_root) {
                    path.strip_prefix(&canonical_build_root).unwrap().into()
                  } else {
                    path
                  }
                };
                paths_to_invalidate.push(path_relative_to_build_root.clone());
                if let Some(parent_dir) = path_relative_to_build_root.parent() {
                  paths_to_invalidate.push(parent_dir.to_path_buf());
                }
                paths_to_invalidate
              })
              .flatten()
              .collect();
            info!("notify invalidating {:?} because of {:?}", paths, ev.kind);
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
      debug!("Watch thread exiting.");
      // Signal that we're exiting (which we would also do by just dropping the channel).
      let _ = thread_liveness_sender.send(());
    });

    Ok(InvalidationWatcher {
      watcher,
      executor,
      liveness: thread_liveness_receiver,
    })
  }

  ///
  /// Watch the given path non-recursively.
  ///
  pub fn watch(&self, path: PathBuf) -> BoxFuture<(), notify::Error> {
    let watcher = self.watcher.clone();
    let path2 = path.clone();
    let executor = self.executor.clone();
    watcher.lock()
    .map_err(move |()| notify::Error::new(notify::ErrorKind::Generic(format!("Could not get lock on notify watcher to watch path {:?}", path2))))
    .and_then(move |mut watcher_lock| {
        executor
        .spawn_on_io_pool(
            watcher_lock.watch(path, RecursiveMode::NonRecursive).into_future()
          )
      }).to_boxed()
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
    info!(
      "{} invalidation: cleared {} and dirtied {} nodes for: {:?}",
      caller, cleared, dirtied, paths
    );
    cleared + dirtied
  }
}
