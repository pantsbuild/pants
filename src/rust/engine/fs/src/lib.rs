// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
    clippy::all,
    clippy::default_trait_access,
    clippy::expl_impl_clone_on_copy,
    clippy::if_not_else,
    clippy::needless_continue,
    clippy::unseparated_literal_suffix,
    clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
    clippy::len_without_is_empty,
    clippy::redundant_field_names,
    clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

pub mod directory;
mod glob_matching;
#[cfg(test)]
mod glob_matching_tests;
#[cfg(test)]
mod posixfs_tests;

pub use crate::directory::{
    DigestTrie, DirectoryDigest, TypedPath, EMPTY_DIGEST_TREE, EMPTY_DIRECTORY_DIGEST,
};
pub use crate::glob_matching::{
    FilespecMatcher, GlobMatching, PathGlob, PreparedPathGlobs, DOUBLE_STAR_GLOB, SINGLE_STAR_GLOB,
};

use std::cmp::min;
use std::io;
use std::ops::Deref;
use std::os::unix::fs::PermissionsExt;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use std::{fmt, fs};

use crate::future::FutureExt;
use ::ignore::gitignore::{Gitignore, GitignoreBuilder};
use async_trait::async_trait;
use bytes::Bytes;
use deepsize::DeepSizeOf;
use futures::future::{self, BoxFuture, TryFutureExt};
use lazy_static::lazy_static;
use serde::Serialize;

lazy_static! {
    static ref EMPTY_IGNORE: Arc<GitignoreStyleExcludes> = Arc::new(GitignoreStyleExcludes {
        patterns: vec![],
        gitignore: Gitignore::empty(),
    });
}

const TARGET_NOFILE_LIMIT: u64 = 10000;

const XDG_CACHE_HOME: &str = "XDG_CACHE_HOME";

/// Follows the unix XDB base spec: http://standards.freedesktop.org/basedir-spec/latest/index.html.
pub fn default_cache_path() -> PathBuf {
    let cache_path = std::env::var(XDG_CACHE_HOME)
        .ok()
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .or_else(|| dirs_next::home_dir().map(|home| home.join(".cache")))
        .unwrap_or_else(|| panic!("Could not find home dir or {}.", XDG_CACHE_HOME));
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
                    return Err(format!("Windows paths are not allowed: {:?}", candidate))
                }
                Component::RootDir => {
                    return Err(format!("Absolute paths are not allowed: {:?}", candidate))
                }
                Component::CurDir => continue,
                Component::ParentDir => {
                    if !relative_path.pop() {
                        return Err(format!(
                            "Relative paths that escape the root are not allowed: {:?}",
                            candidate
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
            &Stat::Link(Link(ref p)) => p.as_path(),
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
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Link(pub PathBuf);

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
}

impl PathStat {
    pub fn dir(path: PathBuf, stat: Dir) -> PathStat {
        PathStat::Dir { path, stat }
    }

    pub fn file(path: PathBuf, stat: File) -> PathStat {
        PathStat::File { path, stat }
    }

    pub fn path(&self) -> &Path {
        match self {
            &PathStat::Dir { ref path, .. } => path.as_path(),
            &PathStat::File { ref path, .. } => path.as_path(),
        }
    }
}

#[derive(Debug, DeepSizeOf, Eq, PartialEq)]
pub struct DirectoryListing(pub Vec<Stat>);

#[derive(Debug)]
pub struct GitignoreStyleExcludes {
    patterns: Vec<String>,
    gitignore: Gitignore,
}

impl GitignoreStyleExcludes {
    pub fn create(patterns: Vec<String>) -> Result<Arc<Self>, String> {
        Self::create_with_gitignore_file(patterns, None)
    }

    pub fn empty() -> Arc<Self> {
        EMPTY_IGNORE.clone()
    }

    pub fn create_with_gitignore_file(
        patterns: Vec<String>,
        gitignore_path: Option<PathBuf>,
    ) -> Result<Arc<Self>, String> {
        if patterns.is_empty() && gitignore_path.is_none() {
            return Ok(EMPTY_IGNORE.clone());
        }

        let mut ignore_builder = GitignoreBuilder::new("");

        if let Some(path) = gitignore_path {
            if let Some(err) = ignore_builder.add(path) {
                return Err(format!("Error adding .gitignore path: {:?}", err));
            }
        }
        for pattern in &patterns {
            ignore_builder.add_line(None, pattern).map_err(|e| {
                format!(
                    "Could not parse glob exclude pattern `{:?}`: {:?}",
                    pattern, e
                )
            })?;
        }

        let gitignore = ignore_builder
            .build()
            .map_err(|e| format!("Could not build ignore patterns: {:?}", e))?;

        Ok(Arc::new(Self {
            patterns: patterns,
            gitignore,
        }))
    }

    fn exclude_patterns(&self) -> &[String] {
        self.patterns.as_slice()
    }

    fn is_ignored(&self, stat: &Stat) -> bool {
        let is_dir = matches!(stat, &Stat::Dir(_));
        self.is_ignored_path(stat.path(), is_dir)
    }

    pub fn is_ignored_path(&self, path: &Path, is_dir: bool) -> bool {
        match self.gitignore.matched(path, is_dir) {
            ::ignore::Match::None | ::ignore::Match::Whitelist(_) => false,
            ::ignore::Match::Ignore(_) => true,
        }
    }

    pub fn is_ignored_or_child_of_ignored_path(&self, path: &Path, is_dir: bool) -> bool {
        match self.gitignore.matched_path_or_any_parents(path, is_dir) {
            ::ignore::Match::None | ::ignore::Match::Whitelist(_) => false,
            ::ignore::Match::Ignore(_) => true,
        }
    }
}

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
        "Unrecognized strict glob matching behavior: {}.",
        behavior,
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
            _ => Err(format!("Unrecognized conjunction: {}.", spec)),
        }
    }
}

