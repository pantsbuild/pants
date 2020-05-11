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

mod rules;

use std::cmp::Ordering;
use std::collections::{hash_map, BTreeSet, HashMap, HashSet};
use std::io;

pub use crate::rules::{DependencyKey, DisplayForGraph, Rule, TypeId};

// TODO: Consider switching to HashSet and dropping the Ord bound from TypeId.
type ParamTypes<T> = BTreeSet<T>;

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct UnreachableError<R: Rule> {
  rule: R,
  diagnostic: Diagnostic<R::TypeId>,
}

impl<R: Rule> UnreachableError<R> {
  fn new(rule: R) -> UnreachableError<R> {
    UnreachableError {
      rule,
      diagnostic: Diagnostic {
        params: ParamTypes::default(),
        reason: "Was not reachable, either because no rules could produce the params or because it was shadowed by another @rule.".to_string(),
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
  pub fn rule(&self) -> Option<R> {
    match self {
      &EntryWithDeps::Inner(InnerEntry { ref rule, .. }) => Some(rule.clone()),
      &EntryWithDeps::Root(_) => None,
    }
  }

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
type ChosenDependency<'a, R> = (&'a <R as Rule>::DependencyKey, &'a Entry<R>);

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct Diagnostic<T: TypeId> {
  params: ParamTypes<T>,
  reason: String,
  details: Vec<String>,
}

enum ConstructGraphResult<R: Rule> {
  // The Entry was satisfiable without waiting for any additional nodes to be satisfied. The result
  // contains copies of the input Entry for each set subset of the parameters that satisfy it.
  Fulfilled(Vec<EntryWithDeps<R>>),
  // The Entry was not satisfiable with installed rules.
  Unfulfillable,
  // The dependencies of an Entry might be satisfiable, but is currently blocked waiting for the
  // results of the given entries.
  //
  // Holds partially-fulfilled Entries which do not yet contain their full set of used parameters.
  // These entries are only consumed the case when a caller is the source of a cycle, and in that
  // case they represent everything except the caller's own parameters (which provides enough
  // information for the caller to complete).
  CycledOn {
    cyclic_deps: HashSet<EntryWithDeps<R>>,
    partial_simplified_entries: Vec<EntryWithDeps<R>>,
  },
}

// Given the task index and the root subjects, it produces a rule graph that allows dependency nodes
// to be found statically rather than dynamically.
pub struct GraphMaker<'t, R: Rule> {
  tasks: &'t HashMap<R::TypeId, Vec<R>>,
  root_param_types: ParamTypes<R::TypeId>,
}

impl<'t, R: Rule> GraphMaker<'t, R> {
  pub fn new(
    tasks: &'t HashMap<R::TypeId, Vec<R>>,
    root_param_types: Vec<R::TypeId>,
  ) -> GraphMaker<'t, R> {
    let root_param_types = root_param_types.into_iter().collect();
    GraphMaker {
      tasks,
      root_param_types,
    }
  }

  pub fn graph(&self) -> RuleGraph<R> {
    self.construct_graph(self.gen_root_entries(&self.tasks.keys().cloned().collect()))
  }

  pub fn construct_graph(&self, roots: Vec<RootEntry<R>>) -> RuleGraph<R> {
    let mut dependency_edges: RuleDependencyEdges<_> = HashMap::new();
    let mut simplified_entries = HashMap::new();
    let mut unfulfillable_rules: UnfulfillableRuleMap<_> = HashMap::new();

    for beginning_root in roots {
      self.construct_graph_helper(
        &mut dependency_edges,
        &mut simplified_entries,
        &mut unfulfillable_rules,
        EntryWithDeps::Root(beginning_root),
      );
    }

    let unreachable_rules = self.unreachable_rules(&dependency_edges);

    RuleGraph {
      root_param_types: self.root_param_types.clone(),
      rule_dependency_edges: dependency_edges,
      unfulfillable_rules,
      unreachable_rules,
    }
  }

  ///
  /// Compute input TaskRules that are unreachable from root entries.
  ///
  fn unreachable_rules(
    &self,
    full_dependency_edges: &RuleDependencyEdges<R>,
  ) -> Vec<UnreachableError<R>> {
    // Walk the graph, starting from root entries.
    let mut entry_stack: Vec<_> = full_dependency_edges
      .keys()
      .filter(|entry| match entry {
        EntryWithDeps::Root(_) => true,
        _ => false,
      })
      .collect();
    let mut visited = HashSet::new();
    while let Some(entry) = entry_stack.pop() {
      if visited.contains(&entry) {
        continue;
      }
      visited.insert(entry);

      if let Some(edges) = full_dependency_edges.get(entry) {
        entry_stack.extend(edges.all_dependencies().filter_map(|e| match e {
          Entry::WithDeps(ref e) => Some(e),
          _ => None,
        }));
      }
    }

    let reachable_rules: HashSet<_> = visited
      .into_iter()
      .filter_map(|entry| match entry {
        EntryWithDeps::Inner(InnerEntry { ref rule, .. }) if rule.require_reachable() => {
          Some(rule.clone())
        }
        _ => None,
      })
      .collect();

    self
      .tasks
      .values()
      .flat_map(|r| r.iter())
      .filter(|r| r.require_reachable() && !reachable_rules.contains(r))
      .map(|r| UnreachableError::new(r.clone()))
      .collect()
  }

  ///
  /// Computes whether the given candidate Entry is satisfiable, and if it is, returns a copy
  /// of the Entry for each set of input parameters that will satisfy it. Once computed, the
  /// simplified versions are memoized in all_simplified_entries.
  ///
  /// When a rule can be fulfilled it will end up stored in both the rule_dependency_edges and
  /// all_simplified_entries. If it can't be fulfilled, it is added to `unfulfillable_rules`.
  ///
  fn construct_graph_helper(
    &self,
    rule_dependency_edges: &mut RuleDependencyEdges<R>,
    all_simplified_entries: &mut HashMap<EntryWithDeps<R>, Vec<EntryWithDeps<R>>>,
    unfulfillable_rules: &mut UnfulfillableRuleMap<R>,
    entry: EntryWithDeps<R>,
  ) -> ConstructGraphResult<R> {
    if let Some(simplified) = all_simplified_entries.get(&entry) {
      // A simplified equivalent entry has already been computed, return it.
      return ConstructGraphResult::Fulfilled(simplified.clone());
    } else if unfulfillable_rules.get(&entry).is_some() {
      // The rule is unfulfillable.
      return ConstructGraphResult::Unfulfillable;
    }

    // Otherwise, store a placeholder in the rule_dependency_edges map and then visit its
    // children.
    //
    // This prevents infinite recursion by shortcircuiting when an entry recursively depends on
    // itself. It's totally fine for rules to be recursive: the recursive path just never
    // contributes to whether the rule is satisfiable.
    match rule_dependency_edges.entry(entry.clone()) {
      hash_map::Entry::Vacant(re) => {
        // When a rule has not been visited before, we start the visit by storing a placeholder in
        // the rule dependencies map in order to detect rule cycles.
        re.insert(RuleEdges::default());
      }
      hash_map::Entry::Occupied(_) => {
        // We're currently recursively under this rule, but its simplified equivalence has not yet
        // been computed (or we would have returned it above). The cyclic parent(s) will complete
        // before recursing to compute this node again.
        let mut cyclic_deps = HashSet::new();
        let simplified = entry.simplified(BTreeSet::new());
        cyclic_deps.insert(entry);
        return ConstructGraphResult::CycledOn {
          cyclic_deps,
          partial_simplified_entries: vec![simplified],
        };
      }
    };

    // For each dependency of the rule, recurse for each potential match and collect RuleEdges and
    // used parameters.
    //
    // This is a `loop` because if we discover that this entry needs to complete in order to break
    // a cycle on itself, it will re-compute dependencies after having partially-completed.
    loop {
      if let Ok(res) = self.construct_dependencies(
        rule_dependency_edges,
        all_simplified_entries,
        unfulfillable_rules,
        entry.clone(),
      ) {
        break res;
      }
    }
  }

  ///
  /// For each dependency of the rule, recurse for each potential match and collect RuleEdges and
  /// used parameters.
  ///
  /// This is called in a `loop` until it succeeds, because if we discover that this entry needs
  /// to complete in order to break a cycle on itself, it will re-compute dependencies after having
  /// partially-completed.
  ///
  fn construct_dependencies(
    &self,
    rule_dependency_edges: &mut RuleDependencyEdges<R>,
    all_simplified_entries: &mut HashMap<EntryWithDeps<R>, Vec<EntryWithDeps<R>>>,
    unfulfillable_rules: &mut UnfulfillableRuleMap<R>,
    entry: EntryWithDeps<R>,
  ) -> Result<ConstructGraphResult<R>, ()> {
    let mut fulfillable_candidates_by_key = HashMap::new();
    let mut cycled_on = HashSet::new();
    let mut unfulfillable_diagnostics = Vec::new();

    let dependency_keys = entry.dependency_keys();

    for dependency_key in dependency_keys {
      let product = dependency_key.product();
      let provided_param = dependency_key.provided_param();
      let params = if let Some(provided_param) = provided_param {
        // The dependency key provides a parameter: include it in the Params that are already in
        // the context.
        let mut params = entry.params().clone();
        params.insert(provided_param);
        params
      } else {
        entry.params().clone()
      };

      // Collect fulfillable candidates, used parameters, and cyclic deps.
      let mut cycled = false;
      let fulfillable_candidates = fulfillable_candidates_by_key
        .entry(dependency_key)
        .or_insert_with(Vec::new);
      for candidate in self.rhs(&params, product) {
        match candidate {
          Entry::WithDeps(c) => match self.construct_graph_helper(
            rule_dependency_edges,
            all_simplified_entries,
            unfulfillable_rules,
            c,
          ) {
            ConstructGraphResult::Unfulfillable => {}
            ConstructGraphResult::Fulfilled(simplified_entries) => {
              fulfillable_candidates.push(
                simplified_entries
                  .into_iter()
                  .filter(|e| {
                    // Only entries that actually consume a provided (Get) parameter are eligible
                    // for consideration.
                    if let Some(pp) = provided_param {
                      e.params().contains(&pp)
                    } else {
                      true
                    }
                  })
                  .map(Entry::WithDeps)
                  .collect::<Vec<_>>(),
              );
            }
            ConstructGraphResult::CycledOn {
              cyclic_deps,
              partial_simplified_entries,
            } => {
              cycled = true;
              cycled_on.extend(cyclic_deps);
              fulfillable_candidates.push(
                partial_simplified_entries
                  .into_iter()
                  .map(Entry::WithDeps)
                  .collect::<Vec<_>>(),
              );
            }
          },
          p @ Entry::Param(_) => {
            fulfillable_candidates.push(vec![p]);
          }
        };
      }

      if cycled {
        // If any candidate triggered a cycle on a rule that has not yet completed, then we are not
        // yet fulfillable, and should finish gathering any other cyclic rule dependencies.
        continue;
      }

      if fulfillable_candidates.is_empty() {
        // If no candidates were fulfillable, this rule is not fulfillable.
        unfulfillable_diagnostics.push(Diagnostic {
          params: params.clone(),
          reason: if params.is_empty() {
            format!(
              "No rule was available to compute {}. Maybe declare RootRule({})?",
              dependency_key, product,
            )
          } else {
            format!(
              "No rule was available to compute {} with parameter type{} {}",
              dependency_key,
              if params.len() > 1 { "s" } else { "" },
              params_str(&params),
            )
          },
          details: vec![],
        });
      }
    }

    // If any dependencies were completely unfulfillable, then whether or not there were cyclic
    // dependencies isn't relevant.
    if !unfulfillable_diagnostics.is_empty() {
      // Was not fulfillable. Remove the placeholder: the unfulfillable entries we stored will
      // prevent us from attempting to expand this node again.
      unfulfillable_rules
        .entry(entry.clone())
        .or_insert_with(Vec::new)
        .extend(unfulfillable_diagnostics);
      rule_dependency_edges.remove(&entry);
      return Ok(ConstructGraphResult::Unfulfillable);
    }

    // No dependencies were completely unfulfillable (although some may have been cyclic).
    let flattened_fulfillable_candidates_by_key = fulfillable_candidates_by_key
      .into_iter()
      .map(|(k, candidate_group)| (k, candidate_group.into_iter().flatten().collect()))
      .collect::<Vec<_>>();

    // Generate one Entry per legal combination of parameters.
    let simplified_entries =
      match Self::monomorphize(&entry, &flattened_fulfillable_candidates_by_key) {
        Ok(se) => se,
        Err(ambiguous_diagnostics) => {
          // At least one combination of the dependencies was ambiguous.
          unfulfillable_rules
            .entry(entry.clone())
            .or_insert_with(Vec::new)
            .extend(ambiguous_diagnostics);
          rule_dependency_edges.remove(&entry);
          return Ok(ConstructGraphResult::Unfulfillable);
        }
      };
    let simplified_entries_only: Vec<_> = simplified_entries.keys().cloned().collect();

    if cycled_on.is_empty() {
      // All dependencies were fulfillable and none were blocked on cycles. Remove the
      // placeholder and store the simplified entries.
      rule_dependency_edges.remove(&entry);
      rule_dependency_edges.extend(simplified_entries);

      all_simplified_entries.insert(entry, simplified_entries_only.clone());
      Ok(ConstructGraphResult::Fulfilled(simplified_entries_only))
    } else {
      // The set of cycled dependencies can only contain call stack "parents" of the dependency: we
      // remove this entry from the set (if we're in it), until the top-most cyclic parent
      // (represented by an empty set) is the one that re-starts recursion.
      cycled_on.remove(&entry);
      if cycled_on.is_empty() {
        // If we were the only member of the set of cyclic dependencies, then we are the top-most
        // cyclic parent in the call stack, and we should complete. This represents the case where
        // a rule recursively depends on itself, and thus "cannot complete without completing".
        //
        // Store our simplified equivalence and then re-execute our dependency discovery. In this
        // second attempt our cyclic dependencies will use the simplified representation(s) to succeed.
        all_simplified_entries.insert(entry, simplified_entries_only);
        Err(())
      } else {
        // This rule may be fulfillable, but we can't compute its complete set of dependencies until
        // parent rule entries complete. Remove our placeholder edges before returning.
        rule_dependency_edges.remove(&entry);
        Ok(ConstructGraphResult::CycledOn {
          cyclic_deps: cycled_on,
          partial_simplified_entries: simplified_entries_only,
        })
      }
    }
  }

  ///
  /// Given an Entry and a mapping of all legal sources of each of its dependencies, generates a
  /// simplified Entry for each legal combination of parameters.
  ///
  /// Computes the union of all parameters used by the dependencies, and then uses the powerset of
  /// used parameters to filter the possible combinations of dependencies. If multiple choices of
  /// dependencies are possible for any set of parameters, then the graph is ambiguous.
  ///
  fn monomorphize(
    entry: &EntryWithDeps<R>,
    deps: &[(R::DependencyKey, Vec<Entry<R>>)],
  ) -> Result<RuleDependencyEdges<R>, Vec<Diagnostic<R::TypeId>>> {
    // Collect the powerset of the union of used parameters, ordered by set size.
    let params_powerset: Vec<Vec<R::TypeId>> = {
      let mut all_used_params = BTreeSet::new();
      for (key, inputs) in deps {
        let provided_param = key.provided_param();
        for input in inputs {
          all_used_params.extend(
            input
              .params()
              .into_iter()
              .filter(|p| Some(*p) != provided_param),
          );
        }
      }
      // Compute the powerset ordered by ascending set size.
      let all_used_params = all_used_params.into_iter().collect::<Vec<_>>();
      let mut param_sets = Self::powerset(&all_used_params).collect::<Vec<_>>();
      param_sets.sort_by(|l, r| l.len().cmp(&r.len()));
      param_sets
    };

    // Then, for the powerset of used parameters, determine which dependency combinations are
    // satisfiable.
    let mut combinations: HashMap<EntryWithDeps<_>, _> = HashMap::new();
    let mut diagnostics = Vec::new();
    for available_params in params_powerset {
      let available_params = available_params.into_iter().collect();
      // If a subset of these parameters is already satisfied, skip. This has the effect of
      // selecting the smallest sets of parameters that will satisfy a rule.
      // NB: This scan over satisfied sets is linear, but should have a small N.
      if combinations
        .keys()
        .any(|satisfied_entry| satisfied_entry.params().is_subset(&available_params))
      {
        continue;
      }

      match Self::choose_dependencies(&available_params, deps) {
        Ok(Some(inputs)) => {
          let mut rule_edges = RuleEdges::default();
          for (key, input) in inputs {
            rule_edges.add_edge(key.clone(), input.clone());
          }
          combinations.insert(entry.simplified(available_params), rule_edges);
        }
        Ok(None) => {}
        Err(diagnostic) => diagnostics.push(diagnostic),
      }
    }

    // If none of the combinations was satisfiable, return the generated diagnostics.
    if combinations.is_empty() {
      Err(diagnostics)
    } else {
      Ok(combinations)
    }
  }

  ///
  /// Given a set of available Params, choose one combination of satisfiable Entry dependencies if
  /// it exists (it may not, because we're searching for sets of legal parameters in the powerset
  /// of all used params).
  ///
  /// If an ambiguity is detected in rule dependencies (ie, if multiple rules are satisfiable for
  /// a single dependency key), fail with a Diagnostic.
  ///
  fn choose_dependencies<'a>(
    available_params: &ParamTypes<R::TypeId>,
    deps: &'a [(R::DependencyKey, Vec<Entry<R>>)],
  ) -> Result<Option<Vec<ChosenDependency<'a, R>>>, Diagnostic<R::TypeId>> {
    let mut combination = Vec::new();
    for (key, input_entries) in deps {
      let provided_param = key.provided_param();
      let satisfiable_entries = input_entries
        .iter()
        .filter(|input_entry| {
          input_entry
            .params()
            .iter()
            .all(|p| available_params.contains(p) || Some(*p) == provided_param)
        })
        .collect::<Vec<_>>();

      let chosen_entries = Self::choose_dependency(satisfiable_entries);
      match chosen_entries.len() {
        0 => {
          return Ok(None);
        }
        1 => {
          combination.push((key, chosen_entries[0]));
        }
        _ => {
          let params_clause = match available_params.len() {
            0 => "",
            1 => " with parameter type ",
            _ => " with parameter types ",
          };

          return Err(Diagnostic {
            params: available_params.clone(),
            reason: format!(
              "Ambiguous rules to compute {}{}{}",
              key,
              params_clause,
              params_str(&available_params),
            ),
            details: chosen_entries.into_iter().map(entry_str).collect(),
          });
        }
      }
    }

    Ok(Some(combination))
  }

