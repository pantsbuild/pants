// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::Stat;
use deepsize::{DeepSizeOf, known_deep_size};
use hashing::Digest;
use ignore::gitignore::{Gitignore, GitignoreBuilder};
use std::fs::File;
use std::hash::{Hash, Hasher};
use std::io::{BufRead, BufReader};
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::LazyLock;

static EMPTY_IGNORE: LazyLock<Arc<GitignoreStyleExcludes>> = LazyLock::new(|| {
    Arc::new(GitignoreStyleExcludes {
        patterns: vec![],
        gitignore: Ignore::empty(),
        gitignore_digests: vec![],
    })
});

#[derive(Clone, Debug)]
pub struct Ignore(pub Gitignore);

known_deep_size!(2_500; Ignore); // Guesstimate for a .gitignore with ~15 patterns.

impl Ignore {
    pub fn empty() -> Ignore {
        Self(Gitignore::empty())
    }
}

impl Deref for Ignore {
    type Target = Gitignore;
    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

#[derive(Debug, Clone, DeepSizeOf)]
pub struct GitignoreStyleExcludes {
    patterns: Vec<String>,
    pub(crate) gitignore: Ignore,
    gitignore_digests: Vec<Digest>,
}

impl PartialEq for GitignoreStyleExcludes {
    fn eq(&self, other: &Self) -> bool {
        self.patterns == other.patterns && self.gitignore_digests == other.gitignore_digests
    }
}

impl Eq for GitignoreStyleExcludes {}

impl Hash for GitignoreStyleExcludes {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.patterns.hash(state);
        self.gitignore_digests.hash(state);
    }
}

pub struct PatternsAndFileExcludes {
    pub patterns: Arc<GitignoreStyleExcludes>,
    pub files: Arc<GitignoreStyleExcludes>,
}

impl PatternsAndFileExcludes {
    pub fn empty() -> PatternsAndFileExcludes {
        Self {
            patterns: EMPTY_IGNORE.clone(),
            files: EMPTY_IGNORE.clone(),
        }
    }
}

impl GitignoreStyleExcludes {
    pub fn create(patterns: Vec<String>) -> Result<Arc<Self>, String> {
        Self::create_with_gitignore_files(patterns, vec![]).map(|excludes| excludes.patterns)
    }

    pub fn empty() -> Arc<Self> {
        EMPTY_IGNORE.clone()
    }

    /// Create with patterns and possibly multiple files.
    ///
    /// Later paths in `gitignore_paths` take precedence. `patterns` takes precedence over all
    /// `gitignore_paths`.
    pub fn create_with_gitignore_files(
        patterns: Vec<String>,
        gitignore_paths: Vec<PathBuf>,
    ) -> Result<PatternsAndFileExcludes, String> {
        if patterns.is_empty() && gitignore_paths.is_empty() {
            return Ok(PatternsAndFileExcludes::empty());
        }
        let patterns = Self::create_with_builder(patterns, vec![], GitignoreBuilder::new(""))?;
        let files = Self::create_with_builder(vec![], gitignore_paths, GitignoreBuilder::new(""))?;
        Ok(PatternsAndFileExcludes { patterns, files })
    }

    pub fn create_with_gitignore_file(
        directory: &Path,
        gitignore_file: PathBuf,
    ) -> Result<Arc<Self>, String> {
        Self::create_with_builder(
            vec![],
            vec![gitignore_file],
            GitignoreBuilder::new(directory),
        )
    }

    fn create_with_builder(
        patterns: Vec<String>,
        gitignore_paths: Vec<PathBuf>,
        mut ignore_builder: GitignoreBuilder,
    ) -> Result<Arc<Self>, String> {
        let gitignore_digests = gitignore_paths
            .into_iter()
            .map(|path| Self::read_and_hash_gitignore_file(&mut ignore_builder, &path))
            .collect::<Result<Vec<Digest>, _>>()
            .map_err(|e| e.to_string())?;
        for pattern in &patterns {
            ignore_builder.add_line(None, pattern).map_err(|e| {
                format!("Could not parse glob exclude pattern `{pattern:?}`: {e:?}")
            })?;
        }

        let gitignore = ignore_builder
            .build()
            .map_err(|e| format!("Could not build ignore patterns: {e:?}"))
            .map(Ignore)?;

        Ok(Arc::new(Self {
            patterns,
            gitignore,
            gitignore_digests,
        }))
    }