#[derive(Clone)]
pub enum SymlinkBehavior {
    Aware,
    Oblivious,
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
            .map_err(|e| format!("Could not canonicalize root {:?}: {:?}", root, e))?;

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
            .spawn_blocking(move || vfs.scandir_sync(&dir_relative_to_root))
            .await
    }

    fn scandir_sync(&self, dir_relative_to_root: &Dir) -> Result<DirectoryListing, io::Error> {
        let dir_abs = self.root.0.join(&dir_relative_to_root.0);
        let root = self.root.0.clone();
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
                    &root,
                    dir_relative_to_root.0.join(dir_entry.file_name()),
                    file_type,
                    compute_metadata,
                )
            })
            .filter_map(|s| match s {
                Ok(Some(s)) if !self.ignore.is_ignored(&s) => {
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
                    format!("Failed to scan directory {:?}: {}", dir_abs, e),
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
        let link_parent = link.0.parent().map(Path::to_owned);
        let link_abs = self.root.0.join(link.0.as_path());
        self.executor
            .spawn_blocking(move || {
                link_abs
                    .read_link()
                    .and_then(|path_buf| {
                        if path_buf.is_absolute() {
                            Err(io::Error::new(
                                io::ErrorKind::InvalidData,
                                format!("Absolute symlink: {:?}", path_buf),
                            ))
                        } else {
                            link_parent
                                .map(|parent| parent.join(&path_buf))
                                .ok_or_else(|| {
                                    io::Error::new(
                                        io::ErrorKind::InvalidData,
                                        format!("Symlink without a parent?: {:?}", path_buf),
                                    )
                                })
                        }
                    })
                    .map_err(|e| {
                        io::Error::new(
                            e.kind(),
                            format!("Failed to read link {:?}: {}", link_abs, e),
                        )
                    })
            })
            .await
    }

    ///
    /// Makes a Stat for path_for_stat relative to absolute_path_to_root.
    ///
    /// This method takes both a `FileType` and a getter for `Metadata` because on Unixes,
    /// directory walks cheaply return the `FileType` without extra syscalls, but other
    /// metadata requires additional syscall(s) to compute. We can avoid those calls for
    /// Dirs and Links.
    ///
    fn stat_internal<F>(
        absolute_path_to_root: &Path,
        path_for_stat: PathBuf,
        file_type: std::fs::FileType,
        compute_metadata: F,
    ) -> Result<Option<Stat>, io::Error>
    where
        F: FnOnce() -> Result<std::fs::Metadata, io::Error>,
    {
        if !path_for_stat.is_relative() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "Argument path_for_stat to PosixFS::stat must be relative path, got {:?}",
                    path_for_stat
                ),
            ));
        }
        // TODO: Make this an instance method, and stop having to check this every call.
        if !absolute_path_to_root.is_absolute() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
          "Argument absolute_path_to_root to PosixFS::stat must be absolute path, got {:?}",
          absolute_path_to_root
        ),
            ));
        }
        if file_type.is_symlink() {
            Ok(Some(Stat::Link(Link(path_for_stat))))
        } else if file_type.is_file() {
            let is_executable = compute_metadata()?.permissions().mode() & 0o100 == 0o100;
            Ok(Some(Stat::File(File {
                path: path_for_stat,
                is_executable: is_executable,
            })))
        } else if file_type.is_dir() {
            Ok(Some(Stat::Dir(Dir(path_for_stat))))
        } else {
            Ok(None)
        }
    }

    pub fn stat_sync(&self, relative_path: PathBuf) -> Result<Option<Stat>, io::Error> {
        let abs_path = self.root.0.join(&relative_path);
        let metadata = match self.symlink_behavior {
            SymlinkBehavior::Aware => fs::symlink_metadata(abs_path),
            SymlinkBehavior::Oblivious => fs::metadata(abs_path),
        };
        metadata
            .and_then(|metadata| {
                PosixFS::stat_internal(&self.root.0, relative_path, metadata.file_type(), || {
                    Ok(metadata)
                })
            })
            .or_else(|err| match err.kind() {
                io::ErrorKind::NotFound => Ok(None),
                _ => Err(err),
            })
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
        // DigestTrie does not currently support Links.
        Err(format!("{:?} does not exist within this Snapshot.", link))
    }

    async fn scandir(&self, dir: Dir) -> Result<Arc<DirectoryListing>, String> {
        // TODO(#14890): Change interface to take a reference to an Entry, and to avoid absolute paths.
        // That would avoid both the need to handle this root case, and the need to recurse in `entry`
        // down into children.
        let directory = if dir.0.components().next().is_none() {
            directory::Directory::new(directory::Name::new(""), self.entries().into())
        } else {
            let entry = self
                .entry(&dir.0)?
                .ok_or_else(|| format!("{:?} does not exist within this Snapshot.", dir))?;
            match entry {
                directory::Entry::File(_) => {
                    return Err(format!(
                        "Path `{}` was a file rather than a directory.",
                        dir.0.display()
                    ))
                }
                directory::Entry::Directory(d) => d.clone(),
            }
        };

        Ok(Arc::new(DirectoryListing(
            directory
                .tree()
                .entries()
                .iter()
                .map(|child| match child {
                    directory::Entry::File(f) => Stat::File(File {
                        path: dir.0.join(f.name().as_ref()),
                        is_executable: f.is_executable(),
                    }),
                    directory::Entry::Directory(d) => Stat::Dir(Dir(dir.0.join(d.name().as_ref()))),
                })
                .collect(),
        )))
    }

    fn is_ignored(&self, _stat: &Stat) -> bool {
        false
    }

    fn mk_error(msg: &str) -> String {
        msg.to_owned()
    }
}

