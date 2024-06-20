// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

pub mod directory;
#[cfg(test)]
mod directory_tests;
pub mod gitignore;
mod glob_matching;
#[cfg(test)]
mod glob_matching_tests;
#[cfg(test)]
mod posixfs_tests;
#[cfg(test)]
mod testutil;

pub use crate::directory::{
    DigestTrie, DirectoryDigest, Entry, SymlinkBehavior, TypedPath, EMPTY_DIGEST_TREE,
    EMPTY_DIRECTORY_DIGEST,
};
pub use crate::gitignore::GitignoreStyleExcludes;
pub use crate::glob_matching::{
    FilespecMatcher, GlobMatching, PathGlob, PreparedPathGlobs, DOUBLE_STAR_GLOB, SINGLE_STAR_GLOB,
};

use std::cmp::min;
use std::io::{self, ErrorKind};
use std::ops::Deref;
use std::os::unix::fs::PermissionsExt;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use std::time::SystemTime;
use std::{fmt, fs};

use async_trait::async_trait;
use bytes::Bytes;
use deepsize::DeepSizeOf;
use pyo3::prelude::*;
use serde::Serialize;

const TARGET_NOFILE_LIMIT: u64 = 10000;

const XDG_CACHE_HOME: &str = "XDG_CACHE_HOME";

/// NB: Linux limits path lookups to 40 symlink traversals: https://lwn.net/Articles/650786/
///
/// We use a slightly different limit because this is not exactly the same operation: we're
/// walking recursively while matching globs, and so our link traversals might involve steps
/// through non-link destinations.
const MAX_LINK_DEPTH: u8 = 64;

type LinkDepth = u8;

/// Follows the unix XDB base spec: <http://standards.freedesktop.org/basedir-spec/latest/index.html>.
pub fn default_cache_path() -> PathBuf {
    let cache_path = std::env::var(XDG_CACHE_HOME)
        .ok()
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .or_else(|| dirs_next::home_dir().map(|home| home.join(".cache")))
        .unwrap_or_else(|| panic!("Could not find home dir or {XDG_CACHE_HOME}."));
    cache_path.join("pants")
}

/// Simplified filesystem Permissions.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum Permissions {
    ReadOnly,
    Writable,
}

#[derive(Clone, Debug, DeepSizeOf, PartialEq, Eq, Ord, PartialOrd, Hash, Serialize)]
pub struct RelativePath(PathBuf);

impl RelativePath {
    pub fn empty() -> RelativePath {
        RelativePath(PathBuf::new())
    }

    pub fn new<P: AsRef<Path>>(path: P) -> Result<RelativePath, String> {
        let mut relative_path = PathBuf::new();
        let candidate = path.as_ref();
        for component in candidate.components() {
            match component {
                Component::Prefix(_) => {
                    return Err(format!("Windows paths are not allowed: {candidate:?}"))
                }
                Component::RootDir => {
                    return Err(format!("Absolute paths are not allowed: {candidate:?}"))
                }
                Component::CurDir => continue,
                Component::ParentDir => {
                    if !relative_path.pop() {
                        return Err(format!(
                            "Relative paths that escape the root are not allowed: {candidate:?}"
                        ));
                    }
                }
                Component::Normal(path) => relative_path.push(path),
            }
        }
        Ok(RelativePath(relative_path))
    }

    pub fn to_str(&self) -> Option<&str> {
        self.0.to_str()
    }

    pub fn join(&self, other: Self) -> RelativePath {
        RelativePath(self.0.join(other))
    }
}

impl Deref for RelativePath {
    type Target = PathBuf;

    fn deref(&self) -> &PathBuf {
        &self.0
    }
}

impl AsRef<Path> for RelativePath {
    fn as_ref(&self) -> &Path {
        self.0.as_path()
    }
}

impl From<RelativePath> for PathBuf {
    fn from(p: RelativePath) -> Self {
        p.0
    }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub enum Stat {
    Link(Link),
    Dir(Dir),
    File(File),
}

impl Stat {
    pub fn path(&self) -> &Path {
        match self {
            &Stat::Dir(Dir(ref p)) => p.as_path(),
            &Stat::File(File { path: ref p, .. }) => p.as_path(),
            &Stat::Link(Link { path: ref p, .. }) => p.as_path(),
        }
    }

    pub fn dir(path: PathBuf) -> Stat {
        Stat::Dir(Dir(path))
    }

