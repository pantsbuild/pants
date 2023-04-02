// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::cmp::Ordering;
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use ignore::gitignore::{Gitignore, GitignoreBuilder};
use lazy_static::lazy_static;

use crate::Stat;

lazy_static! {
  static ref EMPTY_IGNORE: Arc<GitignoreStyleExcludes> = Arc::new(GitignoreStyleExcludes {
    patterns: vec![],
    gitignore: Gitignore::empty(),
  });
}

#[derive(Debug)]
pub struct GitignoreStyleExcludes {
  patterns: Vec<String>,
  gitignore: Gitignore,
}

impl GitignoreStyleExcludes {
  pub fn create(patterns: Vec<String>) -> Result<Arc<Self>, String> {
    Self::create_with_gitignore_files(patterns, vec![], vec![], &PathBuf::new())
  }

  pub fn empty() -> Arc<Self> {
    EMPTY_IGNORE.clone()
  }

  /// Create with patterns and possibly multiple gitignore files.
  ///
  /// `global_gitignore_paths` will be used as-is. They're expected to live in the `build_root`
  /// or be the global ignore file. Meanwhile, `nested_gitignore_paths` will have each line
  /// relativized to `build_root`, as if their contents were defined in the repository root's
  /// gitignore.
  ///
  /// Precedence, from least to most: `global_gitignore_paths`, `nested_gitignore_paths`, then
  /// `patterns`. Within `global_gitignore_paths` and `nested_gitignore_paths`, later paths take
  /// precedence over earlier ones; so, it's expected that the caller correctly orders the entries.
  pub fn create_with_gitignore_files(
    patterns: Vec<String>,
    global_gitignore_paths: Vec<PathBuf>,
    nested_gitignore_paths: Vec<PathBuf>,
    build_root: &Path,
  ) -> Result<Arc<Self>, String> {
    if patterns.is_empty() && global_gitignore_paths.is_empty() && nested_gitignore_paths.is_empty()
    {
      return Ok(Self::empty());
    }

    let mut ignore_builder = GitignoreBuilder::new("");

    for path in global_gitignore_paths {
      if let Some(err) = ignore_builder.add(&path) {
        return Err(format!("Error adding the path {}: {err:?}", path.display()));
      }
    }

    for path in nested_gitignore_paths {
      let contents = fs::read_to_string(&path).map_err(|e| e.to_string())?;
      let rel_path = path
        .parent()
        .ok_or(format!(
          "nested_gitignore_paths must have a parent: {}",
          path.display()
        ))?
        .strip_prefix(build_root)
        .map_err(|e| {
          format!("nested_gitignore_paths must be subdirectories of the build_root: {e}")
        })?;
      for line in contents.lines() {
        if let Some(pattern) = Self::relativize_pattern(line, rel_path) {
          ignore_builder.add_line(None, &pattern).map_err(|e| {
            format!(
              "Could not parse line `{line:?}` from the file {}: {e:?}",
              rel_path.display()
            )
          })?;
        }
      }
    }

    for pattern in &patterns {
      ignore_builder
        .add_line(None, pattern)
        .map_err(|e| format!("Could not parse glob exclude pattern `{pattern:?}`: {e:?}"))?;
    }

    let gitignore = ignore_builder
      .build()
      .map_err(|e| format!("Could not build ignore patterns: {e:?}"))?;

    Ok(Arc::new(Self {
      patterns,
      gitignore,
    }))
  }

