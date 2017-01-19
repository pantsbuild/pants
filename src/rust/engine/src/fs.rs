use std::ffi::OsStr;
use std::path::{Path, PathBuf};

use globset::Glob;
use globset;

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

enum LinkExpansion {
  // Successfully resolved to a File.
  File(File),
  // Successfully resolved to a Dir.
  Dir(Dir),
}

#[derive(Clone, Eq, Hash, PartialEq)]
pub struct PathStat {
  // The symbolic name of some filesystem Path, which is context specific.
  pub path: PathBuf,
  // The canonical Stat that underlies the Path.
  pub stat: Stat,
}

impl PathStat {
  fn new(path: PathBuf, stat: Stat) -> PathStat {
    PathStat {
      path: path,
      stat: stat,
    }
  }
}

#[derive(Clone)]
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
    remainder: PathBuf,
  },
}

impl PathGlob {
  pub fn root_stat() -> PathStat {
    PathStat {
      path: PathBuf::new(),
      stat: Stat::Dir(Dir(PathBuf::new())),
    }
  }

  fn wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: Glob) -> PathGlob {
    PathGlob::Wildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
    }
  }

  fn dir_wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: Glob, remainder: PathBuf) -> PathGlob {
    PathGlob::DirWildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
      remainder: remainder,
    }
  }
}

pub struct PathGlobs(pub Vec<PathGlob>);

const SINGLE_STAR: &'static str ="*";
const DOUBLE_STAR: &'static str = "**";

fn join(components: &[&OsStr]) -> PathBuf {
  let mut out = PathBuf::new();
  for component in components {
    out.push(component);
  }
  out
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
  fn normalize_doublestar(parts: &mut Vec<&OsStr>) {
    let mut idx = 1;
    while idx < parts.len() && DOUBLE_STAR == parts[idx] {
      idx += 1;
    }
    parts.drain(..idx);
  }

  /**
   * Given a filespec String, parse it to a series of PathGlob objects.
   */
  fn parse(canonical_dir: &Dir, symbolic_path: &Path, filespec: &String) -> Result<Vec<PathGlob>, globset::Error> {
    // NB: Because the filespec is a String input, calls to `to_str_lossy` below are never lossy; the
    // use of `Path` is strictly for os-independent Path parsing.
    let lossy_glob = |s: &OsStr| { Glob::new(&s.to_string_lossy()) };

    let mut parts: Vec<&OsStr> = Path::new(filespec).iter().collect();
    PathGlobs::normalize_doublestar(&mut parts);

    if canonical_dir.0.as_os_str() == "." && parts.len() == 1 && parts[0] == "." {
      // A request for the root path.
      Ok(vec![PathGlob::Root])
    } else if DOUBLE_STAR == parts[0] {
      if parts.len() == 1 {
        // Per https://git-scm.com/docs/gitignore:
        //  "A trailing '/**' matches everything inside. For example, 'abc/**' matches all files inside
        //   directory "abc", relative to the location of the .gitignore file, with infinite depth."
        return Ok(
          vec![
            PathGlob::dir_wildcard(
              canonical_dir.clone(),
              symbolic_path.to_owned(),
              Glob::new(SINGLE_STAR)?,
              PathBuf::from(DOUBLE_STAR)
            ),
            PathGlob::wildcard(
              canonical_dir.clone(),
              symbolic_path.to_owned(),
              Glob::new(SINGLE_STAR)?
            ),
          ]
        );
      }

      // There is a double-wildcard in a dirname of the path: double wildcards are recursive,
      // so there are two remainder possibilities: one with the double wildcard included, and the
      // other without.
      let pathglob_with_doublestar =
        PathGlob::dir_wildcard(
          canonical_dir.clone(),
          symbolic_path.to_owned(),
          Glob::new(SINGLE_STAR)?,
          join(&parts[0..])
        );
      let pathglob_no_doublestar =
        if parts.len() == 2 {
          PathGlob::wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            lossy_glob(parts[1])?
          )
        } else {
          PathGlob::dir_wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            lossy_glob(parts[1])?,
            join(&parts[2..])
          )
        };
      Ok(vec![pathglob_with_doublestar, pathglob_no_doublestar])
    } else if parts.len() == 1 {
      // This is the path basename.
      Ok(
        vec![
          PathGlob::wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            lossy_glob(parts[0])?
          )
        ]
      )
    } else {
      // This is a path dirname.
      Ok(
        vec![
          PathGlob::dir_wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            lossy_glob(parts[0])?,
            join(&parts[1..])
          )
        ]
      )
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
  fn canonicalize(&self, path_stat: PathStat) -> Result<PathStat, K> {
    let expansion =
      match path_stat.stat {
        Stat::Link(ref l) =>
          self.expand_link(&l)?,
        _ =>
          return Ok(path_stat),
      };
    let canonical_stat =
      match expansion {
        LinkExpansion::Dir(d) => Stat::Dir(d),
        LinkExpansion::File(f) => Stat::File(f),
      };
    Ok(PathStat::new(path_stat.path, canonical_stat))
  }

  /**
   * Apply a PathGlob, returning either PathStats on success or
   * continuations if more information is needed.
   */
  fn apply_path_glob(&self, path_glob: &PathGlob) -> Result<Vec<PathStat>, Vec<K>> {
    match path_glob {
      &PathGlob::Root =>
        Ok(vec![PathGlob::root_stat()]),
      &PathGlob::Wildcard { ref canonical_dir, ref symbolic_path, ref wildcard } => {
        // List the directory, match any relevant Stats, and join them into PathStats.
        let glob_matcher = wildcard.compile_matcher();
        let matched =
          self.scandir(canonical_dir).map_err(|k| vec![k])?.into_iter()
            .filter_map(|stat| {
              let p = stat.path().clone();
              p.file_name().and_then(|file_name| {
                if glob_matcher.is_match(file_name) {
                  let mut path = symbolic_path.clone();
                  path.push(file_name);
                  Some(PathStat::new(path, stat))
                } else {
                  None
                }
              })
            });

        // Batch-canonicalize matched PathStats.
        let mut path_stats = Vec::new();
        let mut continuations = Vec::new();
        for path_stat in matched {
          match self.canonicalize(path_stat) {
            Ok(ps) => path_stats.push(ps),
            Err(k) => continuations.push(k),
          }
        }
        if continuations.is_empty() {
          Ok(path_stats)
        } else {
          Err(continuations)
        }
      },
      &PathGlob::DirWildcard { .. } => {
        // Compute a DirectoryListing, and filter to Dirs (also, recursively expand symlinks
        // to determine whether they represent Dirs).
        let dir_list = panic!("TODO: implement DirectoryListing.");
        // expand dirs
        panic!("TODO: implement filtering and expanding a DirectoryListing to Dirs.")
      },
    }
  }
}
