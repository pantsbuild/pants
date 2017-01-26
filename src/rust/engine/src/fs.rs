use std::collections::HashSet;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::{fmt, fs, hash, io};

use globset::Glob;
use globset;
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

pub enum LinkExpansion {
  // Successfully resolved to a File.
  File(File),
  // Successfully resolved to a Dir.
  Dir(Dir),
  // Link destination does not exist.
  Broken,
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
  static ref SINGLE_DOT_GLOB: Glob = Glob::new(".").unwrap();
  static ref SINGLE_STAR_GLOB: Glob = Glob::new("*").unwrap();
  static ref DOUBLE_STAR: &'static str = "**";
  static ref DOUBLE_STAR_GLOB: Glob = Glob::new("**").unwrap();
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PathGlob {
  Root,
  Wildcard {
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Glob,
  },
  DirWildcard {
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Glob,
    remainder: Vec<Glob>,
  },
}

// TODO: `Glob` does not implement Hash.
//   see: https://github.com/BurntSushi/ripgrep/pull/339
impl hash::Hash for PathGlob {
  fn hash<H: hash::Hasher>(&self, state: &mut H) {
    let (cd, sp, w) =
      match self {
        &PathGlob::Root => {
          0.hash(state);
          return;
        },
        &PathGlob::Wildcard { ref canonical_dir, ref symbolic_path, ref wildcard } =>
          (canonical_dir, symbolic_path, wildcard),
        &PathGlob::DirWildcard { ref canonical_dir, ref symbolic_path, ref wildcard, ref remainder } => {
          for r in remainder {
            r.glob().hash(state);
          }
          (canonical_dir, symbolic_path, wildcard)
        }
      };
    cd.hash(state);
    sp.hash(state);
    w.glob().hash(state);
  }
}

impl PathGlob {
  pub fn root_stat() -> PathStat {
    PathStat::dir(PathBuf::new(), Dir(PathBuf::new()))
  }

  fn wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: Glob) -> PathGlob {
    PathGlob::Wildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
    }
  }

  fn dir_wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: Glob, remainder: Vec<Glob>) -> PathGlob {
    PathGlob::DirWildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
      remainder: remainder,
    }
  }

  pub fn create(filespecs: &Vec<String>) -> Result<Vec<PathGlob>, globset::Error> {
    let canonical_dir = Dir(PathBuf::new());
    let symbolic_path = PathBuf::new();
    let mut path_globs = Vec::new();
    for filespec in filespecs {
      path_globs.extend(PathGlob::parse(&canonical_dir, &symbolic_path, filespec)?);
    }
    Ok(path_globs)
  }

  /**
   * Eliminate consecutive '**'s to avoid repetitive traversing.
   */
  fn split_path(filespec: &String) -> Vec<&OsStr> {
    let mut parts: Vec<&OsStr> = Path::new(filespec).iter().collect();
    let mut idx = 1;
    while idx < parts.len() && *DOUBLE_STAR == parts[idx] {
      idx += 1;
    }
    parts.drain(..idx);
    parts
  }

  /**
   * Given a filespec String relative to a canonical Dir and path, parse it to a
   * series of PathGlob objects.
   */
  fn parse(canonical_dir: &Dir, symbolic_path: &Path, filespec: &String) -> Result<Vec<PathGlob>, globset::Error> {
    let mut parts = Vec::new();
    for part in PathGlob::split_path(filespec) {
      // NB: Because the filespec is a String input, calls to `to_str_lossy` are not lossy; the
      // use of `Path` is strictly for os-independent Path parsing.
      parts.push(Glob::new(&part.to_string_lossy())?);
    }
    Ok(PathGlob::parse_globs(canonical_dir, symbolic_path, &parts))
  }

  /**
   * Given a filespec as Globs, create a series of PathGlob objects.
   */
  fn parse_globs(canonical_dir: &Dir, symbolic_path: &Path, parts: &Vec<Glob>) -> Vec<PathGlob> {
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
  pub fn create(include: &Vec<String>, exclude: &Vec<String>) -> Result<PathGlobs, globset::Error> {
    Ok(
      PathGlobs {
        include: PathGlob::create(include)?,
        exclude: PathGlob::create(exclude)?,
      }
    )
  }
}

/**
 * A context for filesystem operations parameterized on a continuation type 'K'. An operation
 * resulting in K indicates that more information is needed to complete the operation.
 */
