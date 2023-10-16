// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::{Debug, Display};
use std::future::Future;
use std::hash::Hash;
use std::ops::DerefMut;

use async_trait::async_trait;

use petgraph::stable_graph;

use crate::entry::Entry;
use crate::Graph;

// 2^32 Nodes ought to be more than enough for anyone!
pub type EntryId = stable_graph::NodeIndex<u32>;

///
/// Defines executing a cacheable/memoizable step within the given NodeContext.
///
/// Note that it is assumed that Nodes are very cheap to clone.
///
#[async_trait]
pub trait Node: Clone + Debug + Display + Eq + Hash + Send + 'static {
    type Context: NodeContext<Node = Self>;

    type Item: Clone + Debug + Eq + Send + Sync + 'static;
    type Error: NodeError;

    async fn run(self, context: Self::Context) -> Result<Self::Item, Self::Error>;

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
    /// Creates an instance that represents that a Node was invalidated out of the
    /// Graph (generally while running).
    ///
    fn invalidated() -> Self;
}

///
/// A trait used to visualize Nodes in either DOT/GraphViz format.
///
pub trait NodeVisualizer<N: Node> {
    ///
    /// Returns a GraphViz color scheme name for this visualizer.
    ///
    fn color_scheme(&self) -> &str;

    ///
    /// Returns a GraphViz color name/id within Self::color_scheme for the given Entry.
    ///
    fn color(&mut self, entry: &Entry<N>, context: &N::Context) -> String;
}

///
/// A context passed between Nodes that also stores an EntryId to uniquely identify them.
///
pub trait NodeContext: Clone + Send + Sync + 'static {
    ///
    /// The type generated when this Context is cloned for another Node.
    ///
    type Node: Node;

    ///
    /// The Run ID type for this Context. Some Node behaviours have Run-specific semantics. In
    /// particular: an uncacheable (Node::cacheable) Node will execute once per Run, regardless
    /// of other invalidation.
    ///
    type RunId: Clone + Debug + Eq + Send;

    ///
    /// Return a reference to a Stats instance that the Graph will use to record relevant statistics
    /// about a run.
    ///
    /// TODO: This API is awkward because it assumes that you need a lock inside your NodeContext
    /// implementation. We should likely make NodeContext a concrete struct with a type parameter
    /// for other user specific context rather than having such a large trait.
    ///
    fn stats<'a>(&'a self) -> Box<dyn DerefMut<Target = Stats> + 'a>;

    ///
    /// Creates a clone of this NodeContext to be used for a different Node.
    ///
    /// To clone a Context for use for the same Node, `Clone` is used directly.
    ///
    fn clone_for(&self, entry_id: EntryId) -> <Self::Node as Node>::Context;

    ///
    /// Returns the RunId for this Context, which should uniquely identify a caller's run for the
    /// purposes of "once per Run" behaviour.
    ///
    fn run_id(&self) -> &Self::RunId;

    ///
    /// Returns a reference to the Graph for this Context.
    ///
    fn graph(&self) -> &Graph<Self::Node>;

    ///
    /// Spawns a Future on an Executor provided by the context.
    ///
    /// NB: Unlike the futures `Executor` trait itself, this implementation _must_ spawn the work
    /// on another thread, as it is called from within the Graph lock.
    ///
    fn spawn<F>(&self, future: F)
    where
        F: Future<Output = ()> + Send + 'static;
}

#[derive(Default)]
pub struct Stats {
    pub ran: usize,
    pub cleaning_succeeded: usize,
    pub cleaning_failed: usize,
}
