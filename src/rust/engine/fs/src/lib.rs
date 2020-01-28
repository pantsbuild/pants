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

mod glob_matching;
pub use crate::glob_matching::GlobMatching;

use ::ignore::gitignore::{Gitignore, GitignoreBuilder};
use boxfuture::{BoxFuture, Boxable};
use bytes::Bytes;
use futures01::{future, Future};
use glob::{MatchOptions, Pattern};
use lazy_static::lazy_static;
use std::cmp::min;
use std::ffi::OsStr;
use std::io::{self, Read};
use std::os::unix::fs::PermissionsExt;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use std::{fmt, fs};

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
  fn create(patterns: &[String]) -> Result<Arc<Self>, String> {
    if patterns.is_empty() {
      return Ok(EMPTY_IGNORE.clone());
    }

    let gitignore = Self::create_gitignore(patterns)
      .map_err(|e| format!("Could not parse glob excludes {:?}: {:?}", patterns, e))?;

    Ok(Arc::new(Self {
      patterns: patterns.to_vec(),
      gitignore,
    }))
  }

  fn create_gitignore(patterns: &[String]) -> Result<Gitignore, ::ignore::Error> {
    let mut ignore_builder = GitignoreBuilder::new("");
    for pattern in patterns {
      ignore_builder.add_line(None, pattern.as_str())?;
    }
    ignore_builder.build()
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
}

