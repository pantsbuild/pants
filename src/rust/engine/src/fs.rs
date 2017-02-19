use std::collections::HashSet;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::sync::{atomic, RwLock, RwLockReadGuard};
use std::{fmt, fs, io};

use futures::future::{self, BoxFuture, Future};
use futures_cpupool::{self, CpuFuture, CpuPool};
use glob::{Pattern, PatternError};
use ignore::gitignore::{Gitignore, GitignoreBuilder};
use ignore;
use ordermap::OrderMap;
use sha2::{Sha256, Digest};
use tar;
use tempdir::TempDir;

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum Stat {
  Link(Link),
  Dir(Dir),
  File(File),
}

impl Stat {
  fn path(&self) -> &PathBuf {
    match self {
      &Stat::Dir(Dir(ref p)) => p,
      &Stat::File(File(ref p)) => p,
      &Stat::Link(Link(ref p)) => p,
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Link(pub PathBuf);

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Dir(pub PathBuf);

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct File(pub PathBuf);

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
  }
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
}

lazy_static! {
  static ref SINGLE_DOT_GLOB: Pattern = Pattern::new(".").unwrap();
  static ref SINGLE_STAR_GLOB: Pattern = Pattern::new("*").unwrap();
  static ref DOUBLE_STAR: &'static str = "**";
  static ref DOUBLE_STAR_GLOB: Pattern = Pattern::new("**").unwrap();
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum PathGlob {
  Root,
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
  pub fn root_stat() -> PathStat {
    PathStat::dir(PathBuf::new(), Dir(PathBuf::new()))
  }

  fn wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: Pattern) -> PathGlob {
    PathGlob::Wildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
    }
  }

  fn dir_wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: Pattern, remainder: Vec<Pattern>) -> PathGlob {
    PathGlob::DirWildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
      remainder: remainder,
    }
  }

  pub fn create(filespecs: &Vec<String>) -> Result<Vec<PathGlob>, PatternError> {
    let canonical_dir = Dir(PathBuf::new());
    let symbolic_path = PathBuf::new();
    let mut path_globs = Vec::new();
    for filespec in filespecs {
      path_globs.extend(PathGlob::parse(&canonical_dir, &symbolic_path, filespec)?);
    }
    Ok(path_globs)
  }

  /**
   * Split a filespec string into path components while eliminating
   * consecutive '**'s (to avoid repetitive traversing).
   */
  fn split_path(filespec: &str) -> Vec<&OsStr> {
    let mut out = Vec::new();
    let mut prev_was_doublestar = false;
    for part in Path::new(filespec).iter() {
      let cur_is_doublestar = *DOUBLE_STAR == part;
      if prev_was_doublestar && cur_is_doublestar {
        continue;
      }
      out.push(part);
      prev_was_doublestar = cur_is_doublestar;
    }
    out
  }

  /**
   * Given a filespec String relative to a canonical Dir and path, parse it to a
   * series of PathGlob objects.
   */
  fn parse(canonical_dir: &Dir, symbolic_path: &Path, filespec: &str) -> Result<Vec<PathGlob>, PatternError> {
    let mut parts = Vec::new();
    for part in PathGlob::split_path(filespec) {
      // NB: Because the filespec is a String input, calls to `to_str_lossy` are not lossy; the
      // use of `Path` is strictly for os-independent Path parsing.
      parts.push(Pattern::new(&part.to_string_lossy())?);
    }
    Ok(PathGlob::parse_globs(canonical_dir, symbolic_path, &parts))
  }

  /**
   * Given a filespec as Patterns, create a series of PathGlob objects.
   */
  fn parse_globs(canonical_dir: &Dir, symbolic_path: &Path, parts: &Vec<Pattern>) -> Vec<PathGlob> {
    if canonical_dir.0.as_os_str() == "." && parts.len() == 1 && *SINGLE_DOT_GLOB == parts[0] {
      // A request for the root path.
      vec![PathGlob::Root]
    } else if *DOUBLE_STAR_GLOB == parts[0] {
      if parts.len() == 1 {
        // Per https://git-scm.com/docs/gitignore:
        //  "A trailing '/**' matches everything inside. For example, 'abc/**' matches all files inside
        //   directory "abc", relative to the location of the .gitignore file, with infinite depth."
        return vec![
          PathGlob::dir_wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            SINGLE_STAR_GLOB.clone(),
            vec![DOUBLE_STAR_GLOB.clone()]
          ),
          PathGlob::wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            SINGLE_STAR_GLOB.clone()
          ),
        ];
      }

      // There is a double-wildcard in a dirname of the path: double wildcards are recursive,
      // so there are two remainder possibilities: one with the double wildcard included, and the
      // other without.
      let pathglob_with_doublestar =
        PathGlob::dir_wildcard(
          canonical_dir.clone(),
          symbolic_path.to_owned(),
          SINGLE_STAR_GLOB.clone(),
          parts[0..].to_vec()
        );
      let pathglob_no_doublestar =
        if parts.len() == 2 {
          PathGlob::wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            parts[1].clone()
          )
        } else {
          PathGlob::dir_wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            parts[1].clone(),
            parts[2..].to_vec()
          )
        };
      vec![pathglob_with_doublestar, pathglob_no_doublestar]
    } else if parts.len() == 1 {
      // This is the path basename.
      vec![
        PathGlob::wildcard(
          canonical_dir.clone(),
          symbolic_path.to_owned(),
          parts[0].clone()
        )
      ]
    } else {
      // This is a path dirname.
      vec![
        PathGlob::dir_wildcard(
          canonical_dir.clone(),
          symbolic_path.to_owned(),
          parts[0].clone(),
          parts[1..].to_vec()
        )
      ]
    }
  }
}