pub trait PathStatGetter<E> {
    fn path_stats(&self, paths: Vec<PathBuf>) -> BoxFuture<Result<Vec<Option<PathStat>>, E>>;
}

impl PathStatGetter<io::Error> for Arc<PosixFS> {
    fn path_stats(
        &self,
        paths: Vec<PathBuf>,
    ) -> BoxFuture<Result<Vec<Option<PathStat>>, io::Error>> {
        async move {
            future::try_join_all(
                paths
                    .into_iter()
                    .map(|path| {
                        let fs = self.clone();
                        let fs2 = self.clone();
                        self.executor
                            .spawn_blocking(move || fs2.stat_sync(path))
                            .and_then(move |maybe_stat| {
                                async move {
                                    match maybe_stat {
                                        // Note: This will drop PathStats for symlinks which don't point anywhere.
                                        Some(Stat::Link(link)) => {
                                            fs.canonicalize_link(link.0.clone(), link).await
                                        }
                                        Some(Stat::Dir(dir)) => {
                                            Ok(Some(PathStat::dir(dir.0.clone(), dir)))
                                        }
                                        Some(Stat::File(file)) => {
                                            Ok(Some(PathStat::file(file.path.clone(), file)))
                                        }
                                        None => Ok(None),
                                    }
                                }
                            })
                    })
                    .collect::<Vec<_>>(),
            )
            .await
        }
        .boxed()
    }
}

