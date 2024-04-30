// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::Arc;

use deepsize::DeepSizeOf;
use fs::{Dir, DirectoryListing};
use graph::CompoundNode;

use super::{NodeKey, NodeOutput, NodeResult};
use crate::context::Context;
use crate::python::throw;

///
/// A Node that represents executing a directory listing that returns a Stat per directory
/// entry (generally in one syscall). No symlinks are expanded.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Scandir(pub(super) Dir);

impl Scandir {
    pub(super) async fn run_node(self, context: Context) -> NodeResult<Arc<DirectoryListing>> {
        let directory_listing = context
            .core
            .vfs
            .scandir(self.0)
            .await
            .map_err(|e| throw(format!("{e}")))?;
        Ok(Arc::new(directory_listing))
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