#[derive(Debug)]
pub struct PathGlobs {
  include: Vec<PathGlob>,
  exclude: Vec<PathGlob>,
}

impl PathGlobs {
  pub fn create(include: &Vec<String>, exclude: &Vec<String>) -> Result<PathGlobs, PatternError> {
    Ok(
      PathGlobs {
        include: PathGlob::create(include)?,
        exclude: PathGlob::create(exclude)?,
      }
    )
  }
}

#[derive(Debug)]
struct PathGlobsExpansion<T: Sized> {
  context: T,
  // Globs that have yet to be expanded, in order.
  todo: Vec<PathGlob>,
  // Globs that have already been expanded.
  completed: HashSet<PathGlob>,
  // Unique Paths that have been matched, in order.
  outputs: OrderMap<PathStat, ()>,
}

pub struct PosixFS {
  build_root: Dir,
  // The pool needs to be reinitialized after a fork, so it is protected by a lock.
  pool: RwLock<CpuPool>,
  pub ignore: Gitignore,
}

impl PosixFS {
  pub fn new(
    build_root: PathBuf,
    ignore_patterns: Vec<String>,
  ) -> Result<PosixFS, String> {
    let pool = RwLock::new(PosixFS::create_pool());
    let canonical_build_root =
      build_root.canonicalize().and_then(|canonical|
        canonical.metadata().and_then(|metadata|
          if metadata.is_dir() {
            Ok(Dir(canonical))
          } else {
            Err(io::Error::new(io::ErrorKind::InvalidInput, "Not a directory."))
          }
        )
      )
      .map_err(|e| format!("Could not canonicalize build root {:?}: {:?}", build_root, e))?;

    let ignore =
      PosixFS::create_ignore(&canonical_build_root, &ignore_patterns)
        .map_err(|e|
          format!("Could not parse build ignore inputs {:?}: {:?}", ignore_patterns, e)
        )?;
    Ok(
      PosixFS {
        build_root: canonical_build_root,
        pool: pool,
        ignore: ignore,
      }
    )
  }

  fn create_pool() -> CpuPool {
    futures_cpupool::Builder::new()
      .name_prefix("engine-")
      .create()
  }

  fn create_ignore(root: &Dir, patterns: &Vec<String>) -> Result<Gitignore, ignore::Error> {
    let mut ignore_builder = GitignoreBuilder::new(root.0.as_path());
    for pattern in patterns {
      ignore_builder.add_line(None, pattern.as_str())?;
    }
    ignore_builder
      .build()
  }

