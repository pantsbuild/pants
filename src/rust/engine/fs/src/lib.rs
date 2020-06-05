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
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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

mod glob_matching;
#[cfg(test)]
mod glob_matching_tests;
#[cfg(test)]
mod posixfs_tests;

pub use crate::glob_matching::{GlobMatching, PreparedPathGlobs};

use std::cmp::min;
use std::io::{self, Read};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::{fmt, fs};

use ::ignore::gitignore::{Gitignore, GitignoreBuilder};
use async_trait::async_trait;
use bytes::Bytes;
use futures::future::{self, TryFutureExt};
use lazy_static::lazy_static;

lazy_static! {
  static ref EMPTY_IGNORE: Arc<GitignoreStyleExcludes> = Arc::new(GitignoreStyleExcludes {
    patterns: vec![],
    gitignore: Gitignore::empty(),
  });
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
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

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Link(pub PathBuf);

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Dir(pub PathBuf);

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct File {
  pub path: PathBuf,
  pub is_executable: bool,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
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
    PathStat::Dir {
      path: path,
      stat: stat,
    }
  }

  pub fn file(path: PathBuf, stat: File) -> PathStat {
    PathStat::File {
      path: path,
      stat: stat,
    }
  }

  pub fn path(&self) -> &Path {
    match self {
      &PathStat::Dir { ref path, .. } => path.as_path(),
      &PathStat::File { ref path, .. } => path.as_path(),
    }
  }
}

#[derive(Debug, Eq, PartialEq)]
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
    let is_dir = match stat {
      &Stat::Dir(_) => true,
      _ => false,
    };
    self.is_ignored_path(stat.path(), is_dir)
  }

  fn is_ignored_path(&self, path: &Path, is_dir: bool) -> bool {
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

#[derive(Debug)]
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
    match self {
      &StrictGlobMatching::Ignore => false,
      _ => true,
    }
  }

  pub fn should_throw_on_error(&self) -> bool {
    match self {
      &StrictGlobMatching::Error(_) => true,
      _ => false,
    }
  }
}

#[derive(Debug)]
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

#[derive(Debug)]
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
    self
      .executor
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
      .filter(|s| match s {
        Ok(ref s) =>
        // It would be nice to be able to ignore paths before stat'ing them, but in order to apply
        // git-style ignore patterns, we need to know whether a path represents a directory.
        {
          !self.ignore.is_ignored(s)
        }
        Err(_) => true,
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

  pub async fn read_file(&self, file: &File) -> Result<FileContent, io::Error> {
    let path = file.path.clone();
    let path_abs = self.root.0.join(&file.path);
    self
      .executor
      .spawn_blocking(move || {
        let is_executable = path_abs.metadata()?.permissions().mode() & 0o100 == 0o100;
        std::fs::File::open(&path_abs)
          .and_then(|mut f| {
            let mut content = Vec::new();
            f.read_to_end(&mut content)?;
            Ok(FileContent {
              path: path,
              content: Bytes::from(content),
              is_executable,
            })
          })
          .map_err(|e| {
            io::Error::new(
              e.kind(),
              format!("Failed to read file {:?}: {}", path_abs, e),
            )
          })
      })
      .await
  }

  pub async fn read_link(&self, link: &Link) -> Result<PathBuf, io::Error> {
    let link_parent = link.0.parent().map(Path::to_owned);
    let link_abs = self.root.0.join(link.0.as_path());
    self
      .executor
      .spawn_blocking(move || {
        link_abs
          .read_link()
          .and_then(|path_buf| {
            if path_buf.is_absolute() {
              Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("Absolute symlink: {:?}", link_abs),
              ))
            } else {
              link_parent
                .map(|parent| parent.join(path_buf))
                .ok_or_else(|| {
                  io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("Symlink without a parent?: {:?}", link_abs),
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
  ) -> Result<Stat, io::Error>
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
      Ok(Stat::Link(Link(path_for_stat)))
    } else if file_type.is_file() {
      let is_executable = compute_metadata()?.permissions().mode() & 0o100 == 0o100;
      Ok(Stat::File(File {
        path: path_for_stat,
        is_executable: is_executable,
      }))
    } else if file_type.is_dir() {
      Ok(Stat::Dir(Dir(path_for_stat)))
    } else {
      Err(io::Error::new(
        io::ErrorKind::InvalidData,
        format!(
          "Expected File, Dir or Link, but {:?} (relative to {:?}) was a {:?}",
          path_for_stat, absolute_path_to_root, file_type
        ),
      ))
    }
  }

  pub fn stat_sync(&self, relative_path: PathBuf) -> Result<Option<Stat>, io::Error> {
    let abs_path = self.root.0.join(&relative_path);
    let metadata = match self.symlink_behavior {
      SymlinkBehavior::Aware => fs::symlink_metadata(abs_path),
      SymlinkBehavior::Oblivious => fs::metadata(abs_path),
    };
    let stat_result = metadata.and_then(|metadata| {
      PosixFS::stat_internal(&self.root.0, relative_path, metadata.file_type(), || {
        Ok(metadata)
      })
    });
    match stat_result {
      Ok(v) => Ok(Some(v)),
      Err(err) => match err.kind() {
        io::ErrorKind::NotFound => Ok(None),
        _ => Err(err),
      },
    }
  }
}

#[async_trait]
impl VFS<io::Error> for Arc<PosixFS> {
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
pub trait PathStatGetter<E> {
  async fn path_stats(&self, paths: Vec<PathBuf>) -> Result<Vec<Option<PathStat>>, E>;
}

#[async_trait]
impl PathStatGetter<io::Error> for Arc<PosixFS> {
  async fn path_stats(&self, paths: Vec<PathBuf>) -> Result<Vec<Option<PathStat>>, io::Error> {
    future::try_join_all(
      paths
        .into_iter()
        .map(|path| {
          let fs = self.clone();
          let fs2 = self.clone();
          self
            .executor
            .spawn_blocking(move || fs2.stat_sync(path))
            .and_then(move |maybe_stat| {
              async move {
                match maybe_stat {
                  // Note: This will drop PathStats for symlinks which don't point anywhere.
                  Some(Stat::Link(link)) => fs.canonicalize(link.0.clone(), link).await,
                  Some(Stat::Dir(dir)) => Ok(Some(PathStat::dir(dir.0.clone(), dir))),
                  Some(Stat::File(file)) => Ok(Some(PathStat::file(file.path.clone(), file))),
                  None => Ok(None),
                }
              }
            })
        })
        .collect::<Vec<_>>(),
    )
    .await
  }
}

///
/// A context for filesystem operations parameterized on an error type 'E'.
///
#[async_trait]
pub trait VFS<E: Send + Sync + 'static>: Clone + Send + Sync + 'static {
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

// Like std::fs::create_dir_all, except handles concurrent calls among multiple
// threads or processes. Originally lifted from rustc.
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
