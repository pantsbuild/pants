// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::{Debug, Display};
use std::future::Future;
use std::hash::Hash;

use async_trait::async_trait;

use crate::entry::{Entry, RunToken};
use crate::Graph;

// 2^32 Nodes ought to be more than enough for anyone!
// TODO: Consider renaming to NodeId.
pub type EntryId = petgraph::graph::NodeIndex<u32>;
pub type EdgeId = petgraph::graph::EdgeIndex<u32>;

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
}

pub trait NodeError: Clone + Debug + Eq + Send {
  ///
  /// Creates an instance that represents that a Node was invalidated out of the
  /// Graph (generally while running).
  ///
  fn invalidated() -> Self;

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
  type SessionId: Clone + Debug + Eq + Send;

  ///
  /// Creates a clone of this NodeContext to be used for a different Node, or different run of the
  /// same Node.
  ///
  /// To clone a Context for use for the same run of the same Node, `Clone` is used directly.
  ///
  fn clone_for(&self, entry_id: EntryId, run_token: RunToken) -> <Self::Node as Node>::Context;

  ///
  /// If this Context is associated with a run of a particular Node, returns its EntryId and
  /// RunToken. A Context used at the root of the Graph will not be associated with any particular
  /// Node, but all other Contexts are created via `clone_for` for a particular Node's run.
  ///
  fn entry_id_and_run_token(&self) -> Option<(EntryId, RunToken)>;

  ///
  /// Returns the SessionId for this Context, which should uniquely identify a caller's session for
  /// the purposes of "once per Session" behaviour.
  ///
  fn session_id(&self) -> &Self::SessionId;

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