  fn scandir_sync(dir: Dir, dir_abs: PathBuf) -> Result<Vec<Stat>, io::Error> {
    let mut stats = Vec::new();
    for dir_entry_res in dir_abs.read_dir()? {
      let dir_entry = dir_entry_res?;
      let path = dir.0.join(dir_entry.file_name());
      let file_type = dir_entry.file_type()?;
      if file_type.is_dir() {
        stats.push(Stat::Dir(Dir(path)));
      } else if file_type.is_file() {
        stats.push(Stat::File(File(path)));
      } else if file_type.is_symlink() {
        stats.push(Stat::Link(Link(path)));
      }
      // Else: ignore.
    }
    stats.sort_by(|s1, s2| s1.path().cmp(s2.path()));
    Ok(stats)
  }

  fn pool(&self) -> RwLockReadGuard<CpuPool> {
    self.pool.read().unwrap()
  }

  pub fn post_fork(&self) {
    let mut pool = self.pool.write().unwrap();
    *pool = PosixFS::create_pool();
  }

  pub fn read_link(&self, link: &Link) -> BoxFuture<PathBuf, io::Error> {
    let link_parent = link.0.parent().map(|p| p.to_owned());
    let link_abs = self.build_root.0.join(link.0.as_path()).to_owned();
    self.pool()
      .spawn_fn(move || {
        link_abs
          .read_link()
          .and_then(|path_buf| {
            if path_buf.is_absolute() {
              Err(
                io::Error::new(
                  io::ErrorKind::InvalidData, format!("Absolute symlink: {:?}", link_abs)
                )
              )
            } else {
              link_parent
                .map(|parent| parent.join(path_buf))
                .ok_or_else(|| {
                  io::Error::new(
                    io::ErrorKind::InvalidData, format!("Symlink without a parent?: {:?}", link_abs)
                  )
                })
            }
          })
      })
      .boxed()
  }

  pub fn scandir(&self, dir: &Dir) -> BoxFuture<Vec<Stat>, io::Error> {
    let dir = dir.to_owned();
    let dir_abs = self.build_root.0.join(dir.0.as_path());
    self.pool()
      .spawn_fn(move || {
        PosixFS::scandir_sync(dir, dir_abs)
      })
      .boxed()
  }
}

/**
 * A context for filesystem operations parameterized on an error type 'E'.
 */
pub trait VFS<E: Send + Sync + 'static> : Clone + Send + Sync + 'static {
  fn read_link(&self, link: Link) -> BoxFuture<PathBuf, E>;
  fn scandir(&self, dir: Dir) -> BoxFuture<Vec<Stat>, E>;
  fn ignore<P: AsRef<Path>>(&self, path: P, is_dir: bool) -> bool;

  /**
   * Canonicalize the Link for the given Path to an underlying File or Dir. May result
   * in None if the PathStat represents a broken Link.
   *
   * Skips ignored paths both before and after expansion.
   *
   * TODO: Should handle symlink loops (which would exhibit as an infinite loop in expand_multi).
   */
  fn canonicalize(&self, symbolic_path: PathBuf, link: Link) -> BoxFuture<Option<PathStat>, E> {
    // Read the link, which may result in PathGlob(s) that match 0 or 1 Path.
    let context = self.clone();
    self.read_link(link)
      .map(|dest_path| {
        // If the link destination can't be parsed as PathGlob(s), it is broken.
        dest_path.to_str()
          .and_then(|dest_str| {
            PathGlob::create(&vec![dest_str.to_string()]).ok()
          })
          .unwrap_or_else(|| vec![])
      })
      .and_then(move |link_globs| {
        context.expand_multi(link_globs)
      })
      .map(|mut path_stats| {
        // Assume either 0 or 1 destination (anything else would imply a symlink to a path
        // containing an escaped glob character... leaving that as a `TODO` I guess).
        path_stats.pop().map(|ps| {
          // Merge the input symbolic Path to the underlying Stat.
          match ps {
            PathStat::Dir { stat, .. } => PathStat::dir(symbolic_path, stat),
            PathStat::File { stat, .. } => PathStat::file(symbolic_path, stat),
          }
        })
      })
      .boxed()
  }