  /// Return a tuple of global and nested gitignore files.
  ///
  /// The global gitignore files may include the global gitignore (from `core.excludesFile`,
  /// `<build_root>/.gitignore`, and `<build_root>/.git/info/exclude`, in that order.
  ///
  /// The nested gitignore files include all `.gitignore` files in subdirectories underneath
  /// `build_root`. They are ordered by directory level, such that `a/.gitignore` appears before
  /// `a/b/.gitignore`, meaning that `a/.gitignore` has lower precedence.
  ///
  /// All paths are absolute file paths. Will only return files that exist.
  pub fn gitignore_file_paths(build_root: &Path) -> (Vec<PathBuf>, Vec<PathBuf>) {
    let mut global_files_result = vec![];
    let mut unordered_nested_files: HashSet<PathBuf> = walkdir::WalkDir::new(build_root)
      .into_iter()
      .filter_map(|entry| match entry {
        Ok(e) if e.file_name().to_string_lossy() == ".gitignore" => Some(e.path().to_owned()),
        Ok(_) | Err(_) => None,
      })
      .collect();

    if let Some(global_ignore_path) =
      ignore::gitignore::gitconfig_excludes_path().filter(|fp| fp.is_file())
    {
      global_files_result.push(global_ignore_path);
    }

    let gitignore_path = build_root.join(".gitignore");
    if Path::is_file(&gitignore_path) {
      unordered_nested_files.remove(&gitignore_path);
      global_files_result.push(gitignore_path);
    }

    // Unlike Git, we hardcode `.git` and don't look for `$GIT_DIR`. See
    // https://github.com/BurntSushi/ripgrep/blob/041544853c86dde91c49983e5ddd0aa799bd2831/crates/ignore/src/dir.rs#L786-L794
    // for why.
    let exclude_path = build_root.join(".git/info/exclude");
    if Path::is_file(&exclude_path) {
      global_files_result.push(exclude_path)
    }

    let mut sorted_nested_files: Vec<PathBuf> = unordered_nested_files.into_iter().collect();
    sorted_nested_files.sort_by(|a, b| {
      let a_depth = a.components().count();
      let b_depth = b.components().count();
      match a_depth.cmp(&b_depth) {
        Ordering::Equal => a.cmp(b),
        other => other,
      }
    });
    (global_files_result, sorted_nested_files)
  }

  /// Prefix `pattern` with the `base_path`. Return `None` if it's not a pattern, e.g. a
  /// comment.
  ///
  /// This is useful so that gitignores from subdirectories can be merged into the build root-level
  /// gitignore. `base_path` should be the path from the `.gitignore` file without the
  /// build root prefix, such as `subdir/`.
  ///
  /// Respects the rules in https://git-scm.com/docs/gitignore#_pattern_format.
  fn relativize_pattern(pattern: &str, base_path: &Path) -> Option<String> {
    assert!(!base_path.display().to_string().ends_with('/'));
    let trimmed_pattern = pattern.trim();
    if trimmed_pattern.is_empty() || trimmed_pattern.starts_with('#') {
      None
    } else {
      let (negation, rel_pattern) = if let Some(stripped) = trimmed_pattern.strip_prefix('!') {
        ("!", stripped)
      } else {
        ("", trimmed_pattern)
      };

      let prefix = if rel_pattern.starts_with('/') {
        ""
      } else if rel_pattern
        .chars()
        .enumerate()
        .any(|(i, c)| c == '/' && i != rel_pattern.len() - 1)
      {
        "/"
      } else {
        "/**/"
      };

      let relativized_pattern = format!("{}{}{}", base_path.display(), prefix, rel_pattern);
      Some(format!("{}{}", negation, relativized_pattern))
    }
  }

  pub(crate) fn exclude_patterns(&self) -> &[String] {
    self.patterns.as_slice()
  }

  pub(crate) fn is_ignored(&self, stat: &Stat) -> bool {
    let is_dir = matches!(stat, &Stat::Dir(_));
    self.is_ignored_path(stat.path(), is_dir)
  }

  pub fn is_ignored_path(&self, path: &Path, is_dir: bool) -> bool {
    match self.gitignore.matched(path, is_dir) {
      ::ignore::Match::None | ::ignore::Match::Whitelist(_) => false,
      ::ignore::Match::Ignore(_) => true,
    }
  }

  pub fn is_ignored_or_child_of_ignored_path(&self, path: &Path, is_dir: bool) -> bool {
    match self.gitignore.matched_path_or_any_parents(path, is_dir) {
      ::ignore::Match::None | ::ignore::Match::Whitelist(_) => false,
      ::ignore::Match::Ignore(_) => true,
    }
  }
}

#[cfg(test)]
mod tests {
  use std::fs;
  use std::path::{Path, PathBuf};
  use std::sync::Arc;

  use crate::{GitignoreStyleExcludes, PosixFS, Stat};
  use testutil::make_file;

