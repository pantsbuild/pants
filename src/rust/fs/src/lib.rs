// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

pub mod directory;
#[cfg(test)]
mod directory_tests;
pub mod gitignore;
mod glob_matching;
#[cfg(test)]
mod glob_matching_tests;
#[cfg(unix)]
mod posixfs;
#[cfg(test)]
mod posixfs_tests;
#[cfg(test)]
mod testutil;

use std::cmp::min;
use std::fmt;
use std::ops::Deref;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use std::time::SystemTime;

use async_trait::async_trait;
use bytes::Bytes;
use deepsize::DeepSizeOf;
use serde::Serialize;

pub use crate::directory::{
    DigestTrie, DirectoryDigest, EMPTY_DIGEST_TREE, EMPTY_DIRECTORY_DIGEST, Entry, SymlinkBehavior,
    TypedPath,
};
pub use crate::gitignore::GitignoreStyleExcludes;
pub use crate::glob_matching::{
    DOUBLE_STAR_GLOB, FilespecMatcher, GlobMatching, PathGlob, PreparedPathGlobs, SINGLE_STAR_GLOB,
};
#[cfg(unix)]
use crate::posixfs::PosixFS;

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
                    return Err(format!("Windows paths are not allowed: {candidate:?}"));
                }
                Component::RootDir => {
                    return Err(format!("Absolute paths are not allowed: {candidate:?}"));
                }
                Component::CurDir => (),
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
#[derive(Clone, Copy, Debug, DeepSizeOf, Eq, PartialEq)]
pub enum PathMetadataKind {
    File,
    Directory,
    Symlink,
}

/// Expanded version of `Stat` when access to additional filesystem attributes is necessary.
#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub struct PathMetadata {
    /// Path to this filesystem entry.
    pub path: PathBuf,

    /// The kind of file at the path.
    pub kind: PathMetadataKind,

    /// Length of the filesystem entry.
    pub length: u64,

    /// True if the entry is marked executable.
    pub is_executable: bool,

    /// UNIX mode (if available)
    pub unix_mode: Option<u32>,

    /// Modification time of the path (if available).
    pub accessed: Option<SystemTime>,

    /// Modification time of the path (if available).
    pub created: Option<SystemTime>,

    /// Modification time of the path (if available).
    pub modified: Option<SystemTime>,

    /// Symlink target
    pub symlink_target: Option<PathBuf>,
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

#[cfg(unix)]
pub type FS = PosixFS;

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
                ));
            }
            directory::Entry::Symlink(s) => s.target(),
            directory::Entry::Directory(_) => {
                return Err(format!(
                    "Path `{}` was a directory rather than a symlink.",
                    link.path.display()
                ));
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
                    ));
                }
                directory::Entry::Symlink(_) => {
                    return Err(format!(
                        "Path `{}` was a symlink rather than a directory.",
                        dir.0.display()
                    ));
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
            directory::Entry::File(f) => PathMetadata {
                path,
                kind: PathMetadataKind::File,
                length: entry.digest().size_bytes as u64,
                is_executable: f.is_executable(),
                unix_mode: None,
                accessed: None,
                created: None,
                modified: None,
                symlink_target: None,
            },
            directory::Entry::Symlink(s) => PathMetadata {
                path,
                kind: PathMetadataKind::Symlink,
                length: 0,
                is_executable: false,
                unix_mode: None,
                accessed: None,
                created: None,
                modified: None,
                symlink_target: Some(s.target().to_path_buf()),
            },
            directory::Entry::Directory(_) => PathMetadata {
                path,
                kind: PathMetadataKind::Directory,
                length: entry.digest().size_bytes as u64,
                is_executable: false,
                unix_mode: None,
                accessed: None,
                created: None,
                modified: None,
                symlink_target: None,
            },
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