  fn directory_listing(&self, canonical_dir: Dir, symbolic_path: PathBuf, wildcard: Pattern) -> BoxFuture<Vec<PathStat>, E> {
    // List the directory.
    let context = self.clone();
    self.scandir(canonical_dir)
      .and_then(move |dir_listing| {
        // Match any relevant Stats, and join them into PathStats.
        future::join_all(
          dir_listing.into_iter()
            .filter(|stat| {
              // Match relevant filenames.
              stat.path().file_name()
                .map(|file_name| wildcard.matches_path(Path::new(file_name)))
                .unwrap_or(false)
            })
            .filter_map(|stat| {
              // Append matched filenames.
              stat.path().file_name()
                .map(|file_name| {
                  symbolic_path.join(file_name)
                })
                .map(|symbolic_stat_path| {
                  (symbolic_stat_path, stat)
                })
            })
            .map(|(stat_symbolic_path, stat)| {
              // Canonicalize matched PathStats, and filter ignored paths. Note that we ignore
              // links both before and after expansion.
              match stat {
                Stat::Link(l) => {
                  if context.ignore(l.0.as_path(), false) {
                    future::ok(None).boxed()
                  } else {
                    context.canonicalize(stat_symbolic_path, l)
                  }
                },
                Stat::Dir(d) => {
                  let res =
                    if context.ignore(d.0.as_path(), true) {
                      None
                    } else {
                      Some(PathStat::dir(stat_symbolic_path.to_owned(), d))
                    };
                  future::ok(res).boxed()
                },
                Stat::File(f) => {
                  let res =
                    if context.ignore(f.0.as_path(), false) {
                      None
                    } else {
                      Some(PathStat::file(stat_symbolic_path.to_owned(), f))
                    };
                  future::ok(res).boxed()
                },
              }
            })
            .collect::<Vec<_>>()
        )
      })
      .map(|path_stats| {
        // See the TODO above.
        path_stats.into_iter().filter_map(|pso| pso).collect()
      })
      .boxed()
  }

  /**
   * Recursively expands PathGlobs into PathStats while applying excludes.
   *
   * TODO: Eventually, it would be nice to be able to apply excludes as we go, to
   * avoid walking into directories that aren't relevant.
   */
  fn expand(&self, path_globs: PathGlobs) -> BoxFuture<Vec<PathStat>, E> {
    self.expand_multi(path_globs.include).join(self.expand_multi(path_globs.exclude))
      .map(|(include, exclude)| {
        // Exclude matched paths.
        let exclude_set: HashSet<_> = exclude.into_iter().collect();
        include.into_iter().filter(|i| !exclude_set.contains(i)).collect()
      })
      .boxed()
  }

  /**
   * Recursively expands PathGlobs into PathStats.
   */
  fn expand_multi(&self, path_globs: Vec<PathGlob>) -> BoxFuture<Vec<PathStat>, E> {
    if path_globs.is_empty() {
      return future::ok(vec![]).boxed();
    }

    let init =
      PathGlobsExpansion {
        context: self.clone(),
        todo: path_globs,
        completed: HashSet::default(),
        outputs: OrderMap::default()
      };
    future::loop_fn(init, |mut expansion| {
      // Request the expansion of all outstanding PathGlobs as a batch.
      let round =
        future::join_all({
          let context = &expansion.context;
          expansion.todo.drain(..)
            .map(|path_glob| context.expand_single(path_glob))
            .collect::<Vec<_>>()
        });
      round
        .map(move |paths_and_globs| {
          // Collect distinct new PathStats and PathGlobs
          for (paths, globs) in paths_and_globs.into_iter() {
            expansion.outputs.extend(paths.into_iter().map(|p| (p, ())));
            let completed = &mut expansion.completed;
            expansion.todo.extend(
              globs.into_iter()
                .filter(|pg| completed.insert(pg.clone()))
            );
          }

          // If there were any new PathGlobs, continue the expansion.
          if expansion.todo.is_empty() {
            future::Loop::Break(expansion)
          } else {
            future::Loop::Continue(expansion)
          }
        })
    })
    .map(|expansion| {
      assert!(
        expansion.todo.is_empty(),
        "Loop shouldn't have exited with work to do: {:?}",
        expansion.todo,
      );
      // Finally, capture the resulting PathStats from the expansion.
      expansion.outputs.into_iter().map(|(k, _)| k).collect()
    })
    .boxed()
  }