lazy_static! {
  static ref PARENT_DIR: &'static str = "..";
  static ref SINGLE_STAR_GLOB: Pattern = Pattern::new("*").unwrap();
  static ref DOUBLE_STAR: &'static str = "**";
  static ref DOUBLE_STAR_GLOB: Pattern = Pattern::new(*DOUBLE_STAR).unwrap();
  static ref EMPTY_IGNORE: Arc<GitignoreStyleExcludes> = Arc::new(GitignoreStyleExcludes {
    patterns: vec![],
    gitignore: Gitignore::empty(),
  });
  static ref MISSING_GLOB_SOURCE: GlobParsedSource = GlobParsedSource(String::from(""));
  static ref PATTERN_MATCH_OPTIONS: MatchOptions = MatchOptions {
    require_literal_separator: true,
    ..MatchOptions::default()
  };
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum PathGlob {
  Wildcard {
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Pattern,
  },
  DirWildcard {
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Pattern,
    remainder: Vec<Pattern>,
  },
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct GlobParsedSource(String);

#[derive(Clone, Debug, PartialEq)]
pub struct PathGlobIncludeEntry {
  pub input: GlobParsedSource,
  pub globs: Vec<PathGlob>,
}

impl PathGlob {
  fn wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: Pattern) -> PathGlob {
    PathGlob::Wildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
    }
  }

  fn dir_wildcard(
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Pattern,
    remainder: Vec<Pattern>,
  ) -> PathGlob {
    PathGlob::DirWildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
      remainder: remainder,
    }
  }

  pub fn create(filespecs: &[String]) -> Result<Vec<PathGlob>, String> {
    // Getting a Vec<PathGlob> per filespec is needed to create a `PathGlobs`, but we don't need
    // that here.
    let filespecs_globs = Self::spread_filespecs(filespecs)?;
    let all_globs = Self::flatten_entries(filespecs_globs);
    Ok(all_globs)
  }

  fn flatten_entries(entries: Vec<PathGlobIncludeEntry>) -> Vec<PathGlob> {
    entries.into_iter().flat_map(|entry| entry.globs).collect()
  }

  fn spread_filespecs(filespecs: &[String]) -> Result<Vec<PathGlobIncludeEntry>, String> {
    let mut spec_globs_map = Vec::new();
    for filespec in filespecs {
      let canonical_dir = Dir(PathBuf::new());
      let symbolic_path = PathBuf::new();
      spec_globs_map.push(PathGlobIncludeEntry {
        input: GlobParsedSource(filespec.clone()),
        globs: PathGlob::parse(canonical_dir, symbolic_path, filespec)?,
      });
    }
    Ok(spec_globs_map)
  }

  ///
  /// Normalize the given glob pattern string by splitting it into path components, and dropping
  /// references to the current directory, and consecutive '**'s.
  ///
  fn normalize_pattern(pattern: &str) -> Result<Vec<&OsStr>, String> {
    let mut parts = Vec::new();
    let mut prev_was_doublestar = false;
    for component in Path::new(pattern).components() {
      let part = match component {
        Component::Prefix(..) | Component::RootDir => {
          return Err(format!("Absolute paths not supported: {:?}", pattern));
        }
        Component::CurDir => continue,
        c => c.as_os_str(),
      };

      // Ignore repeated doublestar instances.
      let cur_is_doublestar = *DOUBLE_STAR == part;
      if prev_was_doublestar && cur_is_doublestar {
        continue;
      }
      prev_was_doublestar = cur_is_doublestar;

      parts.push(part);
    }
    Ok(parts)
  }

  ///
  /// Given a filespec String relative to a canonical Dir and path, parse it to a normalized
  /// series of PathGlob objects.
  ///
  fn parse(
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    filespec: &str,
  ) -> Result<Vec<PathGlob>, String> {
    // NB: Because the filespec is a String input, calls to `to_str_lossy` are not lossy; the
    // use of `Path` is strictly for os-independent Path parsing.
    let parts = Self::normalize_pattern(filespec)?
      .into_iter()
      .map(|part| {
        Pattern::new(&part.to_string_lossy())
          .map_err(|e| format!("Could not parse {:?} as a glob: {:?}", filespec, e))
      })
      .collect::<Result<Vec<_>, _>>()?;

    PathGlob::parse_globs(canonical_dir, symbolic_path, &parts)
  }

  ///
  /// Given a filespec as Patterns, create a series of PathGlob objects.
  ///
  fn parse_globs(
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    parts: &[Pattern],
  ) -> Result<Vec<PathGlob>, String> {
    if parts.is_empty() {
      Ok(vec![])
    } else if *DOUBLE_STAR == parts[0].as_str() {
      if parts.len() == 1 {
        // Per https://git-scm.com/docs/gitignore:
        //  "A trailing '/**' matches everything inside. For example, 'abc/**' matches all files
        //  inside directory "abc", relative to the location of the .gitignore file, with infinite
        //  depth."
        return Ok(vec![
          PathGlob::dir_wildcard(
            canonical_dir.clone(),
            symbolic_path.clone(),
            SINGLE_STAR_GLOB.clone(),
            vec![DOUBLE_STAR_GLOB.clone()],
          ),
          PathGlob::wildcard(canonical_dir, symbolic_path, SINGLE_STAR_GLOB.clone()),
        ]);
      }

      // There is a double-wildcard in a dirname of the path: double wildcards are recursive,
      // so there are two remainder possibilities: one with the double wildcard included, and the
      // other without.
      let pathglob_with_doublestar = PathGlob::dir_wildcard(
        canonical_dir.clone(),
        symbolic_path.clone(),
        SINGLE_STAR_GLOB.clone(),
        parts[0..].to_vec(),
      );
      let pathglob_no_doublestar = if parts.len() == 2 {
        PathGlob::wildcard(canonical_dir, symbolic_path, parts[1].clone())
      } else {
        PathGlob::dir_wildcard(
          canonical_dir,
          symbolic_path,
          parts[1].clone(),
          parts[2..].to_vec(),
        )
      };
      Ok(vec![pathglob_with_doublestar, pathglob_no_doublestar])
    } else if *PARENT_DIR == parts[0].as_str() {
      // A request for the parent of `canonical_dir`: since we've already expanded the directory
      // to make it canonical, we can safely drop it directly and recurse without this component.
      // The resulting symbolic path will continue to contain a literal `..`.
      let mut canonical_dir_parent = canonical_dir;
      let mut symbolic_path_parent = symbolic_path;
      if !canonical_dir_parent.0.pop() {
        let mut symbolic_path = symbolic_path_parent;
        symbolic_path.extend(parts.iter().map(Pattern::as_str));
        return Err(format!(
          "Globs may not traverse outside of the buildroot: {:?}",
          symbolic_path,
        ));
      }
      symbolic_path_parent.push(Path::new(*PARENT_DIR));
      PathGlob::parse_globs(canonical_dir_parent, symbolic_path_parent, &parts[1..])
    } else if parts.len() == 1 {
      // This is the path basename.
      Ok(vec![PathGlob::wildcard(
        canonical_dir,
        symbolic_path,
        parts[0].clone(),
      )])
    } else {
      // This is a path dirname.
      Ok(vec![PathGlob::dir_wildcard(
        canonical_dir,
        symbolic_path,
        parts[0].clone(),
        parts[1..].to_vec(),
      )])
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

#[derive(Debug)]
pub struct PathGlobs {
  include: Vec<PathGlobIncludeEntry>,
  exclude: Arc<GitignoreStyleExcludes>,
  strict_match_behavior: StrictGlobMatching,
  conjunction: GlobExpansionConjunction,
  patterns: Vec<glob::Pattern>,
}

impl PathGlobs {
  fn parse_patterns_from_include(
    include: &[PathGlobIncludeEntry],
  ) -> Result<Vec<glob::Pattern>, String> {
    include
      .iter()
      .map(|pattern| {
        PathGlob::normalize_pattern(&pattern.input.0).and_then(|components| {
          let normalized_pattern: PathBuf = components.into_iter().collect();
          Pattern::new(normalized_pattern.to_str().unwrap())
            .map_err(|e| format!("Could not parse {:?} as a glob: {:?}", pattern.input.0, e))
        })
      })
      .collect::<Result<Vec<_>, String>>()
  }

  pub fn create(
    globs: &[String],
    strict_match_behavior: StrictGlobMatching,
    conjunction: GlobExpansionConjunction,
  ) -> Result<PathGlobs, String> {
    // NB: We use a loop, rather than `.filter()`, to avoid traversing the globs twice.
    let mut include_globs: Vec<String> = vec![];
    let mut exclude_globs: Vec<String> = vec![];
    for glob in globs {
      if glob.starts_with('!') {
        let normalized_exclude: String = glob.chars().skip(1).collect();
        exclude_globs.push(normalized_exclude.clone());
      } else {
        include_globs.push(glob.clone());
      }
    }
    let include = PathGlob::spread_filespecs(include_globs.as_slice())?;
    let exclude = GitignoreStyleExcludes::create(exclude_globs.as_slice())?;
    let patterns = PathGlobs::parse_patterns_from_include(&include)?;

    Ok(PathGlobs {
      include,
      exclude,
      strict_match_behavior,
      conjunction,
      patterns,
    })
  }

  pub fn from_globs(include: Vec<PathGlob>) -> Result<PathGlobs, String> {
    let include: Vec<PathGlobIncludeEntry> = include
      .into_iter()
      .map(|glob| PathGlobIncludeEntry {
        input: MISSING_GLOB_SOURCE.clone(),
        globs: vec![glob],
      })
      .collect();

    let patterns = PathGlobs::parse_patterns_from_include(&include.as_slice())?;
    Ok(PathGlobs {
      include,
      // An empty exclude becomes EMPTY_IGNORE.
      exclude: GitignoreStyleExcludes::create(&[])?,
      strict_match_behavior: StrictGlobMatching::Ignore,
      conjunction: GlobExpansionConjunction::AllMatch,
      patterns,
    })
  }

  ///
  /// Matches these PathGlobs against the given paths.
  ///
  /// NB: This implementation is independent from GlobMatchingImplementation::expand, and must be
  /// kept in sync via unit tests (in particular: the python FilespecTest) in order to allow for
  /// owners detection of deleted files (see #6790 and #5636 for more info). The lazy filesystem
  /// traversal in expand is (currently) too expensive to use for that in-memory matching (such as
  /// via MemFS).
  ///
  pub fn matches(&self, paths: &[PathBuf]) -> bool {
    self.patterns.iter().any(|pattern| {
      paths
        .iter()
        .any(|path| self.pattern_matches_single_path(&pattern, path))
    })
  }

  fn pattern_matches_single_path(&self, pattern: &glob::Pattern, path: &PathBuf) -> bool {
    pattern.matches_path_with(path, &PATTERN_MATCH_OPTIONS)
      && !self.exclude.is_ignored_path(path, false)
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum GlobSource {
  ParsedInput(GlobParsedSource),
  ParentGlob(PathGlob),
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct GlobWithSource {
  path_glob: PathGlob,
  source: GlobSource,
}

#[derive(Clone)]
pub enum SymlinkBehavior {
  Aware,
  Oblivious,
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
    ignore_patterns: &[String],
    executor: task_executor::Executor,
  ) -> Result<PosixFS, String> {
    Self::new_with_symlink_behavior(root, ignore_patterns, executor, SymlinkBehavior::Aware)
  }

  pub fn new_with_symlink_behavior<P: AsRef<Path>>(
    root: P,
    ignore_patterns: &[String],
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

    let ignore = GitignoreStyleExcludes::create(&ignore_patterns).map_err(|e| {
      format!(
        "Could not parse build ignore inputs {:?}: {:?}",
        ignore_patterns, e
      )
    })?;
    Ok(PosixFS {
      root: canonical_root,
      ignore: ignore,
      executor: executor,
      symlink_behavior: symlink_behavior,
    })
  }

  pub fn scandir(
    &self,
    dir_relative_to_root: Dir,
  ) -> impl Future<Item = DirectoryListing, Error = io::Error> {
    let vfs = self.clone();
    self.executor.spawn_on_io_pool(future::lazy(move || {
      vfs.scandir_sync(&dir_relative_to_root)
    }))
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

  pub fn read_file(&self, file: &File) -> impl Future<Item = FileContent, Error = io::Error> {
    let path = file.path.clone();
    let path_abs = self.root.0.join(&file.path);
    self.executor.spawn_on_io_pool(future::lazy(move || {
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
    }))
  }

  pub fn read_link(&self, link: &Link) -> impl Future<Item = PathBuf, Error = io::Error> {
    let link_parent = link.0.parent().map(Path::to_owned);
    let link_abs = self.root.0.join(link.0.as_path());
    self.executor.spawn_on_io_pool(future::lazy(move || {
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
    }))
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

  pub fn stat_sync(&self, relative_path: PathBuf) -> Result<Stat, io::Error> {
    let abs_path = self.root.0.join(&relative_path);
    let metadata = match self.symlink_behavior {
      SymlinkBehavior::Aware => fs::symlink_metadata(abs_path)?,
      SymlinkBehavior::Oblivious => fs::metadata(abs_path)?,
    };
    PosixFS::stat_internal(&self.root.0, relative_path, metadata.file_type(), || {
      Ok(metadata)
    })
  }
}

impl VFS<io::Error> for Arc<PosixFS> {
  fn read_link(&self, link: &Link) -> BoxFuture<PathBuf, io::Error> {
    PosixFS::read_link(self, link).to_boxed()
  }

  fn scandir(&self, dir: Dir) -> BoxFuture<Arc<DirectoryListing>, io::Error> {
    PosixFS::scandir(self, dir).map(Arc::new).to_boxed()
  }

  fn is_ignored(&self, stat: &Stat) -> bool {
    PosixFS::is_ignored(self, stat)
  }

  fn mk_error(msg: &str) -> io::Error {
    io::Error::new(io::ErrorKind::Other, msg)
  }
}

pub trait PathStatGetter<E> {
  fn path_stats(&self, paths: Vec<PathBuf>) -> BoxFuture<Vec<Option<PathStat>>, E>;
}

impl PathStatGetter<io::Error> for Arc<PosixFS> {
  fn path_stats(&self, paths: Vec<PathBuf>) -> BoxFuture<Vec<Option<PathStat>>, io::Error> {
    future::join_all(
      paths
        .into_iter()
        .map(|path| {
          let fs = self.clone();
          let fs2 = self.clone();
          self
            .executor
            .spawn_on_io_pool(future::lazy(move || fs2.stat_sync(path)))
            .then(|stat_result| match stat_result {
              Ok(v) => Ok(Some(v)),
              Err(err) => match err.kind() {
                io::ErrorKind::NotFound => Ok(None),
                _ => Err(err),
              },
            })
            .and_then(move |maybe_stat| {
              match maybe_stat {
                // Note: This will drop PathStats for symlinks which don't point anywhere.
                Some(Stat::Link(link)) => fs.canonicalize(link.0.clone(), link),
                Some(Stat::Dir(dir)) => {
                  future::ok(Some(PathStat::dir(dir.0.clone(), dir))).to_boxed()
                }
                Some(Stat::File(file)) => {
                  future::ok(Some(PathStat::file(file.path.clone(), file))).to_boxed()
                }
                None => future::ok(None).to_boxed(),
              }
            })
        })
        .collect::<Vec<_>>(),
    )
    .to_boxed()
  }
}

///
/// A context for filesystem operations parameterized on an error type 'E'.
///
pub trait VFS<E: Send + Sync + 'static>: Clone + Send + Sync + 'static {
  fn read_link(&self, link: &Link) -> BoxFuture<PathBuf, E>;
  fn scandir(&self, dir: Dir) -> BoxFuture<Arc<DirectoryListing>, E>;
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

#[cfg(test)]
mod fs_tests;

#[cfg(test)]
mod posixfs_tests;
