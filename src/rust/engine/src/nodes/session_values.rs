// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use deepsize::DeepSizeOf;
use graph::CompoundNode;

use super::{NodeKey, NodeResult};
use crate::context::Context;
use crate::python::Value;

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct SessionValues;

impl SessionValues {
    pub(super) async fn run_node(self, context: Context) -> NodeResult<Value> {
        Ok(Value::new(context.session.session_values()))
    }
}

impl CompoundNode<NodeKey> for SessionValues {
    type Item = Value;
}

impl From<SessionValues> for NodeKey {
    fn from(n: SessionValues) -> Self {
        NodeKey::SessionValues(n)
    }
}