  fn choose_dependency<'a>(satisfiable_entries: Vec<&'a Entry<R>>) -> Vec<&'a Entry<R>> {
    if satisfiable_entries.is_empty() {
      // No source of this dependency was satisfiable with these Params.
      return vec![];
    } else if satisfiable_entries.len() == 1 {
      return satisfiable_entries;
    }

    // We prefer the non-ambiguous entry with the smallest set of Params, as that minimizes Node
    // identities in the graph and biases toward receiving values from dependencies (which do not
    // affect our identity) rather than dependents.
    let mut minimum_param_set_size = ::std::usize::MAX;
    let mut rules = Vec::new();
    for satisfiable_entry in satisfiable_entries {
      let param_set_size = match satisfiable_entry {
        Entry::WithDeps(ref wd) => wd.params().len(),
        Entry::Param(_) => 1,
      };
      match param_set_size.cmp(&minimum_param_set_size) {
        Ordering::Less => {
          rules.clear();
          rules.push(satisfiable_entry);
          minimum_param_set_size = param_set_size;
        }
        Ordering::Equal => {
          rules.push(satisfiable_entry);
        }
        Ordering::Greater => {}
      }
    }

    rules
  }

  fn powerset<'a, T: Clone>(slice: &'a [T]) -> impl Iterator<Item = Vec<T>> + 'a {
    (0..(1 << slice.len())).map(move |mask| {
      let mut ss = Vec::new();
      let mut bitset = mask;
      while bitset > 0 {
        // isolate the rightmost bit to select one item
        let rightmost: u64 = bitset & !(bitset - 1);
        // turn the isolated bit into an array index
        let idx = rightmost.trailing_zeros();
        let item = &slice[idx as usize];
        ss.push(item.clone());
        // zero the trailing bit
        bitset &= bitset - 1;
      }
      ss
    })
  }

  fn gen_root_entries(&self, product_types: &HashSet<R::TypeId>) -> Vec<RootEntry<R>> {
    product_types
      .iter()
      .filter_map(|product_type| self.gen_root_entry(&self.root_param_types, *product_type))
      .collect()
  }

  fn gen_root_entry(
    &self,
    param_types: &ParamTypes<R::TypeId>,
    product_type: R::TypeId,
  ) -> Option<RootEntry<R>> {
    let candidates = self.rhs(param_types, product_type);
    if candidates.is_empty() {
      None
    } else {
      Some(RootEntry {
        params: param_types.clone(),
        dependency_key: R::DependencyKey::new_root(product_type),
      })
    }
  }

  ///
  /// Select Entries that can provide the given product type with the given parameters.
  ///
  fn rhs(&self, params: &ParamTypes<R::TypeId>, product_type: R::TypeId) -> Vec<Entry<R>> {
    let mut entries = Vec::new();
    // If the params can provide the type directly, add that.
    if let Some(type_id) = params.get(&product_type) {
      entries.push(Entry::Param(*type_id));
    }
    // If there are any rules which can produce the desired type, add them.
    if let Some(matching_rules) = self.tasks.get(&product_type) {
      entries.extend(matching_rules.iter().map(|rule| {
        Entry::WithDeps(EntryWithDeps::Inner(InnerEntry {
          params: params.clone(),
          rule: rule.clone(),
        }))
      }));
    }
    entries
  }
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

