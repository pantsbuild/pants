// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use deepsize::DeepSizeOf;
use internment::Intern;
use rule_graph::DependencyKey;

use super::{NodeKey, NodeResult};
use crate::context::Context;
use crate::python::{Params, TypeId, Value};
use crate::tasks::Rule;

///
/// A root Node in the execution graph.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Root {
    pub params: Params,
    pub(super) product: TypeId,
    entry: Intern<rule_graph::Entry<Rule>>,
}

impl Root {
    pub fn new(
        mut params: Params,
        dependency_key: &DependencyKey<TypeId>,
        edges: &rule_graph::RuleEdges<Rule>,
    ) -> Self {
        let entry = edges.entry_for(dependency_key).unwrap_or_else(|| {
            panic!("{edges:?} did not declare a dependency on {dependency_key:?}")
        });
        params.retain(|k| match entry.as_ref() {
            rule_graph::Entry::Param(type_id) => type_id == k.type_id(),
            rule_graph::Entry::WithDeps(with_deps) => with_deps.params().contains(k.type_id()),
        });
        Self {
            params,
            product: dependency_key.product(),
            entry,
        }
    }

    pub(super) async fn run_node(self, context: Context) -> NodeResult<Value> {
        super::select(context, None, 0, self.params, self.entry).await
    }
}

impl From<Root> for NodeKey {
    fn from(n: Root) -> Self {
        NodeKey::Root(Box::new(n))
    }
}