pub trait FSContext<K> {
  fn read_link(&self, link: &Link) -> Result<Vec<PathGlob>, K>;
  fn scandir(&self, dir: &Dir) -> Result<Vec<Stat>, K>;

  /**
   * Expand a symlink to an underlying non-link Stat.
   *
   * TODO: Should handle symlink loops (which would exhibit as infinite recursion here afaict.
   */
  fn expand_link(&self, link: &Link) -> Result<LinkExpansion, Vec<K>> {
    // Read the link, which may result in PathGlob(s) that match 0 or 1 Path.
    let link_globs = self.read_link(&link).map_err(|k| vec![k])?;

    // Assume either 0 or 1 destination (anything else would imply a symlink to a path
    // containing an escaped glob character... leaving that as a `TODO` I guess).
    match self.expand_multi(&link_globs)?.pop() {
      Some(PathStat::Dir { stat, .. }) =>
        Ok(LinkExpansion::Dir(stat)),
      Some(PathStat::File { stat, .. }) =>
        Ok(LinkExpansion::File(stat)),
      None =>
        Ok(LinkExpansion::Broken),
    }
  }

  /**
   * Canonicalize the Stat for the given PathStat to an underlying File or Dir. May result
   * in None if the PathStat represents a broken or cyclic Link.
   */
  fn canonicalize(&self, path: &Path, stat: &Link) -> Result<Option<PathStat>, Vec<K>> {
    match self.expand_link(stat)? {
      LinkExpansion::Broken => Ok(None),
      LinkExpansion::Dir(d) => Ok(Some(PathStat::dir(path.to_owned(), d))),
      LinkExpansion::File(f) => Ok(Some(PathStat::file(path.to_owned(), f))),
    }
  }

  fn directory_listing(&self, canonical_dir: &Dir, symbolic_path: &Path, wildcard: &Glob) -> Result<Vec<PathStat>, Vec<K>> {
    // List the directory, match any relevant Stats, and join them into PathStats.
    let glob_matcher = wildcard.compile_matcher();
    let matched =
      self.scandir(canonical_dir).map_err(|k| vec![k])?.into_iter()
        .filter(|stat| {
          // Match relevant filenames.
          stat.path().file_name().map(|file_name| glob_matcher.is_match(file_name)).unwrap_or(false)
        });

    // Batch-canonicalize matched PathStats.
    let mut path_stats = Vec::new();
    let mut continuations = Vec::new();
    for stat in matched {
      match stat {
        Stat::Link(l) =>
          match self.canonicalize(symbolic_path, &l) {
            Ok(Some(ps)) => path_stats.push(ps),
            Ok(None) => (),
            Err(ks) => continuations.extend(ks),
          },
        Stat::Dir(d) =>
          path_stats.push(PathStat::dir(symbolic_path.to_owned(), d)),
        Stat::File(f) =>
          path_stats.push(PathStat::file(symbolic_path.to_owned(), f)),
      };
    }

    // If there were no continuations, all PathStats were completely expanded.
    if continuations.is_empty() {
      Ok(path_stats)
    } else {
      Err(continuations)
    }
  }

  /**
   * Recursively expands PathGlobs into PathStats while applying excludes and building a set
   * of relevant dependencies.
   *
   * TODO: Eventually, it would be nice to be able to apply excludes as we go, to
   * avoid walking into directories that aren't relevant.
   */
  fn expand(&self, path_globs: &PathGlobs) -> Result<Vec<PathStat>, Vec<K>> {
    match (self.expand_multi(&path_globs.include), self.expand_multi(&path_globs.exclude)) {
      (Ok(include), Ok(exclude)) => {
        // Exclude matched paths.
        let exclude_set: HashSet<_> = exclude.into_iter().collect();
        Ok(include.into_iter().filter(|i| !exclude_set.contains(i)).collect())
      },
      (Err(include_deps), Err(exclude_deps)) =>
        // Both sets still need dependencies.
        Err(include_deps.into_iter().chain(exclude_deps.into_iter()).collect()),
      (include_res, exclude_res) =>
        // A mix of success and failure: return the first set of dependencies.
        include_res.and(exclude_res),
    }
  }