    pub fn file(path: PathBuf, is_executable: bool) -> Stat {
        Stat::File(File {
            path,
            is_executable,
        })
    }

    pub fn link(path: PathBuf, target: PathBuf) -> Stat {
        Stat::Link(Link { path, target })
    }

    pub fn within(&self, directory: &Path) -> Stat {
        match self {
            Stat::Dir(Dir(p)) => Stat::Dir(Dir(directory.join(p))),
            Stat::File(File {
                path,
                is_executable,
            }) => Stat::File(File {
                path: directory.join(path),
                is_executable: *is_executable,
            }),
            Stat::Link(Link { path, target }) => Stat::Link(Link {
                path: directory.join(path),
                target: target.to_owned(),
            }),
        }
    }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Link {
    pub path: PathBuf,
    pub target: PathBuf,
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Dir(pub PathBuf);

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct File {
    pub path: PathBuf,
    pub is_executable: bool,
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub enum PathStat {
    Dir {
        // The symbolic name of some filesystem Path, which is context specific.
        path: PathBuf,
        // The canonical Stat that underlies the Path.
        stat: Dir,
    },
    File {
        // The symbolic name of some filesystem Path, which is context specific.
        path: PathBuf,
        // The canonical Stat that underlies the Path.
        stat: File,
    },
    Link {
        // The symbolic name of some filesystem Path, which is context specific.
        path: PathBuf,
        // The canonical Stat that underlies the Path.
        stat: Link,
    },
}

impl PathStat {
    pub fn dir(path: PathBuf, stat: Dir) -> PathStat {
        PathStat::Dir { path, stat }
    }

    pub fn file(path: PathBuf, stat: File) -> PathStat {
        PathStat::File { path, stat }
    }

    pub fn link(path: PathBuf, stat: Link) -> PathStat {
        PathStat::Link { path, stat }
    }

    pub fn path(&self) -> &Path {
        match self {
            PathStat::Dir { path, .. } => path.as_path(),
            PathStat::File { path, .. } => path.as_path(),
            PathStat::Link { path, .. } => path.as_path(),
        }
    }
}

/// The kind of path (e.g., file, directory, symlink) as identified in `PathMetadata`
#[pyclass(rename_all = "UPPERCASE")]
#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub enum PathMetadataKind {
    File,
    Directory,
    Symlink,
}

/// Expanded version of `Stat` when access to additional filesystem attributes is necessary.
#[pyclass]
#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub struct PathMetadata {
    /// Path to this filesystem entry.
    #[pyo3(get)]
    path: PathBuf,

    /// The kind of file at the path.
    #[pyo3(get)]
    kind: PathMetadataKind,

    /// Length of the filesystem entry.
    #[pyo3(get)]
    length: u64,

    /// True if the entry is marked executable.
    #[pyo3(get)]
    is_executable: bool,

    /// True if the entry is marked read-only.
    #[pyo3(get)]
    read_only: bool,

    /// UNIX mode (if available)
    #[pyo3(get)]
    unix_mode: Option<u32>,

    /// Modification time of the path (if available).
    #[pyo3(get)]
    accessed_time: Option<SystemTime>,

    /// Modification time of the path (if available).
    #[pyo3(get)]
    created_time: Option<SystemTime>,

    /// Modification time of the path (if available).
    #[pyo3(get)]
    modification_time: Option<SystemTime>,

    /// Symlink target
    #[pyo3(get)]
    symlink_target: Option<PathBuf>,
}

impl PathMetadata {
    pub fn new(
        path: PathBuf,
        kind: PathMetadataKind,
        length: u64,
        is_executable: bool,
        read_only: bool,
        unix_mode: Option<u32>,
        accessed_time: Option<SystemTime>,
        created_time: Option<SystemTime>,
        modification_time: Option<SystemTime>,
        symlink_target: Option<PathBuf>,
    ) -> Self {
        Self {
            path,
            kind,
            length,
            is_executable,
            read_only,
            unix_mode,
            accessed_time,
            created_time,
            modification_time,
            symlink_target,
        }
    }
}

#[pymethods]
impl PathMetadata {
    fn __repr__(&self) -> String {
        format!("{:?}", self)
    }
}

#[derive(Debug, DeepSizeOf, Eq, PartialEq)]
pub struct DirectoryListing(pub Vec<Stat>);

#[derive(Debug, DeepSizeOf, Clone, Eq, Hash, PartialEq)]
pub enum StrictGlobMatching {
    // NB: the Error and Warn variants store a description of the origin of the PathGlob
    // request so that we can make the error message more helpful to users when globs fail to match.
    Error(String),
    Warn(String),
    Ignore,
}

impl StrictGlobMatching {
    pub fn create(behavior: &str, description_of_origin: Option<String>) -> Result<Self, String> {
        match (behavior, description_of_origin) {
      ("ignore", None) => Ok(StrictGlobMatching::Ignore),
      ("warn", Some(origin)) => Ok(StrictGlobMatching::Warn(origin)),
      ("error", Some(origin)) => Ok(StrictGlobMatching::Error(origin)),
      ("ignore", Some(_)) => {
        Err("Provided description_of_origin while ignoring glob match errors".to_string())
      }
      ("warn", None) | ("error", None) => Err(
        "Must provide a description_of_origin when warning or erroring on glob match errors"
          .to_string(),
      ),
      _ => Err(format!(
        "Unrecognized strict glob matching behavior: {behavior}.",
      )),
    }
    }

