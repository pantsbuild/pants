// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::{Path, PathBuf};

use deepsize::DeepSizeOf;
use graph::CompoundNode;

use super::{NodeKey, NodeOutput, NodeResult};
use crate::context::Context;
use crate::python::throw;

///
/// A `Node` that represents reading the filesystem metadata of a path.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct PathMetadata {
    path: PathBuf,
}

impl PathMetadata {
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub(super) async fn run_node(self, context: Context) -> NodeResult<Option<fs::PathMetadata>> {
        let node = self;
        context
            .core
            .vfs
            .path_metadata(node.path.clone())
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
