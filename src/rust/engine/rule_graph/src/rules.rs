// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::borrow::Cow;
use std::collections::BTreeSet;
use std::fmt::{Debug, Display};
use std::hash::Hash;

use deepsize::DeepSizeOf;
use smallvec::SmallVec;

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

// Identifies a specific Rule when called by name.
// TODO: Turn into a generic type param, so that production code can wrap `Function`. For now this
// is just a newtype, for clarity.
#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug, PartialOrd, Ord)]
pub struct RuleId(String);

impl RuleId {
    pub fn new(id: &str) -> Self {
        Self(id.into())
    }

    pub fn from_string(s: String) -> Self {
        Self(s)
    }
}

impl Display for RuleId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug, PartialOrd, Ord)]
pub struct CallSignature {
    // The id of the rule that is being called.
    pub rule_id: RuleId,
    // The number of explicit positional arguments that were passed.
    pub explicit_args_arity: u16,
}

// NB: Most of our expected usecases for multiple-provided-parameters involve two parameters, hence
// the SmallVec sizing here. See also `Self::provides`.
#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug, PartialOrd, Ord)]
pub struct DependencyKey<T: TypeId> {
    // If this dependency represents a by-name call to a known rule, the signature of the call.
    pub call_signature: Option<CallSignature>,
    // The output type produced by this dependency.
    pub product: T,
    // The param types which are introduced into scope at the callsite ("provided").
    pub provided_params: SmallVec<[T; 2]>,
    // The param types which must already be in scope at the callsite, regardless of whether they
    // are consumed in order to produce the product type.
    //
    // If a `DependencyKey` declares any `in_scope_params`, then _only_ those params (and provided
    // params) are available to the callee.
    pub in_scope_params: Option<SmallVec<[T; 2]>>,
}

impl<T: TypeId> DependencyKey<T> {
    pub fn new(product: T) -> Self {
        DependencyKey {
            call_signature: None,
            product,
            provided_params: SmallVec::default(),
            in_scope_params: None,
        }
    }

    pub fn for_known_rule(rule_id: RuleId, product: T, explicit_args_arity: u16) -> Self {
        DependencyKey {
            call_signature: Some(CallSignature {
                rule_id,
                explicit_args_arity,
            }),
            product,
            provided_params: SmallVec::default(),
            in_scope_params: None,
        }
    }

    pub fn provided_params<I: IntoIterator<Item = T>>(self, provided_params: I) -> Self {
        let mut provided_params = provided_params.into_iter().collect::<SmallVec<[T; 2]>>();
        provided_params.sort();

        #[cfg(debug_assertions)]
        {
            let original_len = provided_params.len();
            provided_params.dedup();
            if original_len != provided_params.len() {
                panic!("Expected unique provided params.");
            }
        }

        Self {
            provided_params,
            ..self
        }
    }

    pub fn in_scope_params<I: IntoIterator<Item = T>>(self, in_scope_params: I) -> Self {
        let mut in_scope_params = in_scope_params.into_iter().collect::<SmallVec<[T; 2]>>();
        in_scope_params.sort();

        #[cfg(debug_assertions)]
        {
            let original_len = in_scope_params.len();
            in_scope_params.dedup();
            if original_len != in_scope_params.len() {
                panic!("Expected unique in_scope params.");
            }
        }

        Self {
            in_scope_params: Some(in_scope_params),
            ..self
        }
    }

    ///
    /// Returns the product (output) type for this dependency.
    ///
    pub fn product(&self) -> T {
        self.product
    }

    ///
    /// True if this DependencyKey provides the given type.
    ///
    /// NB: This is a linear scan, but that should be fine for small numbers of provided
    /// params: see the struct doc.
    ///
    pub fn provides(&self, t: &T) -> bool {
        self.provided_params.contains(t)
    }

    ///
    /// If this DependencyKey has in_scope_params, returns an equivalent Query,
    ///
    pub fn as_reentry_query(&self) -> Option<Query<T>> {
        self.in_scope_params.as_ref().map(|in_scope_params| {
            Query::new(
                self.product,
                self.provided_params
                    .iter()
                    .chain(in_scope_params.iter())
                    .cloned(),
            )
        })
    }
}

impl<T: TypeId> Display for DependencyKey<T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if let Some(call_signature) = &self.call_signature {
            let explicit_args_arity: Cow<str> = if call_signature.explicit_args_arity > 0 {
                format!("<{}>, ", call_signature.explicit_args_arity).into()
            } else {
                "".into()
            };
            let provided_params: Cow<str> = if self.provided_params.is_empty() {
                "".into()
            } else {
                format!(
                    "**implicitly({})",
                    self.provided_params
                        .iter()
                        .map(|p| p.to_string())
                        .collect::<Vec<_>>()
                        .join(", ")
                )
                .into()
            };
            write!(
                f,
                "{}({}, {}) -> {}",
                call_signature.rule_id, explicit_args_arity, provided_params, self.product
            )
        } else if self.provided_params.is_empty() {
            write!(f, "{}", self.product)
        } else {
            write!(f, "Get({}, {:?})", self.product, self.provided_params)
        }
    }
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

    ///
    /// Returns the id of this Rule.
    ///
    fn id(&self) -> &RuleId;

    ///
    /// Returns the product (output) type for this Rule.
    ///
    fn product(&self) -> Self::TypeId;

    ///
    /// Return keys for the dependencies of this Rule, with the given prefix count of explicitly
    /// provided arguments excluded.
    ///
    fn dependency_keys(&self, explicit_args_arity: u16) -> Vec<&DependencyKey<Self::TypeId>>;

    ///
    /// Returns types which this rule is not allowed to consume from the calling scope.
    ///
    fn masked_params(&self) -> Vec<Self::TypeId>;

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
pub struct Query<T: TypeId> {
    pub product: T,
    pub params: ParamTypes<T>,
}

impl<T: TypeId> Query<T> {
    pub fn new<I: IntoIterator<Item = T>>(product: T, params: I) -> Query<T> {
        Query {
            product,
            params: params.into_iter().collect(),
        }
    }
}

impl<T: TypeId> Display for Query<T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{}",
            self.fmt_for_graph(DisplayForGraphArgs { multiline: false })
        )
    }
}

impl<T: TypeId> DisplayForGraph for Query<T> {
    fn fmt_for_graph(&self, _: DisplayForGraphArgs) -> String {
        format!("Query({} for {})", self.product, params_str(&self.params))
    }
}