    pub fn should_check_glob_matches(&self) -> bool {
        !matches!(self, &StrictGlobMatching::Ignore)
    }

    pub fn should_throw_on_error(&self) -> bool {
        matches!(self, &StrictGlobMatching::Error(_))
    }
}

#[derive(Debug, DeepSizeOf, Clone, Eq, Hash, PartialEq)]
pub enum GlobExpansionConjunction {
    AllMatch,
    AnyMatch,
}

impl GlobExpansionConjunction {
    pub fn create(spec: &str) -> Result<Self, String> {
        match spec {
            "all_match" => Ok(GlobExpansionConjunction::AllMatch),
            "any_match" => Ok(GlobExpansionConjunction::AnyMatch),
            _ => Err(format!("Unrecognized conjunction: {spec}.")),
        }
    }
}

#[derive(Debug, DeepSizeOf, Clone, Eq, PartialEq, Hash)]
pub struct PathGlobs {
    globs: Vec<String>,
    strict_match_behavior: StrictGlobMatching,
    conjunction: GlobExpansionConjunction,
}

impl PathGlobs {
    pub fn new(
        globs: Vec<String>,
        strict_match_behavior: StrictGlobMatching,
        conjunction: GlobExpansionConjunction,
    ) -> PathGlobs {
        PathGlobs {
            globs,
            strict_match_behavior,
            conjunction,
        }
    }

