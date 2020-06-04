// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::{Debug, Display};
use std::future::Future;
use std::hash::Hash;

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

  type Item: Clone + Debug + Eq + Send + 'static;
  type Error: NodeError;

  async fn run(self, context: Self::Context) -> Result<Self::Item, Self::Error>;

  ///
  /// If the node result is cacheable, return true.
  ///
  fn cacheable(&self) -> bool;

  /// Nodes optionally have a user-facing name (distinct from their Debug and Display
  /// implementations). This user-facing name is intended to provide high-level information
  /// to end users of pants about what computation pants is currently doing. Not all
  /// `Node`s need a user-facing name. For `Node`s derived from Python `@rule`s, the
  /// user-facing name should be the same as the `desc` annotation on the rule decorator.
  fn user_facing_name(&self) -> Option<String> {
    None
  }

  /// Provides the `name` field in workunits associated with this node. These names
  /// should be friendly to machine-parsing (i.e. "my_node" rather than "My awesome node!").
  fn workunit_name(&self) -> String;
}

pub trait NodeError: Clone + Debug + Eq + Send {
  ///
  /// Creates an instance that represents that a Node was invalidated out of the
  /// Graph (generally while running).
  ///
  fn invalidated() -> Self;
  ///
  /// Creates an instance that represents an uncacheable node failing from
  /// retrying its dependencies too many times, but never able to resolve them,
  /// usually because they were invalidated too many times while running.
  ///
  fn exhausted() -> Self;

  ///
  /// Creates an instance that represents that a Node dependency was cyclic along the given path.
  ///
  fn cyclic(path: Vec<String>) -> Self;
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
