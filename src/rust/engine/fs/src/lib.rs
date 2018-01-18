// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

mod snapshot;
pub use snapshot::{GetFileDigest, Snapshot};
mod store;
pub use store::Store;
mod pool;
pub use pool::ResettablePool;

extern crate bazel_protos;
extern crate boxfuture;
extern crate bytes;
extern crate digest;
extern crate futures;
extern crate futures_cpupool;
extern crate glob;
extern crate grpcio;
extern crate hashing;
extern crate hex;
extern crate ignore;
extern crate itertools;
#[macro_use]
extern crate lazy_static;
extern crate lmdb;
#[cfg(test)]
extern crate mock;
extern crate ordermap;
extern crate protobuf;
extern crate sha2;
extern crate tar;
extern crate tempdir;

use std::collections::HashSet;
use std::os::unix::fs::PermissionsExt;
use std::path::{Component, Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::{fmt, fs};
use std::io::{self, Read};
use std::cmp::min;

use futures::future::{self, Future};
use futures_cpupool::CpuFuture;
use glob::Pattern;
use hashing::{Fingerprint, WriterHasher};
use ignore::gitignore::{Gitignore, GitignoreBuilder};
use ordermap::OrderMap;
use tempdir::TempDir;

use boxfuture::{Boxable, BoxFuture};


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
  fn dir(path: PathBuf, stat: Dir) -> PathStat {
    PathStat::Dir {
      path: path,
      stat: stat,
    }
  }

  fn file(path: PathBuf, stat: File) -> PathStat {
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

lazy_static! {
  static ref PARENT_DIR: &'static str = "..";

  static ref SINGLE_STAR_GLOB: Pattern = Pattern::new("*").unwrap();

  static ref DOUBLE_STAR: &'static str = "**";
  static ref DOUBLE_STAR_GLOB: Pattern = Pattern::new("**").unwrap();

  static ref EMPTY_IGNORE: Arc<Gitignore> = Arc::new(Gitignore::empty());
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
    let mut path_globs = Vec::new();
    for filespec in filespecs {
      let canonical_dir = Dir(PathBuf::new());
      let symbolic_path = PathBuf::new();
      path_globs.extend(PathGlob::parse(canonical_dir, symbolic_path, filespec)?);
    }
    Ok(path_globs)
  }

  ///
  /// Given a filespec String relative to a canonical Dir and path, split it into path components
  /// while eliminating consecutive '**'s (to avoid repetitive traversing), and parse it to a
  /// series of PathGlob objects.
  ///
  fn parse(
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    filespec: &str,
  ) -> Result<Vec<PathGlob>, String> {
    let mut parts = Vec::new();
    let mut prev_was_doublestar = false;
    for component in Path::new(filespec).components() {
      let part = match component {
        Component::Prefix(..) |
        Component::RootDir => return Err(format!("Absolute paths not supported: {:?}", filespec)),
        Component::CurDir => continue,
        c => c.as_os_str(),
      };

      // Ignore repeated doublestar instances.
      let cur_is_doublestar = *DOUBLE_STAR == part;
      if prev_was_doublestar && cur_is_doublestar {
        continue;
      }
      prev_was_doublestar = cur_is_doublestar;

      // NB: Because the filespec is a String input, calls to `to_str_lossy` are not lossy; the
      // use of `Path` is strictly for os-independent Path parsing.
      parts.push(Pattern::new(&part.to_string_lossy()).map_err(|e| {
        format!("Could not parse {:?} as a glob: {:?}", filespec, e)
      })?);
    }

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
            vec![DOUBLE_STAR_GLOB.clone()]
          ),
          PathGlob::wildcard(
            canonical_dir,
            symbolic_path,
            SINGLE_STAR_GLOB.clone()
          ),
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
        return Err(format!(
          "Globs may not traverse outside the root: {:?}",
          parts
        ));
      }
      symbolic_path_parent.push(Path::new(*PARENT_DIR));
      PathGlob::parse_globs(canonical_dir_parent, symbolic_path_parent, &parts[1..])
    } else if parts.len() == 1 {
      // This is the path basename.
      Ok(vec![
        PathGlob::wildcard(
          canonical_dir,
          symbolic_path,
          parts[0].clone()
        ),
      ])
    } else {
      // This is a path dirname.
      Ok(vec![
        PathGlob::dir_wildcard(
          canonical_dir,
          symbolic_path,
          parts[0].clone(),
          parts[1..].to_vec()
        ),
      ])
    }
  }
}

