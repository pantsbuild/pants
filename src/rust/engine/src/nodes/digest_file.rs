// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use deepsize::DeepSizeOf;
use fs::File;
use futures::TryFutureExt;
use graph::CompoundNode;

use super::{NodeKey, NodeOutput, NodeResult};
use crate::context::Context;
use crate::python::throw;

///
/// A Node that represents reading a file and fingerprinting its contents.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct DigestFile(pub File);

impl DigestFile {
    pub(super) async fn run_node(self, context: Context) -> NodeResult<hashing::Digest> {
        let path = context.core.vfs.file_path(&self.0);
        context
            .core
            .store()
            .store_file(true, false, path)
            .map_err(throw)
            .await
    }
}

impl CompoundNode<NodeKey> for DigestFile {
    type Item = hashing::Digest;
}

impl From<DigestFile> for NodeKey {
    fn from(n: DigestFile) -> Self {
        NodeKey::DigestFile(n)
    }
}

impl TryFrom<NodeOutput> for hashing::Digest {
    type Error = ();

    fn try_from(nr: NodeOutput) -> Result<Self, ()> {
        match nr {
            NodeOutput::FileDigest(v) => Ok(v),
            _ => Err(()),
        }
    }
}
