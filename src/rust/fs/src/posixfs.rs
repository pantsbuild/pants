// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::ffi::OsString;
use std::fs;
use std::io::{self, ErrorKind};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use async_trait::async_trait;

use crate::directory::SymlinkBehavior;
use crate::gitignore::GitignoreStyleExcludes;
use crate::{Dir, DirectoryListing, File, Link, PathMetadata, PathMetadataKind, Stat, Vfs};

///
/// All Stats consumed or returned by this type are relative to the root.
///
/// If `symlink_behavior` is Aware (as it is by default), `scandir` will produce `Link` entries so
/// that a consumer can explicitly track their expansion. Otherwise, if Oblivious, operations will
/// allow the operating system to expand links to their underlying types without regard to the
/// links traversed, and `scandir` will produce only `Dir` and `File` entries.
///
#[derive(Clone)]
pub struct PosixFS {
    root: Dir,
    ignore: Arc<GitignoreStyleExcludes>,
    executor: task_executor::Executor,
    symlink_behavior: SymlinkBehavior,
}

// Non-public functions used internally by the public functions below.
impl PosixFS {
    pub fn new<P: AsRef<Path>>(
        root: P,
        ignorer: Arc<GitignoreStyleExcludes>,
        executor: task_executor::Executor,
    ) -> Result<PosixFS, String> {
        Self::new_with_symlink_behavior(root, ignorer, executor, SymlinkBehavior::Aware)
    }

    pub fn new_with_symlink_behavior<P: AsRef<Path>>(
        root: P,
        ignorer: Arc<GitignoreStyleExcludes>,
        executor: task_executor::Executor,
        symlink_behavior: SymlinkBehavior,
    ) -> Result<PosixFS, String> {
        let root: &Path = root.as_ref();
        let canonical_root = root
            .canonicalize()
            .and_then(|canonical| {
                canonical.metadata().and_then(|metadata| {
                    if metadata.is_dir() {
                        Ok(Dir(canonical))
                    } else {
                        Err(io::Error::new(
                            io::ErrorKind::InvalidInput,
                            "Not a directory.",
                        ))
                    }
                })
            })
            .map_err(|e| format!("Could not canonicalize root {root:?}: {e:?}"))?;

        Ok(PosixFS {
            root: canonical_root,
            ignore: ignorer,
            executor: executor,
            symlink_behavior: symlink_behavior,
        })
    }

    fn scandir_sync(&self, dir_relative_to_root: Dir) -> Result<DirectoryListing, io::Error> {
        let dir_abs = self.root.0.join(&dir_relative_to_root.0);
        let read_dir = dir_abs.read_dir()?;

        let mut entry_abs = dir_abs;

        let mut stats: Vec<Stat> = Vec::new();
        for dir_entry in read_dir {
            let dir_entry = dir_entry.map_err(|e| Self::scandir_error(&entry_abs, e))?;

            // Reuse the owned `file_name` as the `Stat`'s path so it's allocated only once.
            let file_name = dir_entry.file_name();
            entry_abs.push(&file_name);
            let stat = self.scan_entry(&entry_abs, file_name, &dir_entry);
            entry_abs.pop();

            if let Some(stat) = stat.map_err(|e| Self::scandir_error(&entry_abs, e))? {
                stats.push(stat);
            }
        }
        stats.sort_by(|s1, s2| s1.path().cmp(s2.path()));
        Ok(DirectoryListing(stats))
    }

    fn scandir_error(dir_abs: &Path, e: io::Error) -> io::Error {
        io::Error::new(
            e.kind(),
            format!("Failed to scan directory {dir_abs:?}: {e}"),
        )
    }