#[derive(Debug)]
pub struct PathGlobs {
  include: Vec<PathGlob>,
  exclude: Arc<Gitignore>,
}

impl PathGlobs {
  pub fn create(include: &[String], exclude: &[String]) -> Result<PathGlobs, String> {
    let ignore_for_exclude = if exclude.is_empty() {
      EMPTY_IGNORE.clone()
    } else {
      Arc::new(create_ignore(exclude).map_err(|e| {
        format!("Could not parse glob excludes {:?}: {:?}", exclude, e)
      })?)
    };
    Ok(PathGlobs {
      include: PathGlob::create(include)?,
      exclude: ignore_for_exclude,
    })
  }

  pub fn from_globs(include: Vec<PathGlob>) -> PathGlobs {
    PathGlobs {
      include: include,
      exclude: EMPTY_IGNORE.clone(),
    }
  }
}

#[derive(Debug)]
struct PathGlobsExpansion<T: Sized> {
  context: T,
  // Globs that have yet to be expanded, in order.
  todo: Vec<PathGlob>,
  // Paths to exclude.
  exclude: Arc<Gitignore>,
  // Globs that have already been expanded.
  completed: HashSet<PathGlob>,
  // Unique Paths that have been matched, in order.
  outputs: OrderMap<PathStat, ()>,
}

fn create_ignore(patterns: &[String]) -> Result<Gitignore, ignore::Error> {
  let mut ignore_builder = GitignoreBuilder::new("");
  for pattern in patterns {
    ignore_builder.add_line(None, pattern.as_str())?;
  }
  ignore_builder.build()
}

fn is_ignored(ignore: &Gitignore, stat: &Stat) -> bool {
  let is_dir = match stat {
    &Stat::Dir(_) => true,
    _ => false,
  };
  match ignore.matched(stat.path(), is_dir) {
    ignore::Match::None |
    ignore::Match::Whitelist(_) => false,
    ignore::Match::Ignore(_) => true,
  }
}

///
/// All Stats consumed or return by this type are relative to the root.
///
pub struct PosixFS {
  root: Dir,
  pool: Arc<ResettablePool>,
  ignore: Gitignore,
}

impl PosixFS {
  pub fn new<P: AsRef<Path>>(
    root: P,
    pool: Arc<ResettablePool>,
    ignore_patterns: Vec<String>,
  ) -> Result<PosixFS, String> {
    let root: &Path = root.as_ref();
    let canonical_root = root
      .canonicalize()
      .and_then(|canonical| {
        canonical.metadata().and_then(
          |metadata| if metadata.is_dir() {
            Ok(Dir(canonical))
          } else {
            Err(io::Error::new(
              io::ErrorKind::InvalidInput,
              "Not a directory.",
            ))
          },
        )
      })
      .map_err(|e| {
        format!("Could not canonicalize root {:?}: {:?}", root, e)
      })?;

    let ignore = create_ignore(&ignore_patterns).map_err(|e| {
      format!(
        "Could not parse build ignore inputs {:?}: {:?}",
        ignore_patterns,
        e
      )
    })?;
    Ok(PosixFS {
      root: canonical_root,
      pool: pool,
      ignore: ignore,
    })
  }

  fn scandir_sync(root: PathBuf, dir_relative_to_root: Dir) -> Result<Vec<Stat>, io::Error> {
    let dir_abs = root.join(&dir_relative_to_root.0);
    let mut stats: Vec<Stat> = dir_abs
      .read_dir()?
      .map(|readdir| {
        let dir_entry = readdir?;
        let get_metadata = || std::fs::metadata(dir_abs.join(dir_entry.file_name()));
        PosixFS::stat_internal(
          dir_relative_to_root.0.join(dir_entry.file_name()),
          dir_entry.file_type()?,
          &dir_abs,
          get_metadata,
        )
      })
      .collect::<Result<Vec<_>, io::Error>>()?;
    stats.sort_by(|s1, s2| s1.path().cmp(s2.path()));
    Ok(stats)
  }

  pub fn is_ignored(&self, stat: &Stat) -> bool {
    is_ignored(&self.ignore, stat)
  }

