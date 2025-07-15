// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::{Debug, Display};
use std::hash::Hash;

use async_trait::async_trait;

use petgraph::graph;

use crate::context::Context;

// 2^32 Nodes ought to be more than enough for anyone!
pub type EntryId = graph::NodeIndex<u32>;

///
/// Defines executing a cacheable/memoizable step within the given NodeContext.
///
/// Note that it is assumed that Nodes are very cheap to clone.
///
#[async_trait]
pub trait Node: Clone + Debug + Display + Eq + Hash + Send + Sync + 'static {
    /// An implementation-specific context required to run this Node.
    type Context: Send + Sync;

    type Item: Clone + Debug + Eq + Send + Sync + 'static;
    type Error: NodeError;

    async fn run(self, context: Context<Self>) -> Result<Self::Item, Self::Error>;

    ///
    /// True if this Node may be restarted while running. This property is consumed at the point when
    /// a Node might be dirtied, so it's valid for a Node to change its restartable state while running.
    ///
    /// Note that this property does not control whether a Node is cancellable: if all consumers of
    /// a Node go away, it will always be cancelled.
    ///
    fn restartable(&self) -> bool;

    ///
    /// If a node's output is cacheable based solely on properties of the node, and not the output,
    /// return true.
    ///
    /// Nodes which are not cacheable will be recomputed once (at least, in case of dirtying) per
    /// RunId.
    ///
    /// This property must remain stable for the entire lifetime of a particular Node, but a Node
    /// may change its cacheability for a particular output value using `cacheable_item`.
    ///
    fn cacheable(&self) -> bool;

    ///
    /// A Node may want to compute cacheability differently based on properties of the Node's item.
    /// The output of this method will be and'd with `cacheable` to compute overall cacheability.
    ///
    fn cacheable_item(&self, _item: &Self::Item) -> bool {
        self.cacheable()
    }

    ///
    /// Creates an error instance that represents that a Node dependency was cyclic along the given
    /// path.
    ///
    fn cyclic_error(path: &[&Self]) -> Self::Error;
}

pub trait NodeError: Clone + Debug + Eq + Send + Sync {
    ///
    /// Creates a generic Error of type NodeError.
    ///
    fn generic(message: String) -> Self;

    ///
    /// Creates an instance that represents that a Node was invalidated out of the
    /// Graph (generally while running).
    ///
    fn invalidated() -> Self;
}

///
/// A trait to enable easy (un)wrapping in the common case of `enum`-based Nodes. Primarily used
/// with `Context::get`.
///
pub trait CompoundNode<N>: Into<N> + Send
where
    N: Node,
{
    type Item: TryFrom<N::Item>;
}

impl<N: Node> CompoundNode<N> for N {
    type Item = N::Item;
}