    fn scan_entry(
        &self,
        entry_abs: &Path,
        file_name: OsString,
        dir_entry: &std::fs::DirEntry,
    ) -> Result<Option<Stat>, io::Error> {
        let stat = match self.symlink_behavior {
            SymlinkBehavior::Aware => {
                let file_type = dir_entry.file_type()?;
                Self::make_stat(entry_abs, file_name.into(), file_type, || {
                    dir_entry.metadata()
                })?
            }
            SymlinkBehavior::Oblivious => {
                let metadata = std::fs::metadata(entry_abs)?;
                Self::make_stat(entry_abs, file_name.into(), metadata.file_type(), || {
                    Ok(metadata)
                })?
            }
        };

        // It would be nice to ignore paths before stat'ing them, but git-style ignore patterns need
        // to know whether a path is a directory. The matcher takes a root-relative path, which is
        // `entry_abs` minus the root prefix (always present, since `entry_abs` is joined onto it).
        let Some(stat) = stat else {
            return Ok(None);
        };
        let rel = entry_abs
            .strip_prefix(&self.root.0)
            .expect("entry path is always under the root");
        if self
            .ignore
            .is_ignored_path(rel, matches!(stat, Stat::Dir(_)))
        {
            Ok(None)
        } else {
            Ok(Some(stat))
        }
    }

    // Makes a Stat for `path_to_stat`, deriving its directory-relative name from the final path
    // component. Callers on the directory-walk hot path use `make_stat` instead, reusing the name
    // they already own.
    fn stat_internal<F>(
        path_to_stat: &Path,
        file_type: std::fs::FileType,
        compute_metadata: F,
    ) -> Result<Option<Stat>, io::Error>
    where
        F: FnOnce() -> Result<std::fs::Metadata, io::Error>,
    {
        let Some(name) = path_to_stat.file_name() else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Argument path_to_stat to PosixFS::stat_internal must have a file name.",
            ));
        };
        Self::make_stat(path_to_stat, name.into(), file_type, compute_metadata)
    }

    fn make_stat<F>(
        abs_path: &Path,
        name: PathBuf,
        file_type: std::fs::FileType,
        compute_metadata: F,
    ) -> Result<Option<Stat>, io::Error>
    where
        F: FnOnce() -> Result<std::fs::Metadata, io::Error>,
    {
        if cfg!(debug_assertions) && !abs_path.is_absolute() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "Argument abs_path to PosixFS::make_stat must be an absolute path, got {abs_path:?}"
                ),
            ));
        }
        if file_type.is_symlink() {
            Ok(Some(Stat::Link(Link {
                path: name,
                target: std::fs::read_link(abs_path)?,
            })))
        } else if file_type.is_file() {
            let is_executable = compute_metadata()?.permissions().mode() & 0o100 == 0o100;
            Ok(Some(Stat::File(File {
                path: name,
                is_executable,
            })))
        } else if file_type.is_dir() {
            Ok(Some(Stat::Dir(Dir(name))))
        } else {
            Ok(None)
        }
    }
}

// Public functions used externally.
impl PosixFS {
    pub async fn scandir(&self, dir_relative_to_root: Dir) -> Result<DirectoryListing, io::Error> {
        let vfs = self.clone();
        self.executor
            .spawn_blocking(move || vfs.scandir_sync(dir_relative_to_root))
            .await?
            .map_err(|e| io::Error::other(format!("Synchronous scandir failed: {e}")))
    }

    pub fn is_ignored(&self, stat: &Stat) -> bool {
        self.ignore.is_ignored(stat)
    }

    pub fn file_path(&self, file: &File) -> PathBuf {
        self.root.0.join(&file.path)
    }