  pub fn read_file(&self, file: &File) -> BoxFuture<FileContent, io::Error> {
    let path = file.path.clone();
    let path_abs = self.root.0.join(&file.path);
    self
      .pool
      .spawn_fn(move || {
        std::fs::File::open(&path_abs).and_then(|mut f| {
          let mut content = Vec::new();
          f.read_to_end(&mut content)?;
          Ok(FileContent { path, content })
        })
      })
      .to_boxed()
  }

  pub fn read_link(&self, link: &Link) -> BoxFuture<PathBuf, io::Error> {
    let link_parent = link.0.parent().map(|p| p.to_owned());
    let link_abs = self.root.0.join(link.0.as_path()).to_owned();
    self
      .pool
      .spawn_fn(move || {
        link_abs.read_link().and_then(
          |path_buf| if path_buf.is_absolute() {
            Err(io::Error::new(
              io::ErrorKind::InvalidData,
              format!("Absolute symlink: {:?}", link_abs),
            ))
          } else {
            link_parent.map(|parent| parent.join(path_buf)).ok_or_else(
              || {
                io::Error::new(
                  io::ErrorKind::InvalidData,
                  format!("Symlink without a parent?: {:?}", link_abs),
                )
              },
            )
          },
        )
      })
      .to_boxed()
  }

  ///
  /// Makes a Stat for path_for_stat relative to absolute_path_to_root.
  ///
  fn stat_internal<F>(
    path_for_stat: PathBuf,
    file_type: std::fs::FileType,
    absolute_path_to_root: &Path,
    get_metadata: F,
  ) -> Result<Stat, io::Error>
  where
    F: FnOnce() -> Result<fs::Metadata, io::Error>,
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
    if file_type.is_dir() {
      Ok(Stat::Dir(Dir(path_for_stat)))
    } else if file_type.is_file() {
      let is_executable = get_metadata()?.permissions().mode() & 0o100 == 0o100;
      Ok(Stat::File(File {
        path: path_for_stat,
        is_executable: is_executable,
      }))
    } else if file_type.is_symlink() {
      Ok(Stat::Link(Link(path_for_stat)))
    } else {
      Err(io::Error::new(
        io::ErrorKind::InvalidData,
        format!(
          "Expected File, Dir or Link, but {:?} (relative to {:?}) was a {:?}",
          path_for_stat,
          absolute_path_to_root,
          file_type
        ),
      ))
    }
  }

  pub fn stat(&self, relative_path: PathBuf) -> Result<Stat, io::Error> {
    let metadata = fs::symlink_metadata(self.root.0.join(&relative_path))?;
    PosixFS::stat_internal(
      relative_path,
      metadata.file_type(),
      &self.root.0,
      || Ok(metadata),
    )
  }

  pub fn scandir(&self, dir: &Dir) -> BoxFuture<Vec<Stat>, io::Error> {
    let dir = dir.to_owned();
    let root = self.root.0.clone();
    self
      .pool
      .spawn_fn(move || PosixFS::scandir_sync(root, dir))
      .to_boxed()
  }
}

impl VFS<io::Error> for Arc<PosixFS> {
  fn read_link(&self, link: Link) -> BoxFuture<PathBuf, io::Error> {
    PosixFS::read_link(self, &link)
  }

  fn scandir(&self, dir: Dir) -> BoxFuture<Vec<Stat>, io::Error> {
    PosixFS::scandir(self, &dir)
  }

  fn is_ignored(&self, stat: &Stat) -> bool {
    PosixFS::is_ignored(self, stat)
  }

  fn mk_error(msg: &str) -> io::Error {
    io::Error::new(io::ErrorKind::Other, msg)
  }
}

///
/// A context for filesystem operations parameterized on an error type 'E'.
///
pub trait VFS<E: Send + Sync + 'static>: Clone + Send + Sync + 'static {
  fn read_link(&self, link: Link) -> BoxFuture<PathBuf, E>;
  fn scandir(&self, dir: Dir) -> BoxFuture<Vec<Stat>, E>;
  fn is_ignored(&self, stat: &Stat) -> bool;
  fn mk_error(msg: &str) -> E;

