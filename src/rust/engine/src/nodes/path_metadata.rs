// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::Path;

use deepsize::DeepSizeOf;
use graph::CompoundNode;

use super::{NodeKey, NodeOutput, NodeResult, SubjectPath};
use crate::context::Context;
use crate::python::throw;

///
/// A `Node` that represents reading the filesystem metadata of a path.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct PathMetadata {
    pub(super) subject_path: SubjectPath,
}

impl PathMetadata {
    pub fn new(subject_path: SubjectPath) -> Result<Self, String> {
        Ok(Self { subject_path })
    }

    pub fn path(&self) -> &Path {
        match &self.subject_path {
            SubjectPath::Workspace(relpath) => relpath.as_path(),
            SubjectPath::LocalSystem(path) => path,
        }
    }

    pub(super) async fn run_node(self, context: Context) -> NodeResult<Option<fs::PathMetadata>> {
        let (vfs, path) = match &self.subject_path {
            SubjectPath::Workspace(relpath) => (&context.core.vfs, relpath.as_path()),
            SubjectPath::LocalSystem(path) => (&context.core.vfs_system, path.as_path()),
        };

        vfs.path_metadata(path.to_path_buf())
            .await
            .map_err(|e| throw(format!("{e}")))
    }
}

impl CompoundNode<NodeKey> for PathMetadata {
    type Item = Option<fs::PathMetadata>;
}

impl From<PathMetadata> for NodeKey {
    fn from(fs: PathMetadata) -> Self {
        NodeKey::PathMetadata(fs)
    }
}

impl TryFrom<NodeOutput> for Option<fs::PathMetadata> {
    type Error = ();

    fn try_from(nr: NodeOutput) -> Result<Self, ()> {
        match nr {
            NodeOutput::PathMetadata(v) => Ok(v),
            _ => Err(()),
        }
    }
}