  /**
   * Apply a PathGlob, returning PathStats and additional PathGlobs that are needed for the
   * expansion.
   */
  fn expand_single(&self, path_glob: PathGlob) -> BoxFuture<(Vec<PathStat>, Vec<PathGlob>), E> {
    match path_glob {
      PathGlob::Root =>
        // Always results in a single PathStat.
        future::ok((vec![PathGlob::root_stat()], vec![])).boxed(),
      PathGlob::Wildcard { canonical_dir, symbolic_path, wildcard } =>
        // Filter directory listing to return PathStats, with no continuation.
        self.directory_listing(canonical_dir, symbolic_path, wildcard)
          .map(|path_stats| (path_stats, vec![]))
          .boxed(),
      PathGlob::DirWildcard { canonical_dir, symbolic_path, wildcard, remainder } =>
        // Filter directory listing and request additional PathGlobs for matched Dirs.
        self.directory_listing(canonical_dir, symbolic_path, wildcard)
          .map(move |path_stats| {
            path_stats.into_iter()
              .filter_map(|ps| {
                match ps {
                  PathStat::Dir { ref path, ref stat } =>
                    Some(PathGlob::parse_globs(stat, path.as_path(), &remainder)),
                  _ => None,
                }
              })
              .flat_map(|path_globs| path_globs.into_iter())
              .collect()
          })
          .map(|path_globs| (vec![], path_globs))
          .boxed(),
    }
  }
}

pub struct FileContent {
  pub path: PathBuf,
  pub content: Vec<u8>,
}

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub struct Fingerprint(pub [u8;32]);

impl Fingerprint {
  pub fn from_bytes_unsafe(bytes: &[u8]) -> Fingerprint {
    if bytes.len() != 32 {
      panic!("Input value was not a fingerprint; had length: {}", bytes.len());
    }

    let mut fingerprint = [0;32];
    fingerprint.clone_from_slice(&bytes[0..32]);
    Fingerprint(fingerprint)
  }

  pub fn to_hex(&self) -> String {
    let mut s = String::new();
    for &byte in self.0.iter() {
      fmt::Write::write_fmt(&mut s, format_args!("{:x}", byte)).unwrap();
    }
    s
  }
}

#[derive(Clone)]
pub struct Snapshot {
  pub fingerprint: Fingerprint,
  pub path_stats: Vec<PathStat>,
}

impl fmt::Debug for Snapshot {
  fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
    write!(f, "Snapshot({}, entries={})", self.fingerprint.to_hex(), self.path_stats.len())
  }
}

/**
 * A facade for the snapshot directory, which is currently thrown away at the end of each run.
 */
pub struct Snapshots {
  temp_dir: TempDir,
  next_temp_id: atomic::AtomicUsize,
}

impl Snapshots {
  pub fn new() -> Result<Snapshots, io::Error> {
    Ok(
      Snapshots {
        temp_dir: TempDir::new("snapshots")?,
        next_temp_id: atomic::AtomicUsize::new(0),
      }
    )
  }

  /**
   * Fingerprint the given path or return an error string.
   */
  fn fingerprint(path: &Path) -> Result<Fingerprint, String> {
    let mut hasher = Sha256::new();

    let mut file =
      fs::File::open(path)
        .map_err(|e| format!("Could not open snapshot for fingerprinting: {:?}", e))?;
    let mut buffer = [0;4096];
    loop {
      match io::Read::read(&mut file, &mut buffer) {
        Ok(len) if len > 0 =>
          hasher.input(&buffer[..len]),
        Ok(_) =>
          // EOF
          break,
        Err(e) =>
          return Err(format!("Could not read from snapshot: {:?}", e)),
      }
    };


    Ok(Fingerprint::from_bytes_unsafe(&hasher.result()))
  }