pub fn params_str<T: TypeId>(params: &ParamTypes<T>) -> String {
  T::display(params.iter().cloned())
}

pub fn entry_str<R: Rule>(entry: &Entry<R>) -> String {
  entry_node_str_with_attrs(entry).entry_str
}

#[derive(Debug, Clone, PartialOrd, Ord, PartialEq, Eq)]
pub struct GraphVizEntryWithAttrs {
  entry_str: String,
  attrs_str: Option<String>,
}

pub enum Palette {
  Olive,
  Gray,
  Orange,
  Blue,
}

impl Palette {
  // https://c.eev.ee/kouyou/ is wonderful for selecting lovely color juxtapositions across multiple
  // different color axes.
  fn color_string(&self) -> String {
    // These color values are all in HSV. See https://www.graphviz.org/doc/info/colors.html for
    // other methods of specifying
    // colors. https://renenyffenegger.ch/notes/tools/Graphviz/attributes/_color/index may also be
    // useful.
    match self {
      Self::Olive => "0.2214,0.7179,0.8528".to_string(),
      Self::Gray => "0.576,0,0.6242".to_string(),
      Self::Orange => "0.08,0.5,0.976".to_string(),
      Self::Blue => "0.5,1,0.9".to_string(),
    }
  }
}

impl DisplayForGraph for Palette {
  fn fmt_for_graph(&self) -> String {
    format!("[color=\"{}\",style=filled]", self.color_string())
  }
}

