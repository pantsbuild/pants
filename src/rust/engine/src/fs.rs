use std::path::PathBuf;

enum Stat {
  Link(Link),
  Dir(Dir),
  File(File),
}

struct Link(PathBuf);
struct Dir(PathBuf);
struct File(PathBuf);

enum PathGlob {
  PathRoot,
  PathWildcard(PathWildcard),
  PathDirWildcard(PathDirWildcard),
}

struct PathWildcard {
  canonical_dir: Dir,
  symbolic_path: PathBuf,
  wildcard: String,
}

struct PathDirWildcard {
  canonical_dir: Dir,
  symbolic_path: PathBuf,
  wildcard: String,
  remainder: String,
}

struct PathGlobs(Vec<PathGlob>);

impl PathGlobs {
  pub fn create(relative_to: Dir, filespecs: Vec<String>) -> PathGlobs {
    PathGlobs(
      filespecs.iter()
        .flat_map(|filespec| {
          PathGlobs.expand(relative_to, relative_to.1, filespec)
        })
        .collect()
    )
  }

  /**
   * Given a filespec, return the PathGlob objects it expands to.
   */
  fn expand(canonical_dir: Dir, symbolic_path: PathBuf, filespec: String) -> Vec<PathGlob> {
    let parts = Path::new(filespec).components();
    if canonical_stat == Dir("") && len(parts) == 1 && parts[0] == "." {
      // A request for the root path.
      vec![PathRoot]
    } else if cls._DOUBLE == parts[0] {
      parts = cls._prune_doublestar(parts);

      if len(parts) == 1 {
         // Per https://git-scm.com/docs/gitignore:
         //  "A trailing '/**' matches everything inside. For example, 'abc/**' matches all files inside
         //   directory "abc", relative to the location of the .gitignore file, with infinite depth."
        return vec![
          PathDirWildcard(canonical_stat, symbolic_path, "*", "**"),
          PathWildcard(canonical_stat, symbolic_path, "*")
        ];
      }

      // There is a double-wildcard in a dirname of the path: double wildcards are recursive,
      // so there are two remainder possibilities: one with the double wildcard included, and the
      // other without.
      let pathglob_with_doublestar =
        PathDirWildcard(canonical_stat, symbolic_path, "*", join(*parts[0:]))
      let pathglob_no_doublestar =
        if len(parts) == 2 {
          PathWildcard(canonical_stat, symbolic_path, parts[1])
        } else {
          PathDirWildcard(canonical_stat, symbolic_path, parts[1], join(*parts[2:]))
        };
      vec![pathglob_with_doublestar, pathglob_no_doublestar]
    } else if len(parts) == 1 {
      // This is the path basename.
      vec![PathWildcard(canonical_stat, symbolic_path, parts[0])]
    } else {
      // This is a path dirname.
      vec![PathDirWildcard(canonical_stat, symbolic_path, parts[0], join(*parts[1:]))]
    }
  }
}