  /**
   * Recursively expands PathGlobs into PathStats, building a set of relevant dependencies.
   */
  fn expand_multi(&self, path_globs: &Vec<PathGlob>) -> Result<Vec<PathStat>, Vec<K>> {
    let mut dependencies = Vec::new();
    let mut path_globs_stack = path_globs.clone();
    let mut path_globs_set: HashSet<PathGlob> = HashSet::default();
    let mut outputs: OrderMap<PathStat, ()> = OrderMap::default();
    while let Some(path_glob) = path_globs_stack.pop() {
      if path_globs_set.contains(&path_glob) {
        continue;
      }

      // Compute matching PathStats and additional PathGlobs for each PathGlob.
      match self.expand_single(&path_glob) {
        Ok((path_stats, path_globs)) => {
          outputs.extend(path_stats.into_iter().map(|k| (k, ())));
          path_globs_stack.extend(path_globs);
        },
        Err(nodes) => {
          dependencies.extend(nodes);
          continue;
        },
      };

      // Ensure that we do not re-visit this PathGlob.
      path_globs_set.insert(path_glob);
    }

    if dependencies.is_empty() {
      Ok(outputs.into_iter().map(|(k, _)| k).collect())
    } else {
      Err(dependencies)
    }
  }

  /**
   * Apply a PathGlob, returning either PathStats and PathGlobs on success or continuations
   * if more information is needed.
   */
  fn expand_single(&self, path_glob: &PathGlob) -> Result<(Vec<PathStat>, Vec<PathGlob>), Vec<K>> {
    match path_glob {
      &PathGlob::Root =>
        // Always results in a single PathStat.
        Ok((vec![PathGlob::root_stat()], vec![])),
      &PathGlob::Wildcard { ref canonical_dir, ref symbolic_path, ref wildcard } =>
        // Filter directory listing to return PathStats, with no continuation.
        self.directory_listing(canonical_dir, symbolic_path.as_path(), wildcard)
          .map(|path_stats| (path_stats, vec![])),
      &PathGlob::DirWildcard { ref canonical_dir, ref symbolic_path, ref wildcard, ref remainder } =>
        // Filter directory listing and request additional PathGlobs for matched Dirs.
        self.directory_listing(canonical_dir, symbolic_path.as_path(), wildcard)
          .map(|path_stats| {
            path_stats.into_iter()
              .filter_map(|ps| {
                match ps {
                  PathStat::Dir { ref path, ref stat } =>
                    Some(PathGlob::parse_globs(stat, path.as_path(), remainder)),
                  _ => None,
                }
              })
              .flat_map(|path_globs| path_globs.into_iter())
              .collect()
          })
          .map(|path_globs| (vec![], path_globs)),
    }
  }
}

pub type Fingerprint = [u8;32];

pub struct Snapshot {
  pub fingerprint: Fingerprint,
  pub path_stats: Vec<PathStat>,
}

impl Snapshot {
  /**
   * Fingerprint the given path ,or return an error string.
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
      fs::File::create(dest)
        .map_err(|e| format!("Failed to create destination file: {:?}", e))?;
    let mut tar_builder = tar::Builder::new(dest_file);
    let mut head = tar::Header::new_gnu();
    for path in paths {
      // Populate the header for the File or Dir.
      Snapshot::tar_header_populate(&mut head, &path, relative_to)?;
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

  pub fn create(snapshot_root: &Dir, build_root: &Dir, paths: Vec<PathStat>) -> Result<Snapshot, String> {
    // Write the tar (with timestamps cleared) to a temporary file.
    let temp_dir =
      fs::create_dir_all(snapshot_root.0.as_path())
        .and_then(|_| {
          TempDir::new_in(snapshot_root.0.as_path(), ".create")
        })
        .map_err(|e| format!("Failed to create tempdir: {:?}", e))?;
    let temp_path = temp_dir.path().join("snapshot.tar");
    Snapshot::tar_create(temp_path.as_path(), &paths, build_root)?;

    // Fingerprint the tar file and then rename it to create the Snapshot.
    let fingerprint = Snapshot::fingerprint(temp_path.as_path())?;
    let final_path = snapshot_root.0.join(format!("{:}.tar", Snapshot::hex(&fingerprint)));
    fs::rename(temp_path, final_path)
      .map_err(|e| format!("Failed to finalize snapshot: {:?}", e))?;
    Ok(
      Snapshot {
        fingerprint: fingerprint,
        path_stats: paths,
      }
    )
  }
}
