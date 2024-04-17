// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::PathBuf;

use deepsize::DeepSizeOf;
use fs::Link;
use graph::CompoundNode;

use super::{NodeKey, NodeOutput, NodeResult};
use crate::context::Context;
use crate::python::throw;

///
/// A Node that represents reading the destination of a symlink (non-recursively).
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct ReadLink(pub(super) Link);

impl ReadLink {
    pub(super) async fn run_node(self, context: Context) -> NodeResult<LinkDest> {
        let node = self;
        let link_dest = context
            .core
            .vfs
            .read_link(&node.0)
            .await
            .map_err(|e| throw(format!("{e}")))?;
        Ok(LinkDest(link_dest))
    }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub struct LinkDest(pub(super) PathBuf);

impl CompoundNode<NodeKey> for ReadLink {
    type Item = LinkDest;
}

impl From<ReadLink> for NodeKey {
    fn from(n: ReadLink) -> Self {
        NodeKey::ReadLink(n)
    }
}

impl TryFrom<NodeOutput> for LinkDest {
    type Error = ();

    fn try_from(nr: NodeOutput) -> Result<Self, ()> {
        match nr {
            NodeOutput::LinkDest(v) => Ok(v),
            _ => Err(()),
        }
    }
}