///
/// Apply coloration to several nodes.
pub fn entry_node_str_with_attrs<R: Rule>(entry: &Entry<R>) -> GraphVizEntryWithAttrs {
  let (entry_str, attrs_str) = match entry {
    &Entry::WithDeps(ref e) => (
      entry_with_deps_str(e),
      // Color "singleton" entries (with no params)!
      if e.params().is_empty() {
        Some(Palette::Olive.fmt_for_graph())
      } else if let Some(color) = e.rule().and_then(|r| r.color()) {
        // Color "intrinsic" entries (provided by the rust codebase)!
        Some(color.fmt_for_graph())
      } else {
        None
      },
    ),
    &Entry::Param(type_id) => (
      format!("Param({})", type_id),
      // Color "Param"s!
      Some(Palette::Orange.fmt_for_graph()),
    ),
  };
  GraphVizEntryWithAttrs {
    entry_str,
    attrs_str,
  }
}

fn entry_with_deps_str<R: Rule>(entry: &EntryWithDeps<R>) -> String {
  match entry {
    &EntryWithDeps::Inner(InnerEntry {
      ref rule,
      ref params,
    }) => format!("{}\nfor {}", rule.fmt_for_graph(), params_str(params)),
    &EntryWithDeps::Root(ref root) => format!(
      // TODO: Consider dropping this (final) public use of the keyword "Select", while ensuring
      // that error messages remain sufficiently grokkable.
      "Select({})\nfor {}",
      root.dependency_key,
      params_str(&root.params)
    ),
  }
}