  ///
  /// Canonicalize the Link for the given Path to an underlying File or Dir. May result
  /// in None if the PathStat represents a broken Link.
  ///
  /// Skips ignored paths both before and after expansion.
  ///
  /// TODO: Should handle symlink loops (which would exhibit as an infinite loop in expand).
  ///
  fn canonicalize(&self, symbolic_path: PathBuf, link: Link) -> BoxFuture<Option<PathStat>, E> {
    // Read the link, which may result in PathGlob(s) that match 0 or 1 Path.
    let context = self.clone();
    self
      .read_link(link)
      .map(|dest_path| {
        // If the link destination can't be parsed as PathGlob(s), it is broken.
        dest_path
          .to_str()
          .and_then(|dest_str| {
            // Escape any globs in the parsed dest, which should guarantee one output PathGlob.
            PathGlob::create(&[Pattern::escape(dest_str)]).ok()
          })
          .unwrap_or_else(|| vec![])
      })
      .and_then(move |link_globs| {
        context.expand(PathGlobs::from_globs(link_globs))
      })
      .map(|mut path_stats| {
        // Since we've escaped any globs in the parsed path, expect either 0 or 1 destination.
        path_stats.pop().map(|ps| match ps {
          PathStat::Dir { stat, .. } => PathStat::dir(symbolic_path, stat),
          PathStat::File { stat, .. } => PathStat::file(symbolic_path, stat),
        })
      })
      .to_boxed()
  }

  fn directory_listing(
    &self,
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Pattern,
    exclude: &Arc<Gitignore>,
  ) -> BoxFuture<Vec<PathStat>, E> {
    // List the directory.
    let context = self.clone();
    let exclude = exclude.clone();

    self
      .scandir(canonical_dir)
      .and_then(move |dir_listing| {
        // Match any relevant Stats, and join them into PathStats.
        future::join_all(
          dir_listing
            .into_iter()
            .filter(|stat| {
              // Match relevant filenames.
              stat
                .path()
                .file_name()
                .map(|file_name| wildcard.matches_path(Path::new(file_name)))
                .unwrap_or(false)
            })
            .filter_map(|stat| {
              // Append matched filenames.
              stat
                .path()
                .file_name()
                .map(|file_name| symbolic_path.join(file_name))
                .map(|symbolic_stat_path| (symbolic_stat_path, stat))
            })
            .map(|(stat_symbolic_path, stat)| {
              // Canonicalize matched PathStats, and filter paths that are ignored by either the
              // context, or by local excludes. Note that we apply context ignore patterns to both
              // the symbolic and canonical names of Links, but only apply local excludes to their
              // symbolic names.
              if context.is_ignored(&stat) || is_ignored(&exclude, &stat) {
                future::ok(None).to_boxed()
              } else {
                match stat {
                  Stat::Link(l) => context.canonicalize(stat_symbolic_path, l),
                  Stat::Dir(d) => {
                    future::ok(Some(PathStat::dir(stat_symbolic_path.to_owned(), d))).to_boxed()
                  }
                  Stat::File(f) => {
                    future::ok(Some(PathStat::file(stat_symbolic_path.to_owned(), f))).to_boxed()
                  }
                }
              }
            })
            .collect::<Vec<_>>(),
        )
      })
      .map(|path_stats| {
        // See the TODO above.
        path_stats.into_iter().filter_map(|pso| pso).collect()
      })
      .to_boxed()
  }

  ///
  /// Recursively expands PathGlobs into PathStats while applying excludes.
  ///
  fn expand(&self, path_globs: PathGlobs) -> BoxFuture<Vec<PathStat>, E> {
    if path_globs.include.is_empty() {
      return future::ok(vec![]).to_boxed();
    }

    let init = PathGlobsExpansion {
      context: self.clone(),
      todo: path_globs.include,
      exclude: path_globs.exclude,
      completed: HashSet::default(),
      outputs: OrderMap::default(),
    };
    future::loop_fn(init, |mut expansion| {
      // Request the expansion of all outstanding PathGlobs as a batch.
      let round = future::join_all({
        let exclude = &expansion.exclude;
        let context = &expansion.context;
        expansion
          .todo
          .drain(..)
          .map(|path_glob| context.expand_single(path_glob, exclude))
          .collect::<Vec<_>>()
      });
      round.map(move |paths_and_globs| {
        // Collect distinct new PathStats and PathGlobs
        for (paths, globs) in paths_and_globs.into_iter() {
          expansion.outputs.extend(paths.into_iter().map(|p| (p, ())));
          let completed = &mut expansion.completed;
          expansion.todo.extend(globs.into_iter().filter(|pg| {
            completed.insert(pg.clone())
          }));
        }

        // If there were any new PathGlobs, continue the expansion.
        if expansion.todo.is_empty() {
          future::Loop::Break(expansion)
        } else {
          future::Loop::Continue(expansion)
        }
      })
    }).map(|expansion| {
      assert!(
        expansion.todo.is_empty(),
        "Loop shouldn't have exited with work to do: {:?}",
        expansion.todo,
      );
      // Finally, capture the resulting PathStats from the expansion.
      expansion.outputs.into_iter().map(|(k, _)| k).collect()
    })
      .to_boxed()
  }

