use std::ffi::{OsString, OsStr};
use std::path::{Component, Path, PathBuf};

enum Stat {
  Link(Link),
  Dir(Dir),
  File(File),
}

#[derive(Eq, PartialEq)]
struct Link(PathBuf);

#[derive(Eq, PartialEq)]
struct Dir(PathBuf);

impl Clone for Dir {
  fn clone(&self) -> Dir {
    Dir(self.0.to_owned())
  }
}

#[derive(Eq, PartialEq)]
struct File(PathBuf);

enum PathGlob {
  PathRoot,
  PathWildcard {
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: OsString,
  },
  PathDirWildcard {
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: OsString,
    remainder: PathBuf,
  },
}

impl PathGlob {
  fn wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: OsString) -> PathGlob {
    PathGlob::PathWildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
    }
  }

  fn dir_wildcard(canonical_dir: Dir, symbolic_path: PathBuf, wildcard: OsString, remainder: PathBuf) -> PathGlob {
    PathGlob::PathDirWildcard {
      canonical_dir: canonical_dir,
      symbolic_path: symbolic_path,
      wildcard: wildcard,
      remainder: remainder,
    }
  }
}

struct PathGlobs(Vec<PathGlob>);

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
  pub fn create(relative_to: &Dir, filespecs: Vec<PathBuf>) -> PathGlobs {
    PathGlobs(
      filespecs.iter()
        .flat_map(|filespec| {
          PathGlobs::expand(relative_to, relative_to.0.as_path(), filespec)
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
   * Given a filespec, return the PathGlob objects it expands to.
   */
  fn expand(canonical_dir: &Dir, symbolic_path: &Path, filespec: &Path) -> Vec<PathGlob> {
    let mut parts: Vec<&OsStr> = Path::new(filespec).iter().collect();
    PathGlobs::normalize_doublestar(&mut parts);

    if canonical_dir.0.as_os_str() == "." && parts.len() == 1 && parts[0] == "." {
      // A request for the root path.
      vec![PathGlob::PathRoot]
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
