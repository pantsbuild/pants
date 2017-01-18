use std::ffi::{OsString, OsStr};
use std::path::{Path, PathBuf};

#[derive(Eq, Hash, PartialEq)]
pub enum Stat {
  Link(Link),
  Dir(Dir),
  File(File),
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct Link(pub PathBuf);

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct Dir(pub PathBuf);

impl Clone for Dir {
  fn clone(&self) -> Dir {
    Dir(self.0.to_owned())
  }
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct File(pub PathBuf);

enum LinkExpansion {
  // Successfully resolved to a File.
  File(File),
  // Successfully resolved to a Dir.
  Dir(Dir),
  // Failed to resolve due to a Loop.
  Loop(String),
}

#[derive(Eq, Hash, PartialEq)]
pub struct PathStat {
  // The symbolic name of some filesystem Path, which is context specific.
  pub path: PathBuf,
  // The canonical Stat that underlies the Path.
  pub stat: Stat,
}

#[derive(Clone)]
pub enum PathGlob {
  Root,
  Wildcard {
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: OsString,
  },
  DirWildcard {
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: OsString,
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

  fn wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: OsString) -> PathGlob {
    PathGlob::Wildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
    }
  }

  fn dir_wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: OsString, remainder: PathBuf) -> PathGlob {
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

const MAX_LINK_EXPANSION_ATTEMPTS: usize = 64;

fn join(components: &[&OsStr]) -> PathBuf {
  let mut out = PathBuf::new();
  for component in components {
    out.push(component);
  }
  out
}

impl PathGlobs {
  pub fn create(relative_to: &Dir, filespecs: Vec<PathBuf>) -> PathGlobs {
    PathGlobs(
      filespecs.iter()
        .flat_map(|filespec| {
          PathGlobs::parse(relative_to, relative_to.0.as_path(), filespec)
        })
        .collect()
    )
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
  fn parse(canonical_dir: &Dir, symbolic_path: &Path, filespec: &Path) -> Vec<PathGlob> {
    let mut parts: Vec<&OsStr> = Path::new(filespec).iter().collect();
    PathGlobs::normalize_doublestar(&mut parts);

    if canonical_dir.0.as_os_str() == "." && parts.len() == 1 && parts[0] == "." {
      // A request for the root path.
      vec![PathGlob::Root]
    } else if DOUBLE_STAR == parts[0] {
      if parts.len() == 1 {
         // Per https://git-scm.com/docs/gitignore:
         //  "A trailing '/**' matches everything inside. For example, 'abc/**' matches all files inside
         //   directory "abc", relative to the location of the .gitignore file, with infinite depth."
        return vec![
          PathGlob::dir_wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            OsString::from(SINGLE_STAR),
            PathBuf::from(DOUBLE_STAR)
          ),
          PathGlob::wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            OsString::from(SINGLE_STAR)
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
          OsString::from(SINGLE_STAR),
          join(&parts[0..])
        );
      let pathglob_no_doublestar =
        if parts.len() == 2 {
          PathGlob::wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            parts[1].to_owned()
          )
        } else {
          PathGlob::dir_wildcard(
            canonical_dir.clone(),
            symbolic_path.to_owned(),
            parts[1].to_owned(),
            join(&parts[2..])
          )
        };
      vec![pathglob_with_doublestar, pathglob_no_doublestar]
    } else if parts.len() == 1 {
      // This is the path basename.
      vec![
        PathGlob::wildcard(
          canonical_dir.clone(),
          symbolic_path.to_owned(),
          parts[0].to_owned()
        )
      ]
    } else {
      // This is a path dirname.
      vec![
        PathGlob::dir_wildcard(
          canonical_dir.clone(),
          symbolic_path.to_owned(),
          parts[0].to_owned(),
          join(&parts[1..])
        )
      ]
    }
  }
}

pub trait FSContext<Incomplete> {
  fn read_link(&self, link: &Link) -> Result<PathBuf, Incomplete>;
  fn stat(&self, path: &Path) -> Result<Stat, Incomplete>;

  /**
   * Recursively expand a symlink to an underlying non-link Stat.
   */
  fn expand_link<T, C: FSContext<T>>(mut link: &Link, context: &C) -> Result<LinkExpansion, T> {
    let mut attempts = 0;
    loop {
      attempts += 1;
      if attempts > MAX_LINK_EXPANSION_ATTEMPTS {
        return Ok(
          LinkExpansion::Loop(
            format!("Encountered a symlink loop while expanding {:?}", link)
          )
        );
      }

      // Read the link.
      let path =
        match context.read_link(link) {
          Result::Ok(path) => path,
          Result::Err(t) => return Result::Err(t),
        };
      // Stat the destination.
      match context.stat(path.as_path()) {
        Ok(Stat::Link(ref l)) => {
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
}