impl<R: Rule> RuleGraph<R> {
  pub fn new(tasks: &HashMap<R::TypeId, Vec<R>>, root_param_types: Vec<R::TypeId>) -> RuleGraph<R> {
    GraphMaker::new(tasks, root_param_types).graph()
  }

  pub fn find_root_edges<I: IntoIterator<Item = R::TypeId>>(
    &self,
    param_inputs: I,
    product: R::TypeId,
  ) -> Result<RuleEdges<R>, String> {
    let (_, edges) = self.find_root(param_inputs, product)?;
    Ok(edges)
  }

  ///
  /// Create a copy of this RuleGraph filtered to only the subgraph below the root matched by the
  /// given product and params.
  ///
  pub fn subgraph<I: IntoIterator<Item = R::TypeId>>(
    &self,
    param_inputs: I,
    product: R::TypeId,
  ) -> Result<RuleGraph<R>, String> {
    let (root, _) = self.find_root(param_inputs, product)?;

    // Walk the graph, starting from root entries.
    let mut entry_stack: Vec<_> = vec![root];
    let mut reachable = HashMap::new();
    while let Some(entry) = entry_stack.pop() {
      if reachable.contains_key(&entry) {
        continue;
      }

      if let Some(edges) = self.rule_dependency_edges.get(&entry) {
        reachable.insert(entry, edges.clone());

        entry_stack.extend(edges.all_dependencies().filter_map(|e| match e {
          Entry::WithDeps(e) => Some(e.clone()),
          _ => None,
        }));
      } else {
        return Err(format!("Unknown entry in RuleGraph: {:?}", entry));
      }
    }

    Ok(RuleGraph {
      root_param_types: self.root_param_types.clone(),
      rule_dependency_edges: reachable,
      unfulfillable_rules: UnfulfillableRuleMap::default(),
      unreachable_rules: Vec::default(),
    })
  }

