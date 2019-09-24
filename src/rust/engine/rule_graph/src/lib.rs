// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::single_match_else,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

mod builder;
mod rules;

use std::collections::{BTreeSet, HashMap, HashSet};
use std::io;

pub use crate::builder::Builder;
pub use crate::rules::{DependencyKey, Rule, TypeId};

// TODO: Consider switching to HashSet and dropping the Ord bound from TypeId.
type ParamTypes<T> = BTreeSet<T>;

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct UnreachableError<R: Rule> {
  rule: R,
  diagnostic: Diagnostic<R::TypeId>,
}

impl<R: Rule> UnreachableError<R> {
  fn new(rule: R) -> UnreachableError<R> {
    UnreachableError {
      rule,
      diagnostic: Diagnostic {
        params: ParamTypes::default(),
        reason: "Was not usable by any other @rule.".to_string(),
        details: vec![],
      },
    }
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum EntryWithDeps<R: Rule> {
  Root(RootEntry<R>),
  Inner(InnerEntry<R>),
}

impl<R: Rule> EntryWithDeps<R> {
  pub fn params(&self) -> &ParamTypes<R::TypeId> {
    match self {
      EntryWithDeps::Inner(ref ie) => &ie.params,
      EntryWithDeps::Root(ref re) => &re.params,
    }
  }

  ///
  /// Returns the set of DependencyKeys representing the dependencies of this EntryWithDeps.
  ///
  fn dependency_keys(&self) -> Vec<R::DependencyKey> {
    match self {
      EntryWithDeps::Inner(InnerEntry { ref rule, .. }) => rule.dependency_keys(),
      EntryWithDeps::Root(RootEntry {
        ref dependency_key, ..
      }) => vec![*dependency_key],
    }
  }

  ///
  /// Given a set of used parameters (which must be a subset of the parameters available here),
  /// return a clone of this entry with its parameter set reduced to the used parameters.
  ///
  fn simplified(&self, used_params: ParamTypes<R::TypeId>) -> EntryWithDeps<R> {
    let mut simplified = self.clone();
    {
      let simplified_params = match &mut simplified {
        EntryWithDeps::Inner(ref mut ie) => &mut ie.params,
        EntryWithDeps::Root(ref mut re) => &mut re.params,
      };

      let unavailable_params: ParamTypes<_> =
        used_params.difference(simplified_params).cloned().collect();
      assert!(
        unavailable_params.is_empty(),
        "Entry {} used parameters that were not available: {}",
        entry_with_deps_str(self),
        params_str(&unavailable_params),
      );

      *simplified_params = used_params;
    }
    simplified
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum Entry<R: Rule> {
  Param(R::TypeId),
  WithDeps(EntryWithDeps<R>),
}

impl<R: Rule> Entry<R> {
  fn params(&self) -> Vec<R::TypeId> {
    match self {
      Entry::WithDeps(ref e) => e.params().iter().cloned().collect(),
      Entry::Param(ref type_id) => vec![*type_id],
    }
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct RootEntry<R: Rule> {
  params: ParamTypes<R::TypeId>,
  dependency_key: R::DependencyKey,
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct InnerEntry<R: Rule> {
  params: ParamTypes<R::TypeId>,
  rule: R,
}

impl<R: Rule> InnerEntry<R> {
  pub fn rule(&self) -> &R {
    &self.rule
  }
}

type RuleDependencyEdges<R> = HashMap<EntryWithDeps<R>, RuleEdges<R>>;
type UnfulfillableRuleMap<R> = HashMap<EntryWithDeps<R>, Vec<Diagnostic<<R as Rule>::TypeId>>>;

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct Diagnostic<T: TypeId> {
  params: ParamTypes<T>,
  reason: String,
  details: Vec<String>,
}

///
/// A graph containing rules mapping rules to their dependencies taking into account subject types.
///
/// This is a graph of rules. It models dependencies between rules, along with the subject types for
/// those rules. This allows the resulting graph to include cases where a selector is fulfilled by
/// the subject of the graph.
///
///
/// `root_param_types` the root parameter types that this graph was generated with.
/// `root_dependencies` A map from root rules, ie rules representing the expected selector / subject
///   types for requests, to the rules that can fulfill them.
/// `rule_dependency_edges` A map from rule entries to the rule entries they depend on.
///   The collections of dependencies are contained by RuleEdges objects.
/// `unfulfillable_rules` A map of rule entries to collections of Diagnostics
///   containing the reasons why they were eliminated from the graph.
#[derive(Debug)]
pub struct RuleGraph<R: Rule> {
  root_param_types: ParamTypes<R::TypeId>,
  rule_dependency_edges: RuleDependencyEdges<R>,
  unfulfillable_rules: UnfulfillableRuleMap<R>,
  unreachable_rules: Vec<UnreachableError<R>>,
}

// TODO: We can't derive this due to https://github.com/rust-lang/rust/issues/26925, which
// unnecessarily requires `Rule: Default`.
impl<R: Rule> Default for RuleGraph<R> {
  fn default() -> Self {
    RuleGraph {
      root_param_types: ParamTypes::default(),
      rule_dependency_edges: RuleDependencyEdges::default(),
      unfulfillable_rules: UnfulfillableRuleMap::default(),
      unreachable_rules: Vec::default(),
    }
  }
}

fn params_str<T: TypeId>(params: &ParamTypes<T>) -> String {
  T::display(params.iter().cloned())
}

///
/// TODO: Move all of these methods to Display impls.
///
fn entry_str<R: Rule>(entry: &Entry<R>) -> String {
  match entry {
    Entry::WithDeps(ref e) => entry_with_deps_str(e),
    Entry::Param(type_id) => format!("Param({})", type_id),
  }
}

fn entry_with_deps_str<R: Rule>(entry: &EntryWithDeps<R>) -> String {
  match entry {
    EntryWithDeps::Inner(InnerEntry {
      ref rule,
      ref params,
    }) => format!("{} for {}", rule, params_str(params)),
    EntryWithDeps::Root(ref root) => {
      // TODO: Consider dropping this (final) public use of the keyword "Select", while ensuring
      // that error messages remain sufficiently grokkable.
      format!(
        "Select({}) for {}",
        root.dependency_key,
        params_str(&root.params),
      )
    }
  }
}

impl<R: Rule> RuleGraph<R> {
  pub fn new(tasks: &HashMap<R::TypeId, Vec<R>>, root_param_types: Vec<R::TypeId>) -> RuleGraph<R> {
    Builder::new(tasks, root_param_types).full_graph()
  }

  pub fn find_root_edges<I: IntoIterator<Item = R::TypeId>>(
    &self,
    param_inputs: I,
    product: R::TypeId,
  ) -> Result<RuleEdges<R>, String> {
    let params: ParamTypes<_> = param_inputs.into_iter().collect();
    let dependency_key = R::DependencyKey::new_root(product);
    let root = RootEntry {
      params: params.clone(),
      dependency_key,
    };

    // Attempt to find an exact match.
    if let Some(re) = self.rule_dependency_edges.get(&EntryWithDeps::Root(root)) {
      return Ok(re.clone());
    }

    // Otherwise, scan for partial/subset matches.
    // TODO: Is it worth indexing this by product type?
    let subset_matches = self
      .rule_dependency_edges
      .iter()
      .filter_map(|(entry, edges)| match entry {
        EntryWithDeps::Root(ref root_entry)
          if root_entry.dependency_key == dependency_key
            && root_entry.params.is_subset(&params) =>
        {
          Some((entry, edges))
        }
        _ => None,
      })
      .collect::<Vec<_>>();

    match subset_matches.len() {
      1 => Ok(subset_matches[0].1.clone()),
      0 if params.is_subset(&self.root_param_types) => {
        // The Params were all registered as RootRules, but the combination wasn't legal.
        let mut suggestions: Vec<_> = self
          .rule_dependency_edges
          .keys()
          .filter_map(|entry| match entry {
            EntryWithDeps::Root(ref root_entry) if root_entry.dependency_key == dependency_key => {
              Some(format!("Params({})", params_str(&root_entry.params)))
            }
            _ => None,
          })
          .collect();
        let suggestions_str = if suggestions.is_empty() {
          ".".to_string()
        } else {
          suggestions.sort();
          format!(
            ", but there were @rules that could compute it using:\n  {}",
            suggestions.join("\n  ")
          )
        };
        Err(format!(
          "No installed @rules can compute {} for input Params({}){}",
          product,
          params_str(&params),
          suggestions_str,
        ))
      }
      0 => {
        // Some Param(s) were not registered.
        let mut unregistered_params: Vec<_> = params
          .difference(&self.root_param_types)
          .map(|p| p.to_string())
          .collect();
        unregistered_params.sort();
        Err(format!(
          "Types that will be passed as Params at the root of a graph need to be registered via RootRule:\n  {}",
          unregistered_params.join("\n  "),
        ))
      }
      _ => {
        let match_strs = subset_matches
          .into_iter()
          .map(|(e, _)| entry_with_deps_str(e))
          .collect::<Vec<_>>();
        Err(format!(
          "More than one set of @rules can compute {} for input Params({}):\n  {}",
          product,
          params_str(&params),
          match_strs.join("\n  "),
        ))
      }
    }
  }

  ///
  /// TODO: It's not clear what is preventing `Node` implementations from ending up with non-Inner
  /// entries, but it would be good to make it typesafe instead.
  ///
  pub fn edges_for_inner(&self, entry: &Entry<R>) -> Option<RuleEdges<R>> {
    if let Entry::WithDeps(ref e) = entry {
      self.rule_dependency_edges.get(e).cloned()
    } else {
      panic!("not an inner entry! {:?}", entry)
    }
  }

  pub fn validate(&self) -> Result<(), String> {
    let mut collated_errors: HashMap<R, Vec<Diagnostic<_>>> = HashMap::new();

    let used_rules: HashSet<_> = self
      .rule_dependency_edges
      .keys()
      .filter_map(|entry| match entry {
        EntryWithDeps::Inner(InnerEntry { ref rule, .. }) => Some(rule),
        _ => None,
      })
      .collect();

    // Collect and dedupe rule diagnostics, preferring to render an unfulfillable error for a rule
    // over an unreachable error.
    let mut rule_diagnostics: HashMap<_, _> = self
      .unreachable_rules
      .iter()
      .map(|u| (&u.rule, vec![u.diagnostic.clone()]))
      .collect();
    for (e, diagnostics) in &self.unfulfillable_rules {
      match e {
        EntryWithDeps::Inner(InnerEntry { ref rule, .. })
          if rule.require_reachable() && !diagnostics.is_empty() && !used_rules.contains(&rule) =>
        {
          rule_diagnostics.insert(rule, diagnostics.clone());
        }
        _ => {}
      }
    }
    for (rule, diagnostics) in rule_diagnostics {
      for d in diagnostics {
        collated_errors
          .entry(rule.clone())
          .or_insert_with(Vec::new)
          .push(d);
      }
    }

    if collated_errors.is_empty() {
      return Ok(());
    }

    let mut msgs: Vec<String> = collated_errors
      .into_iter()
      .map(|(rule, mut diagnostics)| {
        diagnostics.sort_by(|l, r| l.reason.cmp(&r.reason));
        diagnostics.dedup_by(|l, r| l.reason == r.reason);
        let errors = diagnostics
          .into_iter()
          .map(|mut d| {
            if d.details.is_empty() {
              d.reason.clone()
            } else {
              d.details.sort();
              format!("{}:\n      {}", d.reason, d.details.join("\n      "))
            }
          })
          .collect::<Vec<_>>()
          .join("\n    ");
        format!("{}:\n    {}", rule, errors)
      })
      .collect();
    msgs.sort();

    Err(format!("Rules with errors: {}\n  {}", msgs.len(), msgs.join("\n  ")).to_string())
  }

  pub fn visualize(&self, f: &mut dyn io::Write) -> io::Result<()> {
    let mut root_subject_type_strs = self
      .root_param_types
      .iter()
      .map(|&t| format!("{}", t))
      .collect::<Vec<String>>();
    root_subject_type_strs.sort();
    writeln!(f, "digraph {{")?;
    writeln!(
      f,
      "  // root subject types: {}",
      root_subject_type_strs.join(", ")
    )?;
    writeln!(f, "  // root entries")?;
    let mut root_rule_strs = self
      .rule_dependency_edges
      .iter()
      .filter_map(|(k, deps)| match k {
        EntryWithDeps::Root(_) => {
          let root_str = entry_with_deps_str(k);
          Some(format!(
            "    \"{}\" [color=blue]\n    \"{}\" -> {{{}}}",
            root_str,
            root_str,
            deps
              .all_dependencies()
              .map(|d| format!("\"{}\"", entry_str(d)))
              .collect::<Vec<String>>()
              .join(" ")
          ))
        }
        _ => None,
      })
      .collect::<Vec<String>>();
    root_rule_strs.sort();
    writeln!(f, "{}", root_rule_strs.join("\n"))?;

    writeln!(f, "  // internal entries")?;
    let mut internal_rule_strs = self
      .rule_dependency_edges
      .iter()
      .filter_map(|(k, deps)| match k {
        EntryWithDeps::Inner(_) => {
          let mut deps_strs = deps
            .all_dependencies()
            .map(|d| format!("\"{}\"", entry_str(d)))
            .collect::<Vec<String>>();
          deps_strs.sort();
          Some(format!(
            "    \"{}\" -> {{{}}}",
            entry_with_deps_str(k),
            deps_strs.join(" ")
          ))
        }
        _ => None,
      })
      .collect::<Vec<String>>();
    internal_rule_strs.sort();
    writeln!(f, "{}", internal_rule_strs.join("\n"))?;
    writeln!(f, "}}")
  }
}

///
/// Records the dependency rules for a rule.
///
#[derive(Eq, PartialEq, Clone, Debug)]
pub struct RuleEdges<R: Rule> {
  dependencies: HashMap<R::DependencyKey, Vec<Entry<R>>>,
}

impl<R: Rule> RuleEdges<R> {
  pub fn entry_for(&self, dependency_key: &R::DependencyKey) -> Option<&Entry<R>> {
    self
      .dependencies
      .get(dependency_key)
      .and_then(|entries| entries.first())
  }

  pub fn all_dependencies(&self) -> impl Iterator<Item = &Entry<R>> {
    self.dependencies.values().flatten()
  }

  fn add_edge(&mut self, dependency_key: R::DependencyKey, new_dependency: Entry<R>) {
    self
      .dependencies
      .entry(dependency_key)
      .or_insert_with(Vec::new)
      .push(new_dependency);
  }
}

// TODO: We can't derive this due to https://github.com/rust-lang/rust/issues/26925, which
// unnecessarily requires `Rule: Default`.
impl<R: Rule> Default for RuleEdges<R> {
  fn default() -> Self {
    RuleEdges {
      dependencies: HashMap::default(),
    }
  }
}

#[cfg(test)]
mod tests {
  use super::RuleGraph;
  use std::fmt;

  #[test]
  fn create_and_validate_valid() {
    let rules = vec![("a", vec![Rule("a_from_b", vec![DependencyKey("b", None)])])]
      .into_iter()
      .collect();
    let roots = vec!["b"];
    let graph = RuleGraph::new(&rules, roots);

    graph.validate().unwrap();
  }

  #[test]
  fn create_and_validate_no_root() {
    let rules = vec![("a", vec![Rule("a_from_b", vec![DependencyKey("b", None)])])]
      .into_iter()
      .collect();
    let roots = vec![];
    let graph = RuleGraph::new(&rules, roots);

    assert!(graph
      .validate()
      .err()
      .unwrap()
      .contains("No rule was available to compute DependencyKey(\"b\", None)."));
  }

  impl super::TypeId for &'static str {
    fn display<I>(type_ids: I) -> String
    where
      I: Iterator<Item = Self>,
    {
      type_ids.collect::<Vec<_>>().join("+")
    }
  }

  // A name and vec of DependencyKeys. Abbreviated for simpler construction and matching.
  #[derive(Clone, Debug, Eq, Hash, PartialEq)]
  struct Rule(&'static str, Vec<DependencyKey>);

  impl super::Rule for Rule {
    type TypeId = &'static str;
    type DependencyKey = DependencyKey;

    fn dependency_keys(&self) -> Vec<Self::DependencyKey> {
      self.1.clone()
    }

    fn require_reachable(&self) -> bool {
      true
    }
  }

  impl fmt::Display for Rule {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
      write!(f, "{:?}", self)
    }
  }

  // A product and a param. Abbreviated for simpler construction and matching.
  #[derive(Copy, Clone, Debug, Eq, Hash, PartialEq)]
  struct DependencyKey(&'static str, Option<&'static str>);

  impl super::DependencyKey for DependencyKey {
    type TypeId = &'static str;

    fn new_root(product: Self::TypeId) -> Self {
      DependencyKey(product, None)
    }

    fn product(&self) -> Self::TypeId {
      self.0
    }

    fn provided_param(&self) -> Option<Self::TypeId> {
      self.1
    }
  }

  impl fmt::Display for DependencyKey {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
      write!(f, "{:?}", self)
    }
  }
}