  /**
   * Create a tar file at the given path containing the given paths, or return an error string.
   */
  fn tar_create(dest: &Path, paths: &Vec<PathStat>, relative_to: &Dir) -> Result<(), String> {
    let dest_file =
      io::BufWriter::new(
        fs::File::create(dest)
          .map_err(|e| format!("Failed to create destination file: {:?}", e))?
      );
    let mut tar_builder = tar::Builder::new(dest_file);
    tar_builder.mode(tar::HeaderMode::Deterministic);
    for path_stat in paths {
      // Append the PathStat using the symbolic name and underlying stat.
      match path_stat {
        &PathStat::File { ref path, ref stat } => {
          let mut input =
            fs::File::open(relative_to.0.join(stat.0.as_path()))
              .map_err(|e| format!("Failed to open {:?}: {:?}", path_stat, e))?;
          tar_builder.append_file(path, &mut input)
            .map_err(|e| format!("Failed to tar {:?}: {:?}", path_stat, e))?;
        },
        &PathStat::Dir { ref path, ref stat } => {
          tar_builder.append_dir(path, stat.0.as_path())
            .map_err(|e| format!("Failed to tar {:?}: {:?}", path_stat, e))?;
        },
      }
    }
    // Finish the tar file, allowing the underlying file to be closed.
    tar_builder.finish()
      .map_err(|e| format!("Failed to finalize snapshot tar: {:?}", e))?;
    Ok(())
  }

  fn path_for(&self, fingerprint: &Fingerprint) -> PathBuf {
    Snapshots::path_under_for(self.temp_dir.path(), fingerprint)
  }

  fn path_under_for(path: &Path, fingerprint: &Fingerprint) -> PathBuf {
    path.join(format!("{}.tar", fingerprint.to_hex()))
  }

  /**
   * Creates a Snapshot for the given paths under the given VFS.
   */
  pub fn create(&self, fs: &PosixFS, paths: Vec<PathStat>) -> CpuFuture<Snapshot, String> {
    let dest_dir = self.temp_dir.path().to_owned();
    let build_root = fs.build_root.clone();
    let temp_path = {
      let next_temp_id = self.next_temp_id.fetch_add(1, atomic::Ordering::SeqCst);
      self.temp_dir.path().join(format!("{}.tar.tmp", next_temp_id))
    };

    fs.pool().spawn_fn(move || {
      // Write the tar (with timestamps cleared) to a temporary file.
      Snapshots::tar_create(temp_path.as_path(), &paths, &build_root)?;

      // Fingerprint the resulting tar file.
      let fingerprint = Snapshots::fingerprint(temp_path.as_path())?;
      let dest_path = Snapshots::path_under_for(&dest_dir, &fingerprint);

      // Rename to the final path if it does not already exist.
      if dest_path.is_file() {
        fs::remove_file(temp_path).unwrap_or(());
      } else {
        fs::rename(temp_path, dest_path)
          .map_err(|e| format!("Failed to finalize snapshot: {:?}", e))?;
      }

      Ok(
        Snapshot {
          fingerprint: fingerprint,
          path_stats: paths,
        }
      )
    })
  }

  fn contents_for_sync(snapshot: Snapshot, path: PathBuf) -> Result<Vec<FileContent>, io::Error> {
    let mut archive = fs::File::open(path).map(|f| tar::Archive::new(f))?;

    // Zip the in-memory Snapshot to the on disk representation, validating as we go.
    let mut files_content = Vec::new();
    for (entry_res, path_stat) in archive.entries()?.zip(snapshot.path_stats.into_iter()) {
      let mut entry = entry_res?;
      if entry.header().entry_type() == tar::EntryType::file() {
        let path =
          match path_stat {
            PathStat::File { path, .. } => path,
            PathStat::Dir { .. } => panic!("Snapshot contents changed after storage."),
          };
        let mut content = Vec::new();
        io::Read::read_to_end(&mut entry, &mut content)?;
        files_content.push(
          FileContent {
            path: path,
            content: content,
          }
        );
      }
    }
    Ok(files_content)
  }

  pub fn contents_for(&self, fs: &PosixFS, snapshot: Snapshot) -> CpuFuture<Vec<FileContent>, String> {
    let archive_path = self.path_for(&snapshot.fingerprint);
    fs.pool().spawn_fn(move || {
      let snapshot_str = format!("{:?}", snapshot);
      Snapshots::contents_for_sync(snapshot, archive_path)
        .map_err(|e| format!("Failed to open Snapshot {}: {:?}", snapshot_str, e))
    })
  }
}