  ///
  /// Apply a PathGlob, returning PathStats and additional PathGlobs that are needed for the
  /// expansion.
  ///
  fn expand_single(
    &self,
    path_glob: PathGlob,
    exclude: &Arc<Gitignore>,
  ) -> BoxFuture<(Vec<PathStat>, Vec<PathGlob>), E> {
    match path_glob {
      PathGlob::Wildcard { canonical_dir, symbolic_path, wildcard } =>
        // Filter directory listing to return PathStats, with no continuation.
        self.directory_listing(canonical_dir, symbolic_path, wildcard, exclude)
          .map(|path_stats| (path_stats, vec![]))
          .to_boxed(),
      PathGlob::DirWildcard { canonical_dir, symbolic_path, wildcard, remainder } =>
        // Filter directory listing and request additional PathGlobs for matched Dirs.
        self.directory_listing(canonical_dir, symbolic_path, wildcard, exclude)
          .and_then(move |path_stats| {
            path_stats.into_iter()
              .filter_map(|ps| match ps {
                PathStat::Dir { path, stat } =>
                  Some(
                    PathGlob::parse_globs(stat, path, &remainder)
                      .map_err(|e| Self::mk_error(e.as_str()))
                  ),
                PathStat::File { .. } => None,
              })
              .collect::<Result<Vec<_>, E>>()
          })
          .map(|path_globs| {
            let flattened =
              path_globs.into_iter()
                .flat_map(|path_globs| path_globs.into_iter())
                .collect();
            (vec![], flattened)
          })
          .to_boxed(),
    }
  }
}

pub struct FileContent {
  pub path: PathBuf,
  pub content: Vec<u8>,
}

impl fmt::Debug for FileContent {
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
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
    Some(p) => try!(safe_create_dir_all_ioerror(p)),
    None => return Ok(()),
  }
  match fs::create_dir(path) {
    Ok(()) => Ok(()),
    Err(ref e) if e.kind() == io::ErrorKind::AlreadyExists => Ok(()),
    Err(e) => Err(e),
  }
}

fn safe_create_dir_all(path: &Path) -> Result<(), String> {
  safe_create_dir_all_ioerror(path).map_err(|e| {
    format!("Failed to create dir {:?} due to {:?}", path, e)
  })
}

fn safe_create_tmpdir_in(base_dir: &Path, prefix: &str) -> Result<TempDir, String> {
  safe_create_dir_all(&base_dir)?;
  Ok(TempDir::new_in(&base_dir, prefix).map_err(|e| {
    format!("Failed to create tempdir {:?} due to {:?}", base_dir, e)
  })?)
}

///
/// A facade for the snapshot directory, which lives under the pants workdir.
///
pub struct Snapshots {
  snapshots_dir: PathBuf,
  snapshots_generator: Mutex<(TempDir, usize)>,
}

impl Snapshots {
  pub fn new(snapshots_dir: PathBuf) -> Result<Snapshots, String> {
    let snapshots_tmpdir = safe_create_tmpdir_in(&snapshots_dir, ".tmp")?;

    Ok(Snapshots {
      snapshots_dir: snapshots_dir,
      snapshots_generator: Mutex::new((snapshots_tmpdir, 0)),
    })
  }

  pub fn snapshot_path(&self) -> &Path {
    self.snapshots_dir.as_path()
  }

  fn next_temp_path(&self) -> Result<PathBuf, String> {
    let mut gen = self.snapshots_generator.lock().unwrap();
    gen.1 += 1;

    // N.B. Sometimes, in e.g. a `./pants clean-all test ...` the snapshot tempdir created at the
    // beginning of a run can be removed out from under us by e.g. the `clean-all` task. Here, we
    // we double check existence of the `TempDir`'s path when the path is accessed and replace if
    // necessary.
    if !gen.0.path().exists() {
      gen.0 = safe_create_tmpdir_in(&self.snapshots_dir, ".tmp")?;
    }

    Ok(gen.0.path().join(format!("{}.tmp", gen.1)))
  }

