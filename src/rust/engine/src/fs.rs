use std::collections::HashSet;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::{fmt, fs, io};

use futures::future::{self, BoxFuture, Future};

use glob::{Pattern, PatternError};
use ordermap::OrderMap;
use sha2::{Sha256, Digest};
use tar;
use tempdir::TempDir;

#[derive(Clone, Eq, Hash, PartialEq)]
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

/**
 * A context for filesystem operations parameterized on an error type 'E'.
 */
pub trait FSContext<E: Send + Sync + 'static> : Clone + Send + Sync + 'static {
  fn read_link(&self, link: &Link) -> BoxFuture<PathBuf, E>;
  fn scandir(&self, dir: &Dir) -> BoxFuture<Vec<Stat>, E>;

  /**
   * Canonicalize the Link for the given Path to an underlying File or Dir. May result
   * in None if the PathStat represents a broken Link.
   *
   * TODO: Should handle symlink loops (which would exhibit as an infinite loop in expand_multi).
   */
  fn canonicalize(&self, symbolic_path: PathBuf, link: Link) -> BoxFuture<Option<PathStat>, E> {
    // Read the link, which may result in PathGlob(s) that match 0 or 1 Path.
    let context = self.clone();
    self.read_link(&link)
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

  fn directory_listing(&self, canonical_dir: &Dir, symbolic_path: PathBuf, wildcard: Pattern) -> BoxFuture<Vec<PathStat>, E> {
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
              // Canonicalize matched PathStats.
              // TODO: Boxing every Stat here, when technically we only need to box for Link
              // expansion. Could fix this by partitioning into Links and non-links first, but
              // that would lose ordering.
              match stat {
                Stat::Link(l) =>
                  context.canonicalize(stat_symbolic_path, l),
                Stat::Dir(d) =>
                  future::ok(Some(PathStat::dir(stat_symbolic_path.to_owned(), d))).boxed(),
                Stat::File(f) =>
                  future::ok(Some(PathStat::file(stat_symbolic_path.to_owned(), f))).boxed(),
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
   * Apply a PathGlob, returning either PathStats and PathGlobs on success or continuations
   * if more information is needed.
   */
  fn expand_single(&self, path_glob: PathGlob) -> BoxFuture<(Vec<PathStat>, Vec<PathGlob>), E> {
    match path_glob {
      PathGlob::Root =>
        // Always results in a single PathStat.
        future::ok((vec![PathGlob::root_stat()], vec![])).boxed(),
      PathGlob::Wildcard { canonical_dir, symbolic_path, wildcard } =>
        // Filter directory listing to return PathStats, with no continuation.
        self.directory_listing(&canonical_dir, symbolic_path, wildcard)
          .map(|path_stats| (path_stats, vec![]))
          .boxed(),
      PathGlob::DirWildcard { canonical_dir, symbolic_path, wildcard, remainder } =>
        // Filter directory listing and request additional PathGlobs for matched Dirs.
        self.directory_listing(&canonical_dir, symbolic_path, wildcard)
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

pub type Fingerprint = [u8;32];

pub struct Snapshot {
  pub fingerprint: Fingerprint,
  pub path_stats: Vec<PathStat>,
}

/**
 * A facade for the snapshot directory, which is currently thrown away at the end of
 * each run.
 */
struct SnapshotsInner {
  next_temp_id: usize,
  temp_dir: TempDir,
}

pub struct Snapshots {
  inner: Mutex<SnapshotsInner>,
}

impl Snapshots {
  pub fn new() -> Result<Snapshots, io::Error> {
    Ok(
      Snapshots {
        inner:
          Mutex::new(
            SnapshotsInner {
              next_temp_id: 0,
              temp_dir: TempDir::new("snapshots")?
            }
          ),
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

    let mut fingerprint: Fingerprint = [0;32];
    fingerprint.clone_from_slice(&hasher.result()[0..32]);
    Ok(fingerprint)
  }

  fn hex(fingerprint: &Fingerprint) -> String {
    let mut s = String::new();
    for &byte in fingerprint {
      fmt::Write::write_fmt(&mut s, format_args!("{:x}", byte)).unwrap();
    }
    s
  }

  /**
   * Append the given PathStat to the given Builder, (re)using the given Header.
   */
  fn tar_header_populate(head: &mut tar::Header, path_stat: &PathStat, relative_to: &Dir) -> Result<(), String> {
    let path =
      match path_stat {
        &PathStat::File { ref path, ref stat } => {
          head.set_entry_type(tar::EntryType::file());
          // TODO: Unnecessarily re-executing the syscall here. Could store the `size` info on
          // File stats to avoid this.
          let abs_path = relative_to.0.join(stat.0.as_path());
          head.set_size(
            abs_path.metadata()
              .map_err(|e| format!("Failed to stat {:?}: {:?}", stat, e))?
              .len()
          );
          path
        },
        &PathStat::Dir { ref path, .. } => {
          head.set_entry_type(tar::EntryType::dir());
          head.set_size(0);
          path
        },
      };
    head.set_path(path.as_path())
      .map_err(|e| format!("Illegal path {:?}: {:?}", path, e))?;
    head.set_cksum();
    Ok(())
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
    let mut head = tar::Header::new_ustar();
    for path in paths {
      // Populate the header for the File or Dir.
      Snapshots::tar_header_populate(&mut head, &path, relative_to)?;
      // And append.
      match path {
        &PathStat::File { ref stat, .. } => {
          let input =
            fs::File::open(relative_to.0.join(stat.0.as_path()))
              .map_err(|e| format!("Failed to open {:?}: {:?}", stat, e))?;
          tar_builder.append(&head, input)
            .map_err(|e| format!("Failed to tar {:?}: {:?}", stat, e))?;
        },
        &PathStat::Dir { ref stat, .. } => {
          tar_builder.append(&head, io::empty())
            .map_err(|e| format!("Failed to tar {:?}: {:?}", stat, e))?;
        },
      }
    }
    // Finish the tar file, allowing the underlying file to be closed.
    tar_builder.finish()
      .map_err(|e| format!("Failed to finalize snapshot tar: {:?}", e))?;
    Ok(())
  }

  /**
   * Returns the next temporary path, and the destination path prefix for Snapshots.
   */
  fn next_paths(&self) -> (PathBuf, PathBuf) {
    let (temp_id, temp_dir) = {
      let mut inner = self.inner.lock().unwrap();
      inner.next_temp_id += 1;
      (inner.next_temp_id, inner.temp_dir.path().to_owned())
    };

    (temp_dir.join(format!("{}.tar.tmp", temp_id)), temp_dir)
  }

  pub fn create(&self, build_root: &Dir, paths: Vec<PathStat>) -> Result<Snapshot, String> {
    // Write the tar (with timestamps cleared) to a temporary file.
    let (temp_path, mut dest_path) = self.next_paths();
    Snapshots::tar_create(temp_path.as_path(), &paths, build_root)?;

    // Fingerprint the tar file and then rename it to create the Snapshot.
    let fingerprint = Snapshots::fingerprint(temp_path.as_path())?;
    dest_path.push(format!("{:}.tar", Snapshots::hex(&fingerprint)));
    fs::rename(temp_path, dest_path)
      .map_err(|e| format!("Failed to finalize snapshot: {:?}", e))?;
    Ok(
      Snapshot {
        fingerprint: fingerprint,
        path_stats: paths,
      }
    )
  }
}