  ///
  /// Find the entrypoint in this RuleGraph for the given product and params.
  ///
  pub fn find_root<I: IntoIterator<Item = R::TypeId>>(
    &self,
    param_inputs: I,
    product: R::TypeId,
  ) -> Result<(EntryWithDeps<R>, RuleEdges<R>), String> {
    let params: ParamTypes<_> = param_inputs.into_iter().collect();
    let dependency_key = R::DependencyKey::new_root(product);

    // Attempt to find an exact match.
    let maybe_root = EntryWithDeps::Root(RootEntry {
      params: params.clone(),
      dependency_key,
    });
    if let Some(edges) = self.rule_dependency_edges.get(&maybe_root) {
      return Ok((maybe_root, edges.clone()));
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
      1 => {
        let (root_entry, edges) = subset_matches[0];
        Ok((root_entry.clone(), edges.clone()))
      }
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
          format!(
            "return the type {}. Is the @rule that you're expecting to run registered?",
            product,
          )
        } else {
          suggestions.sort();
          format!(
            "can compute {} given input Params({}), but there were @rules that could compute it using:\n  {}",
            product,
            params_str(&params),
            suggestions.join("\n  ")
          )
        };
        Err(format!("No installed @rules {}", suggestions_str,))
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
              d.reason
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

    Err(format!(
      "Rules with errors: {}\n\n  {}",
      msgs.len(),
      msgs.join("\n\n  ")
    ))
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
          let mut dep_entries = deps
            .all_dependencies()
            .map(|d| entry_node_str_with_attrs(d))
            .collect::<Vec<_>>();
          dep_entries.sort();
          let deps_with_attrs = dep_entries
            .iter()
            .cloned()
            .filter(|d| d.attrs_str.is_some())
            .map(|d| format!("\"{}\" {}", d.entry_str, d.attrs_str.unwrap()))
            .collect::<Vec<String>>()
            .join("\n");
          Some(format!(
            "    \"{}\" {}\n{}    \"{}\" -> {{{}}}",
            root_str,
            Palette::Blue.fmt_for_graph(),
            deps_with_attrs,
            root_str,
            dep_entries
              .iter()
              .cloned()
              .map(|d| format!("\"{}\"", d.entry_str))
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
        &EntryWithDeps::Inner(_) => {
          let mut dep_entries = deps
            .all_dependencies()
            .map(|d| entry_node_str_with_attrs(d))
            .collect::<Vec<_>>();
          dep_entries.sort();
          let deps_with_attrs = dep_entries
            .iter()
            .cloned()
            .filter(|d| d.attrs_str.is_some())
            .map(|d| format!("\"{}\" {}", d.entry_str, d.attrs_str.unwrap()))
            .collect::<Vec<String>>()
            .join("\n");
          Some(format!(
            "{}    \"{}\" -> {{{}}}",
            deps_with_attrs,
            entry_with_deps_str(k),
            dep_entries
              .iter()
              .cloned()
              .map(|d| format!("\"{}\"", d.entry_str))
              .collect::<Vec<String>>()
              .join(" "),
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
mod tests;