  ///
  /// A non-canonical (does not expand symlinks) in-memory form of normalize. Used to collapse
  /// parent and cur components, which are legal in symbolic paths in PathStats, but not in
  /// Tar files.
  ///
  fn normalize(path: &Path) -> Result<PathBuf, String> {
    let mut res = PathBuf::new();
    for component in path.components() {
      match component {
        Component::Prefix(..) |
        Component::RootDir => return Err(format!("Absolute paths not supported: {:?}", path)),
        Component::CurDir => continue,
        Component::ParentDir => {
          // Pop the previous component.
          if !res.pop() {
            return Err(format!(
              "Globs may not traverse outside the root: {:?}",
              path
            ));
          } else {
            continue;
          }
        }
        Component::Normal(p) => res.push(p),
      }
    }
    Ok(res)
  }

  ///
  /// Create a tar file on the given Write instance containing the given paths, or
  /// return an error string.
  ///
  fn tar_create<W: io::Write>(
    dest: W,
    paths: &Vec<PathStat>,
    relative_to: &Dir,
  ) -> Result<W, String> {
    let mut tar_builder = tar::Builder::new(dest);
    tar_builder.mode(tar::HeaderMode::Deterministic);
    for path_stat in paths {
      // Append the PathStat using the symbolic name and underlying stat.
      let append_res = match path_stat {
        &PathStat::File { ref path, ref stat } => {
          let normalized = Snapshots::normalize(path)?;
          let mut input = fs::File::open(relative_to.0.join(stat.path.as_path()))
            .map_err(|e| format!("Failed to open {:?}: {:?}", path_stat, e))?;
          tar_builder.append_file(normalized, &mut input)
        }
        &PathStat::Dir { ref path, ref stat } => {
          let normalized = Snapshots::normalize(path)?;
          tar_builder.append_dir(normalized, relative_to.0.join(stat.0.as_path()))
        }
      };
      append_res.map_err(|e| {
        format!("Failed to tar {:?}: {:?}", path_stat, e)
      })?;
    }

    // Finish the tar file, returning ownership of the stream to the caller.
    Ok(tar_builder.into_inner().map_err(|e| {
      format!("Failed to finalize snapshot tar: {:?}", e)
    })?)
  }

  ///
  /// Create a tar file at the given dest Path containing the given paths, while
  /// fingerprinting the written stream.
  ///
  fn tar_create_fingerprinted(
    dest: &Path,
    paths: &Vec<PathStat>,
    relative_to: &Dir,
  ) -> Result<Fingerprint, String> {
    // Wrap buffering around a fingerprinted stream above a File.
    let stream = io::BufWriter::new(WriterHasher::new(fs::File::create(dest).map_err(|e| {
      format!("Failed to create destination file: {:?}", e)
    })?));

    // Then append the tar to the stream, and retrieve the Fingerprint to flush all writers.
    Ok(
      Snapshots::tar_create(stream, paths, relative_to)?
        .into_inner()
        .map_err(|e| {
          format!("Failed to flush to {:?}: {:?}", dest, e.error())
        })?
        .finish(),
    )
  }

  ///
  /// Attempts to rename src to dst, and _succeeds_ if dst already exists. This is safe in
  /// the case of Snapshots because the destination path is unique to its content.
  ///
  fn finalize(temp_path: &Path, dest_path: &Path) -> Result<(), String> {
    if dest_path.is_file() {
      // The Snapshot has already been created.
      fs::remove_file(temp_path).unwrap_or(());
      Ok(())
    } else {
      let dest_dir = dest_path.parent().expect(
        "All snapshot paths must have parent directories.",
      );
      safe_create_dir_all(dest_dir)?;
      match fs::rename(temp_path, dest_path) {
        Ok(_) => Ok(()),
        Err(_) if dest_path.is_file() => Ok(()),
        Err(e) => Err(format!(
          "Failed to finalize snapshot at {:?}: {:?}",
          dest_path,
          e
        )),
      }
    }
  }