  fn create_empty_file(fp: &Path) {
    fs::create_dir_all(fp.parent().unwrap()).unwrap();
    make_file(&fp, b"", 0o700);
  }

  async fn read_mock_files(input: Vec<PathBuf>, posix_fs: &Arc<PosixFS>) -> Vec<Stat> {
    input
      .into_iter()
      .map(|p| posix_fs.stat_sync(p).unwrap().unwrap())
      .collect()
  }

  #[tokio::test]
  async fn test_basic_gitignore_functionality() {
    let root = tempfile::TempDir::new().unwrap();
    let root_path = root.path();

    for fp in [
      "non-ignored",
      "ignored-file.tmp",
      "important.x",
      "unimportant.x",
      "subdir/f.tmp",
      "subdir/f.x",
      "subdir/dir/f.tmp",
    ] {
      create_empty_file(&root_path.join(fp));
    }

    let create_posix_fx = |patterns, global_gitignore_paths, nested_gitignore_paths| {
      let ignorer = GitignoreStyleExcludes::create_with_gitignore_files(
        patterns,
        global_gitignore_paths,
        nested_gitignore_paths,
        &root_path,
      )
      .unwrap();
      Arc::new(PosixFS::new(root.as_ref(), ignorer, task_executor::Executor::new()).unwrap())
    };

    let gitignore_path = root_path.join(".gitignore");
    make_file(&gitignore_path, b"*.tmp\n!*.x", 0o700);
    let posix_fs = create_posix_fx(vec![], vec![gitignore_path.clone()], vec![]);

    let stats = read_mock_files(
      vec![
        PathBuf::from("non-ignored"),      // 0
        PathBuf::from("ignored-file.tmp"), // 1
        PathBuf::from("important.x"),      // 2
        PathBuf::from("unimportant.x"),    // 3
        PathBuf::from("subdir/f.tmp"),     // 4
        PathBuf::from("subdir/f.x"),       // 5
        PathBuf::from("subdir/dir/f.tmp"), // 6
      ],
      &posix_fs,
    )
    .await;
    let stat_non_ignored = &stats[0];
    let stat_ignored_file_tmp = &stats[1];
    let stat_important_x = &stats[2];
    let stat_unimportant_x = &stats[3];
    let stat_subdir_f_tmp = &stats[4];
    let stat_subdir_f_x = &stats[5];
    let stat_subdir_dir_f_tmp = &stats[6];

    for fp in [
      &stat_ignored_file_tmp,
      &stat_subdir_f_tmp,
      &stat_subdir_dir_f_tmp,
    ] {
      assert!(posix_fs.is_ignored(fp));
    }
    for fp in [
      &stat_non_ignored,
      &stat_important_x,
      &stat_unimportant_x,
      &stat_subdir_f_x,
    ] {
      assert!(!posix_fs.is_ignored(fp));
    }

    // Test that .gitignore files work in tandem with explicit ignores.
    //
    // Patterns override file paths: note how the gitignore says `!*.x` but that gets
    // overridden here.
    let posix_fs2 = create_posix_fx(
      vec!["unimportant.x".to_owned()],
      vec![gitignore_path.clone()],
      vec![],
    );
    for fp in [
      &stat_ignored_file_tmp,
      &stat_unimportant_x,
      &stat_subdir_f_tmp,
      &stat_subdir_dir_f_tmp,
    ] {
      assert!(posix_fs2.is_ignored(fp));
    }
    for fp in [&stat_non_ignored, &stat_important_x, &stat_subdir_f_x] {
      assert!(!posix_fs2.is_ignored(fp));
    }

    // Test that later gitignore files override earlier ones.
    let git_info_exclude_path = root_path.join(".git/info/exclude");
    fs::create_dir_all(git_info_exclude_path.parent().unwrap()).unwrap();
    make_file(&git_info_exclude_path, b"unimportant.x", 0o700);
    let posix_fs3 = create_posix_fx(
      vec![],
      vec![gitignore_path.clone(), git_info_exclude_path.clone()],
      vec![],
    );
    for fp in [
      &stat_ignored_file_tmp,
      &stat_unimportant_x,
      &stat_subdir_f_tmp,
      stat_subdir_dir_f_tmp,
    ] {
      assert!(posix_fs3.is_ignored(fp));
    }
    for fp in [&stat_non_ignored, &stat_important_x, &stat_subdir_f_x] {
      assert!(!posix_fs3.is_ignored(fp));
    }
    let posix_fs4 = create_posix_fx(
      vec![],
      vec![git_info_exclude_path.clone(), gitignore_path.clone()],
      vec![],
    );
    for fp in [
      &stat_ignored_file_tmp,
      &stat_subdir_f_tmp,
      &stat_subdir_dir_f_tmp,
    ] {
      assert!(posix_fs4.is_ignored(fp));
    }
    for fp in [
      &stat_non_ignored,
      &stat_important_x,
      &stat_unimportant_x,
      stat_subdir_f_x,
    ] {
      assert!(!posix_fs4.is_ignored(fp));
    }

    // Test that nested gitignores take precedence over global gitignores.
    let nested_path = root_path.join("subdir/.gitignore");
    make_file(&nested_path, b"f.x", 0o700);
    let posix_fs5 = create_posix_fx(
      vec![],
      vec![gitignore_path.clone()],
      vec![nested_path.clone()],
    );
    for fp in [
      &stat_ignored_file_tmp,
      &stat_subdir_f_tmp,
      &stat_subdir_f_x,
      &stat_subdir_dir_f_tmp,
    ] {
      assert!(posix_fs5.is_ignored(fp));
    }
    for fp in [&stat_non_ignored, &stat_important_x, &stat_unimportant_x] {
      assert!(!posix_fs5.is_ignored(fp));
    }

    // Test that patterns take precedence over nested gitignores.
    let posix_fs6 = create_posix_fx(
      vec!["!subdir/f.x".to_owned()],
      vec![gitignore_path.clone()],
      vec![nested_path.clone()],
    );
    for fp in [
      &stat_ignored_file_tmp,
      &stat_subdir_f_tmp,
      &stat_subdir_dir_f_tmp,
    ] {
      assert!(posix_fs6.is_ignored(fp));
    }
    for fp in [
      &stat_non_ignored,
      &stat_important_x,
      &stat_unimportant_x,
      &stat_subdir_f_x,
    ] {
      assert!(!posix_fs6.is_ignored(fp));
    }

    // Test that later nested gitignore files override earlier ones.
    make_file(&nested_path, b"*.tmp", 0o700);
    let double_nested_path = root_path.join("subdir/dir/.gitignore");
    make_file(&double_nested_path, b"!f.tmp", 0o700);
    let posix_fs7 = create_posix_fx(
      vec![],
      vec![],
      vec![nested_path.clone(), double_nested_path.clone()],
    );
    assert!(posix_fs7.is_ignored(&stat_subdir_f_tmp));
    for fp in [
      &stat_non_ignored,
      &stat_ignored_file_tmp,
      &stat_important_x,
      &stat_unimportant_x,
      &stat_subdir_f_x,
      &stat_subdir_dir_f_tmp,
    ] {
      assert!(!posix_fs7.is_ignored(fp));
    }
    let posix_fs8 = create_posix_fx(vec![], vec![], vec![double_nested_path, nested_path]);
    for fp in [&stat_subdir_f_tmp, &stat_subdir_dir_f_tmp] {
      assert!(posix_fs8.is_ignored(fp));
    }
    for fp in [
      &stat_non_ignored,
      &stat_ignored_file_tmp,
      &stat_important_x,
      &stat_unimportant_x,
      &stat_subdir_f_x,
    ] {
      assert!(!posix_fs8.is_ignored(fp));
    }
  }

