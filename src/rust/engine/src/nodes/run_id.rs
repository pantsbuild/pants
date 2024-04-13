// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use deepsize::DeepSizeOf;
use graph::CompoundNode;
use pyo3::prelude::Python;

use super::{NodeKey, NodeResult};
use crate::context::Context;
use crate::externs;
use crate::python::Value;

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct RunId;

impl RunId {
    pub(super) async fn run_node(self, context: Context) -> NodeResult<Value> {
        Ok(Python::with_gil(|py| {
            externs::unsafe_call(
                py,
                context.core.types.run_id,
                &[externs::store_u64(py, context.session.run_id().0 as u64)],
            )
        }))
    }
}

impl CompoundNode<NodeKey> for RunId {
    type Item = Value;
}

impl From<RunId> for NodeKey {
    fn from(n: RunId) -> Self {
        NodeKey::RunId(n)
    }
}