  fn path_for(&self, fingerprint: &Fingerprint) -> PathBuf {
    Snapshots::path_under_for(self.snapshot_path(), fingerprint)
  }

  fn path_under_for(path: &Path, fingerprint: &Fingerprint) -> PathBuf {
    let hex = fingerprint.to_hex();
    path.join(&hex[0..2]).join(&hex[2..4]).join(
      format!("{}.tar", hex),
    )
  }

  ///
  /// Creates a Snapshot for the given paths under the given VFS.
  ///
  pub fn create(&self, fs: &PosixFS, paths: Vec<PathStat>) -> CpuFuture<Snapshot, String> {
    let dest_dir = self.snapshot_path().to_owned();
    let root = fs.root.clone();
    let temp_path = self.next_temp_path().expect(
      "Couldn't get the next temp path.",
    );

    fs.pool.spawn_fn(move || {
      // Write the tar deterministically to a temporary file while fingerprinting.
      let fingerprint = Snapshots::tar_create_fingerprinted(temp_path.as_path(), &paths, &root)?;

      // Rename to the final path if it does not already exist.
      Snapshots::finalize(
        temp_path.as_path(),
        Snapshots::path_under_for(&dest_dir, &fingerprint).as_path(),
      )?;

      Ok(Snapshot {
        fingerprint: fingerprint,
        digest: None,
        path_stats: paths,
      })
    })
  }

  fn contents_for_sync(snapshot: Snapshot, path: PathBuf) -> Result<Vec<FileContent>, io::Error> {
    let mut archive = fs::File::open(path).map(|f| tar::Archive::new(f))?;

    // Zip the in-memory Snapshot to the on disk representation, validating as we go.
    let mut files_content = Vec::new();
    for (entry_res, path_stat) in archive.entries()?.zip(snapshot.path_stats.into_iter()) {
      let mut entry = entry_res?;
      if entry.header().entry_type() == tar::EntryType::file() {
        let path = match path_stat {
          PathStat::File { path, .. } => path,
          PathStat::Dir { .. } => panic!("Snapshot contents changed after storage."),
        };
        let mut content = Vec::new();
        io::Read::read_to_end(&mut entry, &mut content)?;
        files_content.push(FileContent {
          path: path,
          content: content,
        });
      }
    }
    Ok(files_content)
  }

  pub fn contents_for(
    &self,
    fs: &PosixFS,
    snapshot: Snapshot,
  ) -> CpuFuture<Vec<FileContent>, String> {
    let archive_path = self.path_for(&snapshot.fingerprint);
    fs.pool.spawn_fn(move || {
      let snapshot_str = format!("{:?}", snapshot);
      Snapshots::contents_for_sync(snapshot, archive_path).map_err(|e| {
        format!("Failed to open Snapshot {}: {:?}", snapshot_str, e)
      })
    })
  }
}

#[cfg(test)]
mod posixfs_test {
  extern crate tempdir;
  extern crate testutil;

  use super::{Dir, File, Link, PosixFS, Stat, ResettablePool};
  use futures::Future;
  use self::testutil::make_file;
  use std;
  use std::path::{Path, PathBuf};
  use std::sync::Arc;

