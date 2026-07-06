// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fs;
use std::io::{self, ErrorKind};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use async_trait::async_trait;

use crate::directory::SymlinkBehavior;
use crate::gitignore_stack::GitignoreStack;
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
    root_ignore: GitignoreStack,
    executor: task_executor::Executor,
    symlink_behavior: SymlinkBehavior,
}

// Non-public functions used internally by the public functions below.
impl PosixFS {
    pub fn new<P: AsRef<Path>>(
        root: P,
        ignorer: GitignoreStack,
        executor: task_executor::Executor,
    ) -> Result<PosixFS, String> {
        Self::new_with_symlink_behavior(root, ignorer, executor, SymlinkBehavior::Aware)
    }

    pub fn new_with_symlink_behavior<P: AsRef<Path>>(
        root: P,
        ignorer: GitignoreStack,
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
            root_ignore: ignorer,
            executor: executor,
            symlink_behavior: symlink_behavior,
        })
    }

    fn scandir_sync(
        &self,
        dir_relative_to_root: &Dir,
        gitignore_stack: GitignoreStack,
    ) -> Result<DirectoryListing, io::Error> {
        let dir_abs = self.root.join(dir_relative_to_root);
        let mut stats: Vec<Stat> = dir_abs
            .read_dir()?
            .map(|readdir| {
                let dir_entry = readdir?;
                let path_to_stat = dir_abs.join(dir_entry.file_name());
                let (file_type, compute_metadata): (_, Box<dyn FnOnce() -> Result<_, _>>) =
                    match self.symlink_behavior {
                        SymlinkBehavior::Aware => {
                            // Use the dir_entry metadata, which is symlink aware.
                            (dir_entry.file_type()?, Box::new(|| dir_entry.metadata()))
                        }
                        SymlinkBehavior::Oblivious => {
                            // Use an independent stat call to get metadata, which is symlink oblivious.
                            let metadata = std::fs::metadata(&path_to_stat)?;
                            (metadata.file_type(), Box::new(|| Ok(metadata)))
                        }
                    };
                PosixFS::stat_internal(&path_to_stat, file_type, compute_metadata)
            })
            .filter_map(Result::transpose)
            .collect::<Result<Vec<_>, io::Error>>()
            .map_err(|e| {
                io::Error::new(
                    e.kind(),
                    format!("Failed to scan directory {dir_abs:?}: {e}"),
                )
            })?;
        stats.retain(|s| {
            !gitignore_stack.is_path_ignored(
                &dir_relative_to_root.join(s.path()),
                matches!(s, Stat::Dir(_)),
            )
        });
        stats.sort_by(|s1, s2| s1.path().cmp(s2.path()));
        Ok(DirectoryListing(stats))
    }

    ///
    /// Makes a Stat for path_to_stat relative to its containing directory.
    ///
    /// This method takes both a `FileType` and a getter for `Metadata` because on Unixes,
    /// directory walks cheaply return the `FileType` without extra syscalls, but other
    /// metadata requires additional syscall(s) to compute. We can avoid those calls for
    /// Dirs and Links.
    ///
    fn stat_internal<F>(
        path_to_stat: &Path,
        file_type: std::fs::FileType,
        compute_metadata: F,
    ) -> Result<Option<Stat>, io::Error>
    where
        F: FnOnce() -> Result<std::fs::Metadata, io::Error>,
    {
        let Some(file_name) = path_to_stat.file_name() else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Argument path_to_stat to PosixFS::stat_internal must have a file name.",
            ));
        };
        if cfg!(debug_assertions) && !path_to_stat.is_absolute() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "Argument path_to_stat to PosixFS::stat_internal must be absolute path, got {path_to_stat:?}"
                ),
            ));
        }
        let path = file_name.to_owned().into();
        if file_type.is_symlink() {
            Ok(Some(Stat::Link(Link {
                path,
                target: std::fs::read_link(path_to_stat)?,
            })))
        } else if file_type.is_file() {
            let is_executable = compute_metadata()?.permissions().mode() & 0o100 == 0o100;
            Ok(Some(Stat::File(File {
                path,
                is_executable: is_executable,
            })))
        } else if file_type.is_dir() {
            Ok(Some(Stat::Dir(Dir(path))))
        } else {
            Ok(None)
        }
    }
}

// Public functions used externally.
impl PosixFS {
    pub async fn scandir(
        &self,
        dir_relative_to_root: Dir,
        gitignore_stack: GitignoreStack,
    ) -> Result<DirectoryListing, io::Error> {
        let vfs = self.clone();
        self.executor
            .spawn_blocking(move || vfs.scandir_sync(&dir_relative_to_root, gitignore_stack))
            .await?
            .map_err(|e| io::Error::other(format!("Synchronous scandir failed: {e}")))
    }

    pub fn read_gitignore_files(&self) -> bool {
        self.root_ignore.use_nested_gitignore
    }

    pub async fn push_gitignore_file(
        &self,
        dir: &Dir,
        parent_stack: GitignoreStack,
    ) -> Result<GitignoreStack, io::Error> {
        let dir = dir.clone();
        let gitignore_abs = self.root.join(&dir).join(".gitignore");
        self.executor
            .spawn_blocking(move || match std::fs::metadata(&gitignore_abs) {
                Ok(metadata) if metadata.is_file() => {
                    parent_stack.push(&dir, &gitignore_abs).map_err(|e| {
                        io::Error::other(format!("Failed to read {gitignore_abs:?}: {e}"))
                    })
                }
                Ok(_) => Ok(parent_stack),
                Err(e) if e.kind() == ErrorKind::NotFound => Ok(parent_stack),
                Err(e) => Err(io::Error::new(
                    e.kind(),
                    format!("Failed to stat {gitignore_abs:?}: {e}"),
                )),
            })
            .await?
    }

    pub fn is_ignored(&self, stat: &Stat) -> bool {
        self.root_ignore.is_stat_ignored(stat)
    }

    pub fn root_ignore(&self) -> &GitignoreStack {
        &self.root_ignore
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
        Ok(Arc::new(
            PosixFS::scandir(self, dir, self.root_ignore.clone()).await?,
        ))
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
