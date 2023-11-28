// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#[cfg(test)]
mod tests;

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Weak};
use std::thread;
use std::time::Duration;

use crossbeam_channel::{self, Receiver, RecvTimeoutError, TryRecvError};
use fs::GitignoreStyleExcludes;
use log::{debug, trace, warn};
use notify::event::{Flag, MetadataKind, ModifyKind};
use notify::{Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use parking_lot::Mutex;
use task_executor::Executor;

///
/// An InvalidationWatcher maintains a Thread that receives events from a notify Watcher.
///
/// If the spawned Thread exits for any reason, InvalidationWatcher::running() will return False,
/// and the caller should create a new InvalidationWatcher (or shut down, in some cases). Generally
/// this will mean polling.
///
struct Inner {
    watcher: RecommendedWatcher,
    executor: Executor,
    liveness: Receiver<String>,
    // Until the background task has started, contains the relevant inputs to launch it via
    // start_background_thread. The decoupling of creating the `InvalidationWatcher` and starting it
    // is to allow for testing of the background thread.
    background_task_inputs: Option<WatcherTaskInputs>,
}

type WatcherTaskInputs = (
    Arc<GitignoreStyleExcludes>,
    PathBuf,
    crossbeam_channel::Sender<String>,
    Receiver<notify::Result<Event>>,
);

pub struct InvalidationWatcher(Mutex<Inner>);

impl InvalidationWatcher {
    pub fn new(
        executor: Executor,
        build_root: PathBuf,
        ignorer: Arc<GitignoreStyleExcludes>,
    ) -> Result<Arc<InvalidationWatcher>, String> {
        // Inotify events contain canonical paths to the files being watched.
        // If the build_root contains a symlink the paths returned in notify events
        // wouldn't have the build_root as a prefix, and so we would miss invalidating certain nodes.
        // We canonicalize the build_root once so this isn't a problem.
        let canonical_build_root =
            std::fs::canonicalize(build_root.as_path()).map_err(|e| format!("{e:?}"))?;
        let (watch_sender, watch_receiver) = crossbeam_channel::unbounded();
        let mut watcher: RecommendedWatcher = notify::recommended_watcher(move |ev| {
            if watch_sender.send(ev).is_err() {
                // The watch thread shutting down first is ok, because it can exit when the Invalidatable
                // is dropped.
                debug!("Watch thread has shutdown, but Watcher is still running.");
            }
        })
        .and_then(|mut watcher| {
            // We attempt to consume precise events to skip invalidating parent directories for
            // data-change events, but `handle_event` should safely operate without them.
            let _ = watcher.configure(notify::Config::PreciseEvents(true))?;
            Ok(watcher)
        })
        .map_err(|e| format!("Failed to begin watching the filesystem: {e}"))?;

        let (liveness_sender, liveness_receiver) = crossbeam_channel::unbounded();

        // On darwin the notify API is much more efficient if you watch the build root
        // recursively, so we set up that watch here and then return early when watch() is
        // called by nodes that are running. On Linux the notify crate handles adding paths to watch
        // much more efficiently so we do that instead on Linux.
        if cfg!(target_os = "macos") {
            watcher
                .watch(&canonical_build_root, RecursiveMode::Recursive)
                .map_err(|e| {
                    format!("Failed to begin recursively watching files in the build root: {e}")
                })?
        }

        Ok(Arc::new(InvalidationWatcher(Mutex::new(Inner {
            watcher,
            executor,
            liveness: liveness_receiver,
            background_task_inputs: Some((
                ignorer,
                canonical_build_root,
                liveness_sender,
                watch_receiver,
            )),
        }))))
    }

    ///
    /// Starts the background task that monitors watch events. Panics if called more than once.
    ///
    pub fn start<I: Invalidatable>(&self, invalidatable: &Arc<I>) -> Result<(), String> {
        let mut inner = self.0.lock();
        let (ignorer, canonical_build_root, liveness_sender, watch_receiver) = inner
            .background_task_inputs
            .take()
            .expect("An InvalidationWatcher can only be started once.");

        InvalidationWatcher::start_background_thread(
            Arc::downgrade(invalidatable),
            ignorer,
            canonical_build_root,
            liveness_sender,
            watch_receiver,
        )?;

        Ok(())
    }

    // Public for testing purposes.
    pub(crate) fn start_background_thread<I: Invalidatable>(
        invalidatable: Weak<I>,
        ignorer: Arc<GitignoreStyleExcludes>,
        canonical_build_root: PathBuf,
        liveness_sender: crossbeam_channel::Sender<String>,
        watch_receiver: Receiver<notify::Result<Event>>,
    ) -> Result<thread::JoinHandle<()>, String> {
        thread::Builder::new()
            .name("fs-watcher".to_owned())
            .spawn(move || {
                let exit_msg = loop {
                    let event_res = watch_receiver.recv_timeout(Duration::from_millis(10));
                    let invalidatable = if let Some(g) = invalidatable.upgrade() {
                        g
                    } else {
                        // The Invalidatable has been dropped: we're done.
                        break "The watcher was shut down.".to_string();
                    };
                    match event_res {
                        Ok(Ok(ev)) => {
                            Self::handle_event(&*invalidatable, &ignorer, &canonical_build_root, ev)
                        }
                        Ok(Err(err)) => {
                            if let notify::ErrorKind::PathNotFound = err.kind {
                                warn!("Path(s) did not exist: {:?}", err.paths);
                                continue;
                            } else {
                                break format!("Watch error: {err}");
                            }
                        }
                        Err(RecvTimeoutError::Timeout) => continue,
                        Err(RecvTimeoutError::Disconnected) => {
                            break "The watch provider exited.".to_owned();
                        }
                    };
                };

                // Log and send the exit code.
                warn!("File watcher exiting with: {}", exit_msg);
                let _ = liveness_sender.send(exit_msg);
            })
            .map_err(|e| format!("Failed to start fs-watcher thread: {e}"))
    }

    ///
    /// Handle a single invalidation Event.
    ///
    /// This method must not assume that it receives PreciseEvents, because construction does not
    /// validate that it is possible to enable them.
    ///
    fn handle_event<I: Invalidatable>(
        invalidatable: &I,
        ignorer: &GitignoreStyleExcludes,
        canonical_build_root: &Path,
        ev: Event,
    ) {
        if matches!(ev.kind, EventKind::Modify(ModifyKind::Metadata(mk)) if mk != MetadataKind::Permissions)
        {
            // (Other than permissions, which include the executable bit) if only the metadata
            // (AccessTime, WriteTime, Perms, Link Count, etc...) was changed, it doesn't change anything
            // Pants particularly cares about.
            //
            // One could argue if the ownership changed Pants would care, but until the
            // name/data changes (which would be a separate event) the substance of the file in Pants'
            // eyes is the same.
            return;
        }

        let is_data_only_event = matches!(ev.kind, EventKind::Modify(ModifyKind::Data(_)));
        let flag = ev.flag();

        let paths: HashSet<_> = ev
            .paths
            .into_iter()
            .filter_map(|path| {
                // relativize paths to build root.
                let path_relative_to_build_root = if path.starts_with(canonical_build_root) {
                    // Unwrapping is fine because we check that the path starts with
                    // the build root above.
                    path.strip_prefix(canonical_build_root).unwrap().into()
                } else {
                    path
                };
                // To avoid having to stat paths for events we will eventually ignore we "lie" to
                // the ignorer to say that no path is a directory (although they could be if someone
                // chmod's or creates a dir).
                //
                // This maintains correctness by ensuring that at worst we have false negative
                // events, where a directory-only glob (one that ends in `/` ) was supposed to
                // ignore a directory path, but didn't because we claimed it was a file. That
                // directory path will be used to invalidate nodes, but won't invalidate anything
                // because its path is somewhere out of our purview.
                if ignorer.is_ignored_or_child_of_ignored_path(
                    &path_relative_to_build_root,
                    /* is_dir */ false,
                ) {
                    trace!("notify ignoring {:?}", path_relative_to_build_root);
                    None
                } else {
                    Some(path_relative_to_build_root)
                }
            })
            .flat_map(|path_relative_to_build_root| {
                let mut paths_to_invalidate: Vec<PathBuf> = Vec::with_capacity(2);
                if !is_data_only_event {
                    // If the event is anything other than a data change event (a change to the content of
                    // a file), then we additionally invalidate the parent of the path.
                    if let Some(parent_dir) = path_relative_to_build_root.parent() {
                        paths_to_invalidate.push(parent_dir.to_path_buf());
                    }
                }
                paths_to_invalidate.push(path_relative_to_build_root);
                paths_to_invalidate
            })
            .collect();

        if flag == Some(Flag::Rescan) {
            debug!("notify queue overflowed: invalidating all paths");
            invalidatable.invalidate_all(InvalidateCaller::Notify);
        } else if !paths.is_empty() {
            debug!("notify invalidating {:?} because of {:?}", paths, ev.kind);
            invalidatable.invalidate(&paths, InvalidateCaller::Notify);
        }
    }

    ///
    /// An InvalidationWatcher will never restart on its own: a consumer should re-initialize if this
    /// method returns an error.
    ///
    /// NB: This is currently polled by pantsd, but it could be long-polled or a callback.
    ///
    pub async fn is_valid(&self) -> Result<(), String> {
        // Confirm that the Watcher itself is still alive.
        let watcher = self.0.lock();
        match watcher.liveness.try_recv() {
            Ok(msg) => {
                // The watcher background task set the exit condition.
                Err(msg)
            }
            Err(TryRecvError::Disconnected) => {
                // The watcher background task died (panic, possible?).
                Err(
          "The filesystem watcher exited abnormally: please see the log for more information."
            .to_owned(),
        )
            }
            Err(TryRecvError::Empty) => {
                // Still alive.
                Ok(())
            }
        }
    }

    ///
    /// Add a path to the set of paths being watched by this invalidation watcher, non-recursively.
    ///
    pub async fn watch(self: &Arc<Self>, path: PathBuf) -> Result<(), String> {
        if cfg!(target_os = "macos") {
            // Short circuit here if we are on a Darwin platform because we should be watching
            // the entire build root recursively already.
            return Ok(());
        }

        let executor = {
            let inner = self.0.lock();
            inner.executor.clone()
        };

        let watcher = self.clone();
        executor
            .spawn_blocking(
                move || {
                    let mut inner = watcher.0.lock();
                    inner
                        .watcher
                        .watch(&path, RecursiveMode::NonRecursive)
                        .map_err(|e| maybe_enrich_notify_error(&path, e))
                },
                |e| Err(format!("Watch attempt failed: {e}")),
            )
            .await
    }
}

pub enum InvalidateCaller {
    External,
    Notify,
}

pub trait Invalidatable: Send + Sync + 'static {
    fn invalidate(&self, paths: &HashSet<PathBuf>, caller: InvalidateCaller) -> usize;
    fn invalidate_all(&self, caller: InvalidateCaller) -> usize;
}

///
/// If on Linux, attempt to report the relevant inotify limit(s).
///
fn maybe_enrich_notify_error(path: &Path, e: notify::Error) -> String {
    let hint = match &e.kind {
        notify::ErrorKind::Io(e) if cfg!(target_os = "linux") && e.raw_os_error() == Some(28) => {
            // In the context of an attempt to watch a path, an ENOSPC error indicates that you've bumped
            // into the limit on max watches.
            let limit_value = if let Ok(limit) =
                std::fs::read_to_string("/proc/sys/fs/inotify/max_user_watches")
            {
                format!("yours is set to {}", limit.trim())
            } else {
                "unable to read limit value".to_string()
            };
            format!("\n\nOn Linux, this can be caused by a `max_user_watches` setting that is lower \
              than the number of files and directories in your repository ({limit_value}). Please see \
              https://www.pantsbuild.org/docs/troubleshooting#no-space-left-on-device-error-while-watching-files \
              for more information.")
        }
        _ => "".to_string(),
    };
    format!(
        "Failed to watch filesystem for `{}`: {:?}{}",
        path.display(),
        e,
        hint
    )
}