  #[test]
  fn is_executable_false() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    make_file(&dir.path().join("marmosets"), &[], 0o611);
    assert_only_file_is_executable(dir.path(), false);
  }

  #[test]
  fn is_executable_true() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    make_file(&dir.path().join("photograph_marmosets"), &[], 0o700);
    assert_only_file_is_executable(dir.path(), true);
  }

  #[test]
  fn read_file() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    let path = PathBuf::from("marmosets");
    let content = "cute".as_bytes().to_vec();
    make_file(
      &std::fs::canonicalize(dir.path()).unwrap().join(&path),
      &content,
      0o600,
    );
    let fs = new_posixfs(&dir.path());
    let file_content = fs.read_file(&File {
      path: path.clone(),
      is_executable: false,
    }).wait()
      .unwrap();
    assert_eq!(file_content.path, path);
    assert_eq!(file_content.content, content);
  }

  #[test]
  fn read_file_missing() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    new_posixfs(&dir.path())
      .read_file(&File {
        path: PathBuf::from("marmosets"),
        is_executable: false,
      })
      .wait()
      .expect_err("Expected error");
  }

  #[test]
  fn stat_executable_file() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("photograph_marmosets");
    make_file(&dir.path().join(&path), &[], 0o700);
    assert_eq!(
      posix_fs.stat(path.clone()).unwrap(),
      super::Stat::File(File {
        path: path,
        is_executable: true,
      })
    )
  }

  #[test]
  fn stat_nonexecutable_file() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("marmosets");
    make_file(&dir.path().join(&path), &[], 0o600);
    assert_eq!(
      posix_fs.stat(path.clone()).unwrap(),
      super::Stat::File(File {
        path: path,
        is_executable: false,
      })
    )
  }

  #[test]
  fn stat_dir() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();
    assert_eq!(
      posix_fs.stat(path.clone()).unwrap(),
      super::Stat::Dir(Dir(path))
    )
  }

  #[test]
  fn stat_symlink() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("marmosets");
    make_file(&dir.path().join(&path), &[], 0o600);

    let link_path = PathBuf::from("remarkably_similar_marmoset");
    std::os::unix::fs::symlink(&dir.path().join(path), dir.path().join(&link_path)).unwrap();
    assert_eq!(
      posix_fs.stat(link_path.clone()).unwrap(),
      super::Stat::Link(Link(link_path))
    )
  }

  #[test]
  fn stat_other() {
    new_posixfs("/dev").stat(PathBuf::from("null")).expect_err(
      "Want error",
    );
  }

  #[test]
  fn stat_missing() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    let posix_fs = new_posixfs(&dir.path());
    posix_fs.stat(PathBuf::from("no_marmosets")).expect_err(
      "Want error",
    );
  }

  #[test]
  fn scandir_empty() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("empty_enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();
    assert_eq!(posix_fs.scandir(&Dir(path)).wait().unwrap(), vec![]);
  }

  #[test]
  fn scandir() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    let posix_fs = new_posixfs(&dir.path());
    let path = PathBuf::from("enclosure");
    std::fs::create_dir(dir.path().join(&path)).unwrap();

    let a_marmoset = path.join("a_marmoset");
    let feed = path.join("feed");
    let hammock = path.join("hammock");
    let remarkably_similar_marmoset = path.join("remarkably_similar_marmoset");
    let sneaky_marmoset = path.join("sneaky_marmoset");

    make_file(&dir.path().join(&feed), &[], 0o700);
    make_file(&dir.path().join(&a_marmoset), &[], 0o600);
    make_file(&dir.path().join(&sneaky_marmoset), &[], 0o600);
    std::os::unix::fs::symlink(
      &dir.path().join(&a_marmoset),
      dir.path().join(
        &dir.path().join(&remarkably_similar_marmoset),
      ),
    ).unwrap();
    std::fs::create_dir(dir.path().join(&hammock)).unwrap();
    make_file(
      &dir.path().join(&hammock).join("napping_marmoset"),
      &[],
      0o600,
    );

    assert_eq!(
      posix_fs.scandir(&Dir(path)).wait().unwrap(),
      vec![
        Stat::File(File {
          path: a_marmoset,
          is_executable: false,
        }),
        Stat::File(File {
          path: feed,
          is_executable: true,
        }),
        Stat::Dir(Dir(hammock)),
        Stat::Link(Link(remarkably_similar_marmoset)),
        Stat::File(File {
          path: sneaky_marmoset,
          is_executable: false,
        }),
      ]
    );
  }

  #[test]
  fn scandir_missing() {
    let dir = tempdir::TempDir::new("posixfs").unwrap();
    let posix_fs = new_posixfs(&dir.path());
    posix_fs
      .scandir(&Dir(PathBuf::from("no_marmosets_here")))
      .wait()
      .expect_err("Want error");
  }

  fn assert_only_file_is_executable(path: &Path, want_is_executable: bool) {
    let fs = new_posixfs(path);
    let stats = fs.scandir(&Dir(PathBuf::from("."))).wait().unwrap();
    assert_eq!(stats.len(), 1);
    match stats.get(0).unwrap() {
      &super::Stat::File(File { is_executable: got, .. }) => assert_eq!(want_is_executable, got),
      other => panic!("Expected file, got {:?}", other),
    }
  }

  fn new_posixfs<P: AsRef<Path>>(dir: P) -> PosixFS {
    PosixFS::new(
      dir.as_ref(),
      Arc::new(ResettablePool::new("test-pool-".to_string())),
      vec![],
    ).unwrap()
  }
}
