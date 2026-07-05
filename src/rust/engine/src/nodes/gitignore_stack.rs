// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use deepsize::DeepSizeOf;
use fs::Dir;
use fs::gitignore_stack::GitignoreStack;
use graph::CompoundNode;

use super::{NodeKey, NodeOutput, NodeResult, SubjectPath};
use crate::context::Context;
use crate::python::throw;

///
/// A Node that computes the GitignoreStack applying within a directory: the parent directory's
/// stack, extended with this directory's .gitignore file (if any).
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct GitignoreStackForDir {
    pub(super) dir: Dir,
    pub(super) subject_path: SubjectPath,
}

impl GitignoreStackForDir {
    pub fn for_dir(dir: Dir) -> Result<Self, String> {
        let subject_path = SubjectPath::new_workspace(dir.0.join(".gitignore"))?;
        Ok(Self { dir, subject_path })
    }

    pub(super) async fn run_node(self, context: Context) -> NodeResult<GitignoreStack> {
        let vfs = &context.core.vfs;
        let parent_stack = match self.parent()? {
            Some(parent) => context.get(parent).await?,
            None => vfs.root_ignore().clone(),
        };
        vfs.push_gitignore_file(&self.dir, parent_stack)
            .await
            .map_err(|e| throw(format!("{e}")))
    }

    fn parent(&self) -> NodeResult<Option<GitignoreStackForDir>> {
        self.dir
            .parent()
            .map(|dir| Self::for_dir(dir).map_err(throw))
            .transpose()
    }
}

impl CompoundNode<NodeKey> for GitignoreStackForDir {
    type Item = GitignoreStack;
}

impl From<GitignoreStackForDir> for NodeKey {
    fn from(n: GitignoreStackForDir) -> Self {
        NodeKey::GitignoreStackForDir(n)
    }
}

impl TryFrom<NodeOutput> for GitignoreStack {
    type Error = ();

    fn try_from(nr: NodeOutput) -> Result<Self, ()> {
        match nr {
            NodeOutput::GitignoreStack(v) => Ok(v),
            _ => Err(()),
        }
    }
}
