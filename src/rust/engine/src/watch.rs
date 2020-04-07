// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::{Arc, Weak};
use std::thread;
use std::time::Duration;

use crossbeam_channel::{self, Receiver, RecvTimeoutError, TryRecvError};
use futures::compat::Future01CompatExt;
use futures_locks::Mutex;
use log::{debug, error, info, warn};
use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use task_executor::Executor;

use fs::GitignoreStyleExcludes;
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
  enabled: bool,
}

impl InvalidationWatcher {
  pub fn new(
    graph: Weak<Graph<NodeKey>>,
    executor: Executor,
    build_root: PathBuf,
    ignorer: Arc<GitignoreStyleExcludes>,
    enabled: bool,
  ) -> Result<InvalidationWatcher, String> {
    // Inotify events contain canonical paths to the files being watched.
    // If the build_root contains a symlink the paths returned in notify events
    // wouldn't have the build_root as a prefix, and so we would miss invalidating certain nodes.
    // We canonicalize the build_root once so this isn't a problem.
    let canonical_build_root =
      std::fs::canonicalize(build_root.as_path()).map_err(|e| format!("{:?}", e))?;
    let (watch_sender, watch_receiver) = crossbeam_channel::unbounded();
    let mut watcher: RecommendedWatcher = Watcher::new(watch_sender, Duration::from_millis(50))
      .map_err(|e| format!("Failed to begin watching the filesystem: {}", e))?;

    let (thread_liveness_sender, thread_liveness_receiver) = crossbeam_channel::unbounded();
    if enabled {
      // On darwin the notify API is much more efficient if you watch the build root
      // recursively, so we set up that watch here and then return early when watch() is
      // called by nodes that are running. On Linux the notify crate handles adding paths to watch
      // much more efficiently so we do that instead on Linux.
      if cfg!(target_os = "macos") {
        watcher
          .watch(canonical_build_root.clone(), RecursiveMode::Recursive)
          .map_err(|e| {
            format!(
              "Failed to begin recursively watching files in the build root: {}",
              e
            )
          })?
      }
    }

    InvalidationWatcher::start_background_thread(
      graph,
      ignorer,
      canonical_build_root,
      thread_liveness_sender,
      watch_receiver,
    );

    Ok(InvalidationWatcher {
      watcher: Arc::new(Mutex::new(watcher)),
      executor,
      liveness: thread_liveness_receiver,
      enabled,
    })
  }

  // Public for testing purposes.
  pub fn start_background_thread(
    graph: Weak<Graph<NodeKey>>,
    ignorer: Arc<GitignoreStyleExcludes>,
    canonical_build_root: PathBuf,
    liveness_sender: crossbeam_channel::Sender<()>,
    watch_receiver: Receiver<notify::Result<notify::Event>>,
  ) {
    thread::spawn(move || {
      logging::set_thread_destination(logging::Destination::Pantsd);
      loop {
        let event_res = watch_receiver.recv_timeout(Duration::from_millis(10));
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
              .filter_map(|path| {
                // relativize paths to build root.
                let path_relative_to_build_root = if path.starts_with(&canonical_build_root) {
                  // Unwrapping is fine because we check that the path starts with
                  // the build root above.
                  path.strip_prefix(&canonical_build_root).unwrap().into()
                } else {
                  path
                };
                // To avoid having to stat paths for events we will eventually ignore we "lie" to the ignorer
                // to say that no path is a directory, they could be if someone chmod's or creates a dir.
                // This maintains correctness by ensuring that at worst we have false negative events, where a directory
                // only glob (one that ends in `/` ) was supposed to ignore a directory path, but didn't because we claimed it was a file. That
                // directory path will be used to invalidate nodes, but won't invalidate anything because its path is somewhere
                // out of our purview.
                if ignorer.is_ignored_or_child_of_ignored_path(
                  &path_relative_to_build_root,
                  /* is_dir */ false,
                ) {
                  None
                } else {
                  Some(path_relative_to_build_root)
                }
              })
              .map(|path_relative_to_build_root| {
                let mut paths_to_invalidate: Vec<PathBuf> = vec![];
                if let Some(parent_dir) = path_relative_to_build_root.parent() {
                  paths_to_invalidate.push(parent_dir.to_path_buf());
                }
                paths_to_invalidate.push(path_relative_to_build_root);
                paths_to_invalidate
              })
              .flatten()
              .collect();
            // Only invalidate stuff if we have paths that weren't filtered out by gitignore.
            if !paths.is_empty() {
              debug!("notify invalidating {:?} because of {:?}", paths, ev.kind);
              InvalidationWatcher::invalidate(&graph, &paths, "notify");
            };
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
      let _ = liveness_sender.send(());
    });
  }

  pub fn is_alive(&self) -> bool {
    if let Ok(()) = self.liveness.try_recv() {
      // The watcher background thread set the exit condition. Return false to signal that
      // the watcher is not alive.
      false
    } else {
      true
    }
  }

  ///
  /// Watch the given path non-recursively.
  ///
  pub async fn watch(&self, path: PathBuf) -> Result<(), notify::Error> {
    // Short circuit here if we are on a Darwin platform because we should be watching
    // the entire build root recursively already, or if we are not enabled.
    if cfg!(target_os = "macos") || !self.enabled {
      Ok(())
    } else {
      // Using a futurized mutex here because for some reason using a regular mutex
      // to block the io pool causes the v2 ui to not update which nodes its working
      // on properly.
      let watcher_lock = self.watcher.lock().compat().await;
      match watcher_lock {
        Ok(mut watcher_lock) => {
          self
            .executor
            .spawn_blocking(move || watcher_lock.watch(path, RecursiveMode::NonRecursive))
            .await
        }
        Err(()) => Err(notify::Error::new(notify::ErrorKind::Generic(
          "Couldn't lock mutex for invalidation watcher".to_string(),
        ))),
      }
    }
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