    pub fn parse(self) -> Result<glob_matching::PreparedPathGlobs, String> {
        glob_matching::PreparedPathGlobs::create(
            self.globs,
            self.strict_match_behavior,
            self.conjunction,
        )
    }
}

impl fmt::Display for PathGlobs {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.globs.join(", "))
    }
}

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

    pub async fn scandir(&self, dir_relative_to_root: Dir) -> Result<DirectoryListing, io::Error> {
        let vfs = self.clone();
        self.executor
            .spawn_blocking(
                move || vfs.scandir_sync(&dir_relative_to_root),
                |e| {
                    Err(io::Error::new(
                        io::ErrorKind::Other,
                        format!("Synchronous scandir failed: {e}"),
                    ))
                },
            )
            .await
    }

    fn scandir_sync(&self, dir_relative_to_root: &Dir) -> Result<DirectoryListing, io::Error> {
        let dir_abs = self.root.0.join(&dir_relative_to_root.0);
        let mut stats: Vec<Stat> = dir_abs
            .read_dir()?
            .map(|readdir| {
                let dir_entry = readdir?;
                let (file_type, compute_metadata): (_, Box<dyn FnOnce() -> Result<_, _>>) =
                    match self.symlink_behavior {
                        SymlinkBehavior::Aware => {
                            // Use the dir_entry metadata, which is symlink aware.
                            (dir_entry.file_type()?, Box::new(|| dir_entry.metadata()))
                        }
                        SymlinkBehavior::Oblivious => {
                            // Use an independent stat call to get metadata, which is symlink oblivious.
                            let metadata = std::fs::metadata(dir_abs.join(dir_entry.file_name()))?;
                            (metadata.file_type(), Box::new(|| Ok(metadata)))
                        }
                    };
                PosixFS::stat_internal(
                    &dir_abs.join(dir_entry.file_name()),
                    file_type,
                    compute_metadata,
                )
            })
            .filter_map(|s| match s {
                Ok(Some(s))
                    if !self.ignore.is_ignored_path(
                        &dir_relative_to_root.0.join(s.path()),
                        matches!(s, Stat::Dir(_)),
                    ) =>
                {
                    // It would be nice to be able to ignore paths before stat'ing them, but in order to apply
                    // git-style ignore patterns, we need to know whether a path represents a directory.
                    Some(Ok(s))
                }
                Ok(_) => None,
                Err(e) => Some(Err(e)),
            })
            .collect::<Result<Vec<_>, io::Error>>()
            .map_err(|e| {
                io::Error::new(
                    e.kind(),
                    format!("Failed to scan directory {dir_abs:?}: {e}"),
                )
            })?;
        stats.sort_by(|s1, s2| s1.path().cmp(s2.path()));
        Ok(DirectoryListing(stats))
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

    pub async fn path_metadata(&self, path: PathBuf) -> Result<Option<PathMetadata>, io::Error> {
        let abs_path = self.root.0.join(&path);
        match tokio::fs::symlink_metadata(&abs_path).await {
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

                Ok(Some(PathMetadata::new(
                    path,
                    kind,
                    metadata.len(),
                    is_executable,
                    metadata.permissions().readonly(),
                    unix_mode,
                    metadata.accessed().ok(),
                    metadata.created().ok(),
                    metadata.modified().ok(),
                    symlink_target,
                )))
            }
            Err(err) if err.kind() == ErrorKind::NotFound => Ok(None),
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

    async fn path_metadata(&self, path: PathBuf) -> Result<Option<PathMetadata>, io::Error> {
        PosixFS::path_metadata(self, path).await
    }

    fn is_ignored(&self, stat: &Stat) -> bool {
        PosixFS::is_ignored(self, stat)
    }

    fn mk_error(msg: &str) -> io::Error {
        io::Error::new(io::ErrorKind::Other, msg)
    }
}

#[async_trait]
impl Vfs<String> for DigestTrie {
    async fn read_link(&self, link: &Link) -> Result<PathBuf, String> {
        let entry = self
            .entry(&link.path)?
            .ok_or_else(|| format!("{link:?} does not exist within this Snapshot."))?;
        let target = match entry {
            directory::Entry::File(_) => {
                return Err(format!(
                    "Path `{}` was a file rather than a symlink.",
                    link.path.display()
                ))
            }
            directory::Entry::Symlink(s) => s.target(),
            directory::Entry::Directory(_) => {
                return Err(format!(
                    "Path `{}` was a directory rather than a symlink.",
                    link.path.display()
                ))
            }
        };
        Ok(target.to_path_buf())
    }

    async fn scandir(&self, dir: Dir) -> Result<Arc<DirectoryListing>, String> {
        // TODO(#14890): Change interface to take a reference to an Entry. That would avoid both the
        // need to handle this root case, and the need to recurse in `entry` down into children.
        let entries = if dir.0.components().next().is_none() {
            self.entries()
        } else {
            let entry = self
                .entry(&dir.0)?
                .ok_or_else(|| format!("{dir:?} does not exist within this Snapshot."))?;
            match entry {
                directory::Entry::File(_) => {
                    return Err(format!(
                        "Path `{}` was a file rather than a directory.",
                        dir.0.display()
                    ))
                }
                directory::Entry::Symlink(_) => {
                    return Err(format!(
                        "Path `{}` was a symlink rather than a directory.",
                        dir.0.display()
                    ))
                }
                directory::Entry::Directory(d) => d.tree().entries(),
            }
        };

        Ok(Arc::new(DirectoryListing(
            entries
                .iter()
                .map(|child| match child {
                    directory::Entry::File(f) => Stat::File(File {
                        path: f.name().as_ref().into(),
                        is_executable: f.is_executable(),
                    }),
                    directory::Entry::Symlink(s) => Stat::Link(Link {
                        path: s.name().as_ref().into(),
                        target: s.target().to_path_buf(),
                    }),
                    directory::Entry::Directory(d) => Stat::Dir(Dir(d.name().as_ref().into())),
                })
                .collect(),
        )))
    }

    async fn path_metadata(&self, path: PathBuf) -> Result<Option<PathMetadata>, String> {
        let entry = match self.entry(&path)? {
            Some(e) => e,
            None => return Ok(None),
        };

        Ok(Some(match entry {
            directory::Entry::File(f) => PathMetadata::new(
                path,
                PathMetadataKind::File,
                entry.digest().size_bytes as u64,
                f.is_executable(),
                false,
                None,
                None,
                None,
                None,
                None,
            ),
            directory::Entry::Symlink(s) => PathMetadata::new(
                path,
                PathMetadataKind::Symlink,
                0,
                false,
                false,
                None,
                None,
                None,
                None,
                Some(s.target().to_path_buf()),
            ),
            directory::Entry::Directory(_) => PathMetadata::new(
                path,
                PathMetadataKind::Directory,
                entry.digest().size_bytes as u64,
                false,
                false,
                None,
                None,
                None,
                None,
                None,
            ),
        }))
    }

    fn is_ignored(&self, _stat: &Stat) -> bool {
        false
    }

    fn mk_error(msg: &str) -> String {
        msg.to_owned()
    }
}

///
/// A context for filesystem operations parameterized on an error type 'E'.
///
#[async_trait]
pub trait Vfs<E: Send + Sync + 'static>: Clone + Send + Sync + 'static {
    async fn read_link(&self, link: &Link) -> Result<PathBuf, E>;
    async fn scandir(&self, dir: Dir) -> Result<Arc<DirectoryListing>, E>;
    async fn path_metadata(&self, path: PathBuf) -> Result<Option<PathMetadata>, E>;
    fn is_ignored(&self, stat: &Stat) -> bool;
    fn mk_error(msg: &str) -> E;
}

pub struct FileContent {
    pub path: PathBuf,
    pub content: Bytes,
    pub is_executable: bool,
}

impl fmt::Debug for FileContent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let len = min(self.content.len(), 5);
        let describer = if len < self.content.len() {
            "starting "
        } else {
            ""
        };
        write!(
            f,
            "FileContent(path={:?}, content={} bytes {}{:?})",
            self.path,
            self.content.len(),
            describer,
            &self.content[..len]
        )
    }
}

