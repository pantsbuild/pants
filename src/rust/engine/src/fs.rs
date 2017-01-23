use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::hash;

use globset::Glob;
use globset;
use tar;

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
}

#[derive(Clone, Eq, Hash, PartialEq)]
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

#[derive(Clone, Eq, PartialEq)]
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
}

pub struct PathGlobs(pub Vec<PathGlob>);

lazy_static! {
  static ref SINGLE_DOT_GLOB: Glob = Glob::new(".").unwrap();
  static ref SINGLE_STAR_GLOB: Glob = Glob::new("*").unwrap();
  static ref DOUBLE_STAR: &'static str = "**";
  static ref DOUBLE_STAR_GLOB: Glob = Glob::new("**").unwrap();
}

impl PathGlobs {
  pub fn create(relative_to: &Dir, filespecs: &Vec<String>) -> Result<PathGlobs, globset::Error> {
    let mut path_globs = Vec::new();
    for filespec in filespecs {
      path_globs.extend(
        PathGlobs::parse(relative_to, relative_to.0.as_path(), filespec)?
      );
    }
    Ok(PathGlobs(path_globs))
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
   * Given a filespec String, parse it to a series of PathGlob objects.
   */
  fn parse(canonical_dir: &Dir, symbolic_path: &Path, filespec: &String) -> Result<Vec<PathGlob>, globset::Error> {
    let mut parts = Vec::new();
    for part in PathGlobs::split_path(filespec) {
      // NB: Because the filespec is a String input, calls to `to_str_lossy` are not lossy; the
      // use of `Path` is strictly for os-independent Path parsing.
      parts.push(Glob::new(&part.to_string_lossy())?);
    }
    Ok(PathGlobs::expand(canonical_dir, symbolic_path, &parts))
  }

  /**
   * Given a filespec String, parse it to a series of PathGlob objects.
   */
  fn expand(canonical_dir: &Dir, symbolic_path: &Path, parts: &Vec<Glob>) -> Vec<PathGlob> {
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

/**
 * A context for filesystem operations parameterized on a continuation type 'K'. An operation
 * resulting in K indicates that more information is needed to complete the operation.
 */
pub trait FSContext<K> {
  fn read_link(&self, link: &Link) -> Result<PathBuf, K>;
  fn stat(&self, path: &Path) -> Result<Stat, K>;
  fn scandir(&self, dir: &Dir) -> Result<Vec<Stat>, K>;

  /**
   * Recursively expand a symlink to an underlying non-link Stat.
   *
   * TODO: Should handle symlink loops, but probably not here... this will not
   * detect a loop that traverses multiple directories.
   */
  fn expand_link(&self, link: &Link) -> Result<LinkExpansion, K> {
    let mut link: Link = (*link).clone();
    loop {
      // Read the link and stat the destination.
      match self.stat(self.read_link(&link)?.as_path()) {
        Ok(Stat::Link(l)) => {
          // The link pointed to another link. Continue.
          link = l;
        },
        Ok(Stat::Dir(d)) =>
          return Ok(LinkExpansion::Dir(d)),
        Ok(Stat::File(f)) =>
          return Ok(LinkExpansion::File(f)),
        Err(t) =>
          return Err(t),
      };
    }
  }

  /**
   * Canonicalize the Stat for the given PathStat to an underlying File or Dir. May result
   * in None if the PathStat represents a Link containing a cycle.
   */
  fn canonicalize(&self, path: &Path, stat: &Link) -> Result<PathStat, K> {
    match self.expand_link(stat)? {
      LinkExpansion::Dir(d) => Ok(PathStat::dir(path.to_owned(), d)),
      LinkExpansion::File(f) => Ok(PathStat::file(path.to_owned(), f)),
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
            Ok(ps) => path_stats.push(ps),
            Err(k) => continuations.push(k),
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
   * Apply a PathGlob, returning either PathStats and PathGlobs on success or continuations
   * if more information is needed.
   */
  fn apply_path_glob(&self, path_glob: &PathGlob) -> Result<(Vec<PathStat>, Vec<PathGlob>), Vec<K>> {
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
                    Some(PathGlobs::expand(stat, path.as_path(), remainder)),
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

struct Snapshot {
  fingerprint: [u8;32],
  paths: Vec<PathStat>,
}

/*
impl Snapshot {
  fn create(paths: Vec<PathStat>) -> Snapshot {
    
  }
}
*/