    /// Return the absolute file paths to the global gitignore, `<repo>/.gitignore`, and
    /// `<repo>/.git/info/exclude`, in that order.
    ///
    /// Will only add the files if they exist.
    pub fn gitignore_file_paths(build_root: &Path) -> Vec<PathBuf> {
        let mut result = vec![];

        if let Some(global_ignore_path) =
            ignore::gitignore::gitconfig_excludes_path().filter(|fp| fp.is_file())
        {
            result.push(global_ignore_path);
        }
        // Unlike Git, we hardcode `.git` and don't look for `$GIT_DIR`. See
        // https://github.com/BurntSushi/ripgrep/blob/041544853c86dde91c49983e5ddd0aa799bd2831/crates/ignore/src/dir.rs#L786-L794
        // for why.
        let exclude_path = build_root.join(".git/info/exclude");
        if Path::is_file(&exclude_path) {
            result.push(exclude_path)
        }
        result
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

    fn read_and_hash_gitignore_file(
        ignore_builder: &mut GitignoreBuilder,
        path: &PathBuf,
    ) -> Result<Digest, Box<dyn std::error::Error>> {
        let file = File::open(path)?;
        let mut hasher = hashing::Hasher::new();
        let reader = BufReader::new(file);
        for (i, line) in reader.lines().enumerate() {
            let read_line = line
                .map_err(|e| format!("Reading line {}:{} caused error {}", path.display(), i, e))?;
            hasher.update(read_line.as_bytes());
            ignore_builder.add_line(Some(path.clone()), &read_line)?;
        }
        Ok(hasher.finish())
    }
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::PathBuf;
    use std::sync::Arc;

    use crate::gitignore_stack::GitignoreStack;
    use crate::testutil::make_file;
    use crate::{GitignoreStyleExcludes, PosixFS, Stat};

    async fn read_mock_files(input: Vec<PathBuf>, posix_fs: &Arc<PosixFS>) -> Vec<Stat> {
        input
            .iter()
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
        ] {
            make_file(&root_path.join(fp), b"content", 0o700);
        }

        let gitignore_path = root_path.join(".gitignore");
        let git_info_exclude_path = root_path.join(".git/info/exclude");
        make_file(&gitignore_path, b"*.tmp\n!*.x", 0o700);
        fs::create_dir_all(git_info_exclude_path.parent().unwrap()).unwrap();
        make_file(&git_info_exclude_path, b"unimportant.x", 0o700);

        let create_posix_fx = |patterns, gitignore_paths| {
            let ignorer =
                GitignoreStyleExcludes::create_with_gitignore_files(patterns, gitignore_paths)
                    .unwrap();
            Arc::new(
                PosixFS::new(
                    root.as_ref(),
                    GitignoreStack::root(ignorer.patterns, ignorer.files, false),
                    task_executor::Executor::new(),
                )
                .unwrap(),
            )
        };

        let posix_fs = create_posix_fx(vec![], vec![gitignore_path.clone()]);

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

        assert!(posix_fs.is_ignored(&stats[1]));
        for fp in [&stats[0], &stats[2], &stats[3]] {
            assert!(!posix_fs.is_ignored(fp));
        }

        // Test that .gitignore files work in tandem with explicit ignores.
        //
        // Patterns override file paths: note how the gitignore says `!*.x` but that gets
        // overridden here.
        let posix_fs2 = create_posix_fx(
            vec!["unimportant.x".to_owned()],
            vec![gitignore_path.clone()],
        );
        for fp in [&stats[1], &stats[3]] {
            assert!(posix_fs2.is_ignored(fp));
        }
        for fp in [&stats[0], &stats[2]] {
            assert!(!posix_fs2.is_ignored(fp));
        }

        // Test that later gitignore files override earlier ones.
        let posix_fs3 = create_posix_fx(
            vec![],
            vec![gitignore_path.clone(), git_info_exclude_path.clone()],
        );
        for fp in [&stats[1], &stats[3]] {
            assert!(posix_fs3.is_ignored(fp));
        }
        for fp in [&stats[0], &stats[2]] {
            assert!(!posix_fs3.is_ignored(fp));
        }
        let posix_fs4 = create_posix_fx(
            vec![],
            vec![git_info_exclude_path.clone(), gitignore_path.clone()],
        );
        assert!(posix_fs4.is_ignored(&stats[1]));
        for fp in [&stats[0], &stats[2], &stats[3]] {
            assert!(!posix_fs4.is_ignored(fp));
        }
    }

    #[test]
    fn test_gitignore_file_paths() {
        let root = tempfile::TempDir::new().unwrap();
        let root_path = root.path();

        // The behavior of gitignore_file_paths depends on whether the machine has a global config
        // file or not. We do not want to muck around with people's global config, so instead we
        // update what we expect from the test.
        let global_config_path =
            ignore::gitignore::gitconfig_excludes_path().filter(|fp| fp.is_file());

        let expected = match global_config_path.clone() {
            Some(global_fp) => vec![global_fp],
            None => vec![],
        };
        assert_eq!(
            GitignoreStyleExcludes::gitignore_file_paths(root_path),
            expected
        );

        assert_eq!(
            GitignoreStyleExcludes::gitignore_file_paths(root_path),
            expected
        );

        let git_info_exclude_path = root_path.join(".git/info/exclude");
        fs::create_dir_all(git_info_exclude_path.parent().unwrap()).unwrap();
        make_file(&git_info_exclude_path, b"", 0o700);
        let expected = match global_config_path.clone() {
            Some(global_fp) => vec![global_fp, git_info_exclude_path],
            None => vec![git_info_exclude_path],
        };
        assert_eq!(
            GitignoreStyleExcludes::gitignore_file_paths(root_path),
            expected
        );
    }
}