#[derive(Debug, Eq, PartialEq)]
pub struct FileEntry {
    pub path: PathBuf,
    pub digest: hashing::Digest,
    pub is_executable: bool,
}

#[derive(Debug, Eq, PartialEq)]
pub struct SymlinkEntry {
    pub path: PathBuf,
    pub target: PathBuf,
}

#[derive(Debug, Eq, PartialEq)]
pub enum DigestEntry {
    File(FileEntry),
    Symlink(SymlinkEntry),
    EmptyDirectory(PathBuf),
}

impl DigestEntry {
    pub fn path(&self) -> &Path {
        match self {
            DigestEntry::File(file_entry) => &file_entry.path,
            DigestEntry::Symlink(symlink_entry) => &symlink_entry.path,
            DigestEntry::EmptyDirectory(path) => path,
        }
    }
}

///
/// Increase file handle limits as much as the OS will allow us to, returning an error if we are
/// unable to either get or sufficiently raise them. Generally the returned error should be treated
/// as a warning to be rendered rather than as something fatal.
///
pub fn increase_limits() -> Result<String, String> {
    loop {
        let (cur, max) = rlimit::Resource::NOFILE
            .get()
            .map_err(|e| format!("Could not validate file handle limits: {e}"))?;
        // If the limit is less than our target.
        if cur < TARGET_NOFILE_LIMIT {
            let err_suffix = format!(
        "To avoid 'too many open file handle' errors, we recommend a limit of at least {TARGET_NOFILE_LIMIT}: \
        please see https://www.pantsbuild.org/docs/troubleshooting#too-many-open-files-error \
        for more information."
      );
            // If we might be able to increase the soft limit, try to.
            if cur < max {
                let target_soft_limit = std::cmp::min(max, TARGET_NOFILE_LIMIT);
                rlimit::Resource::NOFILE
          .set(target_soft_limit, max)
          .map_err(|e| {
            format!("Could not raise soft file handle limit above {cur}: `{e}`. {err_suffix}")
          })?;
            } else {
                return Err(format!(
                    "File handle limit is capped to: {cur}. {err_suffix}"
                ));
            }
        } else {
            return Ok(format!("File handle limit is: {cur}"));
        };
    }
}

#[cfg(test)]
mod tests;
