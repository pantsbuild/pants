// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::{Debug, Display};
use std::hash::Hash;

use super::Palette;

pub trait TypeId: Clone + Copy + Debug + Display + Hash + Eq + Ord + Sized + 'static {
  ///
  /// Render a string for a collection of TypeIds.
  ///
  fn display<I>(type_ids: I) -> String
  where
    I: Iterator<Item = Self>;
}

pub trait DependencyKey: Clone + Copy + Debug + Display + Hash + Eq + Sized + 'static {
  type TypeId: TypeId;

  ///
  /// Generate a DependencyKey for a dependency at the "root" of the RuleGraph, which represents an
  /// entrypoint into the set of installed Rules.
  ///
  fn new_root(product: Self::TypeId) -> Self;

  ///
  /// Returns the product (output) type for this dependency.
  ///
  fn product(&self) -> Self::TypeId;

  ///
  /// Returns the Param (input) type for this dependency, if it provides one.
  ///
  fn provided_param(&self) -> Option<Self::TypeId>;
}

pub trait DisplayForGraph {
  ///
  /// Return a pretty-printed representation of this Rule's graph node, suitable for graphviz.
  ///
  fn fmt_for_graph(&self) -> String;
}

pub trait Rule: Clone + Debug + Display + Hash + Eq + Sized + DisplayForGraph + 'static {
  type TypeId: TypeId;
  type DependencyKey: DependencyKey<TypeId = Self::TypeId>;

  ///
  /// Return keys for the dependencies of this Rule.
  ///
  fn dependency_keys(&self) -> Vec<Self::DependencyKey>;

  ///
  /// True if this rule implementation should be required to be reachable in the RuleGraph.
  ///
  fn require_reachable(&self) -> bool;

  ///
  /// Return any specific color this rule should be drawn with on the visualized graph. Note that
  /// this coloration setting may be superseded by other factors.
  ///
  fn color(&self) -> Option<Palette>;
}