  #[test]
  fn test_gitignore_file_paths() {
    let root = tempfile::TempDir::new().unwrap();
    let root_path = root.path();

    // The behavior of gitignore_file_paths depends on whether the machine has a global config
    // file or not. We do not want to muck around with people's global config, so instead we
    // update what we expect from the test.
    let global_config_path = ignore::gitignore::gitconfig_excludes_path().filter(|fp| fp.is_file());

    let global_expected = match global_config_path.clone() {
      Some(global_fp) => vec![global_fp],
      None => vec![],
    };
    assert_eq!(
      GitignoreStyleExcludes::gitignore_file_paths(root_path),
      (global_expected, vec![])
    );

    let gitignore_path = root_path.join(".gitignore");
    create_empty_file(&gitignore_path);
    let global_expected = match global_config_path.clone() {
      Some(global_fp) => vec![global_fp, gitignore_path.clone()],
      None => vec![gitignore_path.clone()],
    };
    assert_eq!(
      GitignoreStyleExcludes::gitignore_file_paths(root_path),
      (global_expected, vec![])
    );

    let git_info_exclude_path = root_path.join(".git/info/exclude");
    create_empty_file(&git_info_exclude_path);
    let global_expected = match global_config_path.clone() {
      Some(global_fp) => vec![global_fp, gitignore_path.clone(), git_info_exclude_path],
      None => vec![gitignore_path.clone(), git_info_exclude_path],
    };
    assert_eq!(
      GitignoreStyleExcludes::gitignore_file_paths(root_path),
      (global_expected.clone(), vec![])
    );

    let nested_a_path = root_path.join("nested/a/.gitignore");
    let nested_b_path = root_path.join("nested/b/.gitignore");
    let nested_ax_path = root_path.join("nested/a/x/.gitignore");
    let nested_ay_path = root_path.join("nested/a/x/y/.gitignore");
    let nested_by_path = root_path.join("nested/b/x/y/.gitignore");
    for fp in [
      &nested_a_path,
      &nested_b_path,
      &nested_ax_path,
      &nested_ay_path,
      &nested_by_path,
    ] {
      create_empty_file(fp);
    }
    assert_eq!(
      GitignoreStyleExcludes::gitignore_file_paths(root_path),
      // Order matters here. Subdirectories should be ordered by directory level (alphabetical
      // within the same level).
      (
        global_expected,
        vec![
          nested_a_path,
          nested_b_path,
          nested_ax_path,
          nested_ay_path,
          nested_by_path
        ]
      )
    );
  }

