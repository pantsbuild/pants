// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::BTreeSet;
use std::fmt::{Debug, Display};
use std::hash::Hash;

use deepsize::DeepSizeOf;

use super::{params_str, Palette};

pub type ParamTypes<T> = BTreeSet<T>;

pub trait TypeId:
    Clone + Copy + Debug + DeepSizeOf + Display + Hash + Eq + Ord + Sized + Send + Sync + 'static
{
    ///
    /// Render a string for a collection of TypeIds.
    ///
    fn display<I>(type_ids: I) -> String
    where
        I: Iterator<Item = Self>;
}

pub trait DependencyKey:
    Clone + Copy + Debug + Display + Hash + Ord + Eq + Sized + 'static
{
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
    fn fmt_for_graph(&self, display_args: DisplayForGraphArgs) -> String;
}

///
/// A struct to contain display options consumed by DisplayForGraph.
///
#[derive(Clone, Copy)]
pub struct DisplayForGraphArgs {
    pub multiline: bool,
}

impl DisplayForGraphArgs {
    pub fn line_separator(&self) -> &'static str {
        if self.multiline {
            "\n"
        } else {
            " "
        }
    }

    pub fn optional_line_separator(&self) -> &'static str {
        if self.multiline {
            "\n"
        } else {
            ""
        }
    }
}

pub trait Rule:
    Clone + Debug + Display + Hash + Eq + Sized + DisplayForGraph + Send + Sync + 'static
{
    type TypeId: TypeId;
    type DependencyKey: DependencyKey<TypeId = Self::TypeId>;

    ///
    /// Returns the product (output) type for this Rule.
    ///
    fn product(&self) -> Self::TypeId;

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

#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug)]
pub struct Query<R: Rule> {
    pub product: R::TypeId,
    pub params: ParamTypes<R::TypeId>,
}

impl<R: Rule> Query<R> {
    pub fn new<I: IntoIterator<Item = R::TypeId>>(product: R::TypeId, params: I) -> Query<R> {
        Query {
            product,
            params: params.into_iter().collect(),
        }
    }
}

impl<R: Rule> Display for Query<R> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{}",
            self.fmt_for_graph(DisplayForGraphArgs { multiline: false })
        )
    }
}

impl<R: Rule> DisplayForGraph for Query<R> {
    fn fmt_for_graph(&self, _: DisplayForGraphArgs) -> String {
        format!("Query({} for {})", self.product, params_str(&self.params))
    }
}
