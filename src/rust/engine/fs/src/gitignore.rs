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
    Self::create_with_gitignore_file(patterns, None)
  }

  pub fn empty() -> Arc<Self> {
    EMPTY_IGNORE.clone()
  }

  pub fn create_with_gitignore_file(
    patterns: Vec<String>,
    gitignore_path: Option<PathBuf>,
  ) -> Result<Arc<Self>, String> {
    if patterns.is_empty() && gitignore_path.is_none() {
      return Ok(EMPTY_IGNORE.clone());
    }

    let mut ignore_builder = GitignoreBuilder::new("");

    if let Some(path) = gitignore_path {
      if let Some(err) = ignore_builder.add(path) {
        return Err(format!("Error adding .gitignore path: {err:?}"));
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
      patterns: patterns,
      gitignore,
    }))
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
  use std::path::PathBuf;
  use std::sync::Arc;

  use crate::{GitignoreStyleExcludes, PosixFS, Stat};
  use testutil::make_file;

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

    let bytes = "content".as_bytes();
    make_file(&root_path.join("non-ignored"), bytes, 0o700);
    make_file(&root_path.join("ignored-file.tmp"), bytes, 0o700);
    make_file(&root_path.join("important.x"), bytes, 0o700);
    make_file(&root_path.join("unimportant.x"), bytes, 0o700);

    let gitignore_content = "*.tmp\n!*.x";
    let gitignore_path = root_path.join(".gitignore");
    make_file(&gitignore_path, gitignore_content.as_bytes(), 0o700);
    let executor = task_executor::Executor::new();
    let ignorer =
      GitignoreStyleExcludes::create_with_gitignore_file(vec![], Some(gitignore_path.clone()))
        .unwrap();
    let posix_fs = Arc::new(PosixFS::new(root.as_ref(), ignorer, executor).unwrap());

    let stats = read_mock_files(
      vec![
        PathBuf::from("non-ignored"),
        PathBuf::from("ignored-file.tmp"),
        PathBuf::from("important.x"),
        PathBuf::from("unimportant.x"),
      ],
      &posix_fs,
    )
    .await;

    assert!(!posix_fs.is_ignored(&stats[0]));
    assert!(posix_fs.is_ignored(&stats[1]));
    assert!(!posix_fs.is_ignored(&stats[2]));
    assert!(!posix_fs.is_ignored(&stats[3]));

    // Test that .gitignore files work in tandem with explicit ignores.
    let executor = task_executor::Executor::new();
    let ignorer = GitignoreStyleExcludes::create_with_gitignore_file(
      vec!["unimportant.x".to_string()],
      Some(gitignore_path),
    )
    .unwrap();
    let posix_fs_2 = Arc::new(PosixFS::new(root.as_ref(), ignorer, executor).unwrap());

    assert!(!posix_fs_2.is_ignored(&stats[0]));
    assert!(posix_fs_2.is_ignored(&stats[1]));
    assert!(!posix_fs_2.is_ignored(&stats[2]));
    assert!(posix_fs_2.is_ignored(&stats[3]));
  }
}