  #[test]
  fn test_relativize_pattern() {
    fn assert_relativized(pattern: &str, expected: Option<&str>) {
      assert_eq!(
        GitignoreStyleExcludes::relativize_pattern(pattern, &PathBuf::from("subdir")),
        expected.map(|s| s.to_owned())
      );
    }

    assert_relativized("", None);
    assert_relativized("  ", None);
    assert_relativized("# comment", None);
    assert_relativized("  # comment", None);

    // If there are no `/` in the beginning or middle, the pattern may match at any level below
    // the `.gitignore`.
    assert_relativized("pattern", Some("subdir/**/pattern"));
    assert_relativized("pattern/", Some("subdir/**/pattern/"));
    assert_relativized("!pattern", Some("!subdir/**/pattern"));
    assert_relativized("!pattern/", Some("!subdir/**/pattern/"));
    assert_relativized("p*n", Some("subdir/**/p*n"));
    assert_relativized("p*n/", Some("subdir/**/p*n/"));
    assert_relativized("!p*n", Some("!subdir/**/p*n"));
    assert_relativized("!p*n/", Some("!subdir/**/p*n/"));

    assert_relativized("/pattern", Some("subdir/pattern"));
    assert_relativized("/pattern/", Some("subdir/pattern/"));
    assert_relativized("!/pattern", Some("!subdir/pattern"));
    assert_relativized("!/pattern/", Some("!subdir/pattern/"));
    assert_relativized("/p*n", Some("subdir/p*n"));
    assert_relativized("/p*n/", Some("subdir/p*n/"));
    assert_relativized("!/p*n", Some("!subdir/p*n"));
    assert_relativized("!/p*n/", Some("!subdir/p*n/"));

    assert_relativized("a/pattern", Some("subdir/a/pattern"));
    assert_relativized("a/pattern/", Some("subdir/a/pattern/"));
    assert_relativized("!a/pattern", Some("!subdir/a/pattern"));
    assert_relativized("!a/pattern/", Some("!subdir/a/pattern/"));
    assert_relativized("a/p*n", Some("subdir/a/p*n"));
    assert_relativized("a/p*n/", Some("subdir/a/p*n/"));
    assert_relativized("!a/p*n", Some("!subdir/a/p*n"));
    assert_relativized("!a/p*n/", Some("!subdir/a/p*n/"));
  }
}