    pub async fn read_link(&self, link: &Link) -> Result<PathBuf, io::Error> {
        let link_parent = link.path.parent().map(Path::to_owned);
        let link_abs = self.root.0.join(link.path.as_path());
        tokio::fs::read_link(&link_abs)
            .await
            .and_then(|path_buf| {
                if path_buf.is_absolute() {
                    Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        format!("Absolute symlink: {path_buf:?}"),
                    ))
                } else {
                    link_parent
                        .map(|parent| parent.join(&path_buf))
                        .ok_or_else(|| {
                            io::Error::new(
                                io::ErrorKind::InvalidData,
                                format!("Symlink without a parent?: {path_buf:?}"),
                            )
                        })
                }
            })
            .map_err(|e| io::Error::new(e.kind(), format!("Failed to read link {link_abs:?}: {e}")))
    }

    ///
    /// Returns a Stat relative to its containing directory.
    ///
    /// NB: This method is synchronous because it is used to stat all files in a directory as one
    /// blocking operation as part of `scandir_sync` (as recommended by the `tokio` documentation, to
    /// avoid many small spawned tasks).
    ///
    pub fn stat_sync(&self, relative_path: &Path) -> Result<Option<Stat>, io::Error> {
        if cfg!(debug_assertions) && relative_path.is_absolute() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "Argument relative_path to PosixFS::stat_sync must be relative path, got {relative_path:?}"
                ),
            ));
        }
        let abs_path = self.root.0.join(relative_path);
        let metadata = match self.symlink_behavior {
            SymlinkBehavior::Aware => fs::symlink_metadata(&abs_path),
            SymlinkBehavior::Oblivious => fs::metadata(&abs_path),
        };
        metadata
            .and_then(|metadata| {
                PosixFS::stat_internal(&abs_path, metadata.file_type(), || Ok(metadata))
            })
            .or_else(|err| match err.kind() {
                io::ErrorKind::NotFound => Ok(None),
                _ => Err(err),
            })
    }

    pub async fn path_metadata(
        &self,
        path: PathBuf,
        follow_symlinks: bool,
    ) -> Result<Option<PathMetadata>, io::Error> {
        let abs_path = self.root.0.join(&path);
        let raw_metadata = if follow_symlinks {
            tokio::fs::metadata(&abs_path).await
        } else {
            tokio::fs::symlink_metadata(&abs_path).await
        };
        match raw_metadata {
            Ok(metadata) => {
                let (kind, symlink_target) = match metadata.file_type() {
                    ft if ft.is_symlink() => {
                        let symlink_target = tokio::fs::read_link(&abs_path).await.map_err(|e| io::Error::other(format!("path {abs_path:?} was previously a symlink but read_link failed: {e}")))?;
                        (PathMetadataKind::Symlink, Some(symlink_target))
                    }
                    ft if ft.is_dir() => (PathMetadataKind::Directory, None),
                    ft if ft.is_file() => (PathMetadataKind::File, None),
                    _ => unreachable!("std::fs::FileType was not a symlink, directory, or file"),
                };

                #[cfg(target_family = "unix")]
                let (unix_mode, is_executable) = {
                    let mode = metadata.permissions().mode();
                    (Some(mode), (mode & 0o111) != 0)
                };

                Ok(Some(PathMetadata {
                    path,
                    kind,
                    length: metadata.len(),
                    is_executable,
                    unix_mode,
                    accessed: metadata.accessed().ok(),
                    created: metadata.created().ok(),
                    modified: metadata.modified().ok(),
                    symlink_target,
                }))
            }
            Err(err) if err.kind() == ErrorKind::NotFound => Ok(None),
            // A path component is a file rather than a directory: treat as not found.
            Err(err) if err.kind() == ErrorKind::NotADirectory => Ok(None),
            Err(err) => Err(err),
        }
    }
}

#[async_trait]
impl Vfs<io::Error> for Arc<PosixFS> {
    async fn read_link(&self, link: &Link) -> Result<PathBuf, io::Error> {
        PosixFS::read_link(self, link).await
    }

    async fn scandir(&self, dir: Dir) -> Result<Arc<DirectoryListing>, io::Error> {
        Ok(Arc::new(PosixFS::scandir(self, dir).await?))
    }

    async fn path_metadata(
        &self,
        path: PathBuf,
        follow_symlinks: bool,
    ) -> Result<Option<PathMetadata>, io::Error> {
        PosixFS::path_metadata(self, path, follow_symlinks).await
    }

    fn is_ignored(&self, stat: &Stat) -> bool {
        PosixFS::is_ignored(self, stat)
    }

    fn mk_error(msg: &str) -> io::Error {
        io::Error::other(msg)
    }
}
