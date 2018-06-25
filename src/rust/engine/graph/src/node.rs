// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::Debug;
use std::hash::Hash;

use boxfuture::BoxFuture;
use hashing::Digest;

use petgraph::stable_graph;

use Graph;

// 2^32 Nodes ought to be more than enough for anyone!
pub type EntryId = stable_graph::NodeIndex<u32>;

///
/// Defines executing a cacheable/memoizable step within the given NodeContext.
///
pub trait Node: Clone + Eq + Hash + Send + 'static {
  type Context: NodeContext<Node = Self>;

  type Item: Clone + Debug + Send + 'static;
  type Error: NodeError;

  fn run(self, context: Self::Context) -> BoxFuture<Self::Item, Self::Error>;

  // TODO: Use a `Display` bound instead.
  fn format(&self) -> String;

  ///
  /// If the given Node output represents an FS operation, returns its Digest.
  ///
  fn digest(result: Self::Item) -> Option<Digest>;
}

pub trait NodeError: Clone + Debug + Send {
  ///
  /// Creates an instance that represents that a Node was invalidated out of the
  /// Graph (generally while running).
  ///
  fn invalidated() -> Self;

  ///
  /// Creates an instance that represents that a Node dependency was cyclic.
  ///
  fn cyclic() -> Self;
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
  /// Returns a GraphViz color name/id within Self::color_scheme for the given Node/result.
  ///
  fn color(&mut self, node: &N, result: Option<Result<N::Item, N::Error>>) -> String;
}

///
/// A trait used to visualize Nodes for the purposes of CLI-output tracing.
///
pub trait NodeTracer<N: Node> {
  ///
  /// Returns true if the given Node Result represents the "bottom" of a trace.
  ///
  fn is_bottom(result: Option<Result<N::Item, N::Error>>) -> bool;

  ///
  /// Renders the given result for a trace. The trace will already be indented by `indent`, but
  /// an implementer creating a multi-line output would need to indent them as well.
  ///
  fn state_str(indent: &str, result: Option<Result<N::Item, N::Error>>) -> String;
}

///
/// A context passed between Nodes that also stores an EntryId to uniquely identify them.
///
pub trait NodeContext: Clone + Send + 'static {
  ///
  /// The type generated when this Context is cloned for another Node.
  ///
  type Node: Node;

  ///
  /// Creates a clone of this NodeContext to be used for a different Node.
  ///
  /// To clone a Context for use for the same Node, `Clone` is used directly.
  ///
  fn clone_for(&self, entry_id: EntryId) -> <Self::Node as Node>::Context;

  ///
  /// Returns a reference to the Graph for this Context.
  ///
  fn graph(&self) -> &Graph<Self::Node>;
}