///
/// A context for filesystem operations parameterized on an error type 'E'.
///
#[async_trait]
pub trait Vfs<E: Send + Sync + 'static>: Clone + Send + Sync + 'static {
    async fn read_link(&self, link: &Link) -> Result<PathBuf, E>;
    async fn scandir(&self, dir: Dir) -> Result<Arc<DirectoryListing>, E>;
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
pub enum DigestEntry {
    File(FileEntry),
    EmptyDirectory(PathBuf),
}

impl DigestEntry {
    pub fn path(&self) -> &Path {
        match self {
            DigestEntry::File(file_entry) => &file_entry.path,
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
            .map_err(|e| format!("Could not validate file handle limits: {}", e))?;
        // If the limit is less than our target.
        if cur < TARGET_NOFILE_LIMIT {
            let err_suffix = format!(
        "To avoid 'too many open file handle' errors, we recommend a limit of at least {}: \
        please see https://www.pantsbuild.org/docs/troubleshooting#too-many-open-files-error \
        for more information.",
        TARGET_NOFILE_LIMIT
      );
            // If we might be able to increase the soft limit, try to.
            if cur < max {
                let target_soft_limit = std::cmp::min(max, TARGET_NOFILE_LIMIT);
                rlimit::Resource::NOFILE
                    .set(target_soft_limit, max)
                    .map_err(|e| {
                        format!(
                            "Could not raise soft file handle limit above {}: `{}`. {}",
                            cur, e, err_suffix
                        )
                    })?;
            } else {
                return Err(format!(
                    "File handle limit is capped to: {}. {}",
                    cur, err_suffix
                ));
            }
        } else {
            return Ok(format!("File handle limit is: {}", cur));
        };
    }
}

///
/// Like std::fs::create_dir_all, except handles concurrent calls among multiple
/// threads or processes. Originally lifted from rustc.
///
pub fn safe_create_dir_all_ioerror(path: &Path) -> Result<(), io::Error> {
    match fs::create_dir(path) {
        Ok(()) => return Ok(()),
        Err(ref e) if e.kind() == io::ErrorKind::AlreadyExists => return Ok(()),
        Err(ref e) if e.kind() == io::ErrorKind::NotFound => {}
        Err(e) => return Err(e),
    }
    match path.parent() {
        Some(p) => safe_create_dir_all_ioerror(p)?,
        None => return Ok(()),
    }
    match fs::create_dir(path) {
        Ok(()) => Ok(()),
        Err(ref e) if e.kind() == io::ErrorKind::AlreadyExists => Ok(()),
        Err(e) => Err(e),
    }
}

pub fn safe_create_dir_all(path: &Path) -> Result<(), String> {
    safe_create_dir_all_ioerror(path)
        .map_err(|e| format!("Failed to create dir {:?} due to {:?}", path, e))
}

pub fn safe_create_dir(path: &Path) -> Result<(), String> {
    match fs::create_dir(path) {
        Ok(()) => Ok(()),
        Err(ref e) if e.kind() == io::ErrorKind::AlreadyExists => Ok(()),
        Err(err) => Err(format!("{}", err)),
    }
}

#[cfg(test)]
mod tests;
