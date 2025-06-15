// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::{GitignoreStyleExcludes, Stat};
use deepsize::DeepSizeOf;
use ignore::gitignore::Gitignore;
use std::path::Path;
use std::sync::Arc;

/// A stack of gitignore style patterns. It is on the caller to ensure the stack is applicable to
/// the input path, likely by constructing it from the parent directory of the path to be tested.
#[derive(Debug, DeepSizeOf, Eq, PartialEq, Clone, Hash)]
pub struct GitignoreStack {
    matcher: Option<Arc<GitignoreStyleExcludes>>,
    parent: Option<Arc<GitignoreStack>>,
    configured_patterns: Arc<GitignoreStyleExcludes>,
    pub use_nested_gitignore: bool,
}

impl GitignoreStack {
    pub fn root(
        configured_patterns: Arc<GitignoreStyleExcludes>,
        root_matcher: Arc<GitignoreStyleExcludes>,
        use_nested_gitignore: bool,
    ) -> Self {
        Self {
            matcher: Some(root_matcher),
            parent: None,
            configured_patterns,
            use_nested_gitignore,
        }
    }

    pub fn new(matcher: Arc<GitignoreStyleExcludes>, parent: Arc<GitignoreStack>) -> Self {
        Self {
            matcher: Some(matcher),
            use_nested_gitignore: parent.use_nested_gitignore,
            configured_patterns: parent.configured_patterns.clone(),
            parent: Some(parent),
        }
    }

    fn parse(
        directory: &Path,
        gitignore_file: &Path,
        parent: Arc<GitignoreStack>,
    ) -> Result<Self, String> {
        Ok(Self::new(
            GitignoreStyleExcludes::create_with_gitignore_file(
                directory,
                gitignore_file.to_path_buf(),
            )?,
            parent,
        ))
    }

    pub fn push(self, directory: &Path, git_ignore_file: &Path) -> Result<GitignoreStack, String> {
        GitignoreStack::parse(directory, git_ignore_file, Arc::new(self))
    }

    pub fn is_path_ignored(&self, path: &Path, is_dir: bool) -> bool {
        self.is_path_ignored_for_method(path, is_dir, |gitignore, path, is_dir| {
            gitignore.matched(path, is_dir)
        })
    }

    pub fn is_path_ignored_or_any_parent(&self, path: &Path, is_dir: bool) -> bool {
        self.is_path_ignored_for_method(path, is_dir, |gitignore, path, is_dir| {
            gitignore.matched_path_or_any_parents(path, is_dir)
        })
    }

    #[inline]
    fn is_path_ignored_for_method<F>(&self, path: &Path, is_dir: bool, method: F) -> bool
    where
        F: for<'g> Fn(&'g Gitignore, &Path, bool) -> ::ignore::Match<&'g ::ignore::gitignore::Glob>,
    {
        match method(&self.configured_patterns.gitignore, path, is_dir) {
            ::ignore::Match::Ignore(_) => return true,
            ::ignore::Match::Whitelist(_) => return false,
            ::ignore::Match::None => {}
        };
        let mut node = Some(self);
        while let Some(n) = node {
            if let Some(matcher) = &n.matcher {
                match method(&matcher.gitignore, path, is_dir) {
                    ::ignore::Match::Ignore(_) => return true,
                    ::ignore::Match::Whitelist(_) => return false,
                    ::ignore::Match::None => {}
                }
            }
            node = n.parent.as_deref();
        }
        false
    }

    pub(crate) fn is_stat_ignored(&self, stat: &Stat) -> bool {
        let is_dir = matches!(stat, &Stat::Dir(_));
        self.is_path_ignored(stat.path(), is_dir)
    }

    pub const fn is_empty(&self) -> bool {
        self.matcher.is_none() && self.parent.is_none()
    }

    pub fn empty() -> Self {
        Self {
            matcher: None,
            parent: None,
            configured_patterns: GitignoreStyleExcludes::empty(),
            use_nested_gitignore: false,
        }
    }
}
