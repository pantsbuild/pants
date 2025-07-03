// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::Arc;

use deepsize::DeepSizeOf;
use fs::gitignore_stack::GitignoreStack;
use fs::{Dir, DirectoryListing};
use graph::CompoundNode;

use super::{NodeKey, NodeOutput, NodeResult, SubjectPath};
use crate::context::Context;
use crate::python::throw;

///
/// A Node that represents executing a directory listing that returns a Stat per directory
/// entry (generally in one syscall). No symlinks are expanded.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Scandir {
    pub(super) dir: Dir,
    pub(super) subject_path: SubjectPath,
}
impl Scandir {
    pub(super) async fn run_node(self, context: Context) -> NodeResult<Arc<DirectoryListing>> {
        let gitignore_stack = self.parent_gitignore_stack(&context).await?;
        let directory_listing = context
            .core
            .vfs
            .scandir(self.dir, gitignore_stack)
            .await
            .map_err(|e| throw(format!("{e}")))?;
        Ok(Arc::new(directory_listing))
    }

    async fn parent_gitignore_stack(&self, context: &Context) -> NodeResult<GitignoreStack> {
        let root_ignore = context.core.vfs.root_ignore();
        if !context.core.vfs.read_gitignore_files() {
            return Ok(root_ignore.clone());
        };
        let gitignore_stack = {
            if let Some(parent) = self.parent()? {
                &context.get(parent).await?.1
            } else {
                root_ignore
            }
        };
        Ok(gitignore_stack.clone())
    }

    fn parent(&self) -> NodeResult<Option<Scandir>> {
        Ok(self
            .subject_path
            .parent()
            .map_err(throw)?
            .and_then(|subject_path| self.dir.parent().map(|dir| Scandir { dir, subject_path })))
    }
}

impl CompoundNode<NodeKey> for Scandir {
    type Item = Arc<DirectoryListing>;
}

impl From<Scandir> for NodeKey {
    fn from(n: Scandir) -> Self {
        NodeKey::Scandir(n)
    }
}

impl TryFrom<NodeOutput> for Arc<DirectoryListing> {
    type Error = ();

    fn try_from(nr: NodeOutput) -> Result<Self, ()> {
        match nr {
            NodeOutput::DirectoryListing(v) => Ok(v),
            _ => Err(()),
        }
    }
}
