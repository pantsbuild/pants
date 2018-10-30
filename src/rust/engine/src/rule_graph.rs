// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{hash_map, BTreeSet, HashMap, HashSet};
use std::io;

use itertools::Itertools;

use core::{Function, Key, TypeConstraint, TypeId, Value, ANY_TYPE};
use externs;
use selectors::{Get, Select};
use tasks::{Intrinsic, Task, Tasks};

type ParamTypes = BTreeSet<TypeId>;

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct UnreachableError {
  task_rule: Task,
  diagnostic: Diagnostic,
}

impl UnreachableError {
  fn new(task_rule: Task) -> UnreachableError {
    UnreachableError {
      task_rule: task_rule,
      diagnostic: Diagnostic {
        params: ParamTypes::default(),
        reason: "Unreachable".to_string(),
        details: vec![],
      },
    }
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum EntryWithDeps {
  Root(RootEntry),
  Inner(InnerEntry),
}

impl EntryWithDeps {
  fn params(&self) -> &ParamTypes {
    match self {
      &EntryWithDeps::Inner(ref ie) => &ie.params,
      &EntryWithDeps::Root(ref re) => &re.params,
    }
  }

  fn task_rule(&self) -> Option<&Task> {
    match self {
      &EntryWithDeps::Inner(InnerEntry {
        rule: Rule::Task(ref task_rule),
        ..
      }) => Some(task_rule),
      _ => None,
    }
  }

  ///
  /// Returns the set of SelectKeys representing the dependencies of this EntryWithDeps.
  ///
  fn dependency_keys(&self) -> Vec<SelectKey> {
    match self {
      &EntryWithDeps::Inner(InnerEntry {
        rule: Rule::Task(Task {
          ref clause,
          ref gets,
          ..
        }),
        ..
      })
      | &EntryWithDeps::Root(RootEntry {
        ref clause,
        ref gets,
        ..
      }) => clause
        .iter()
        .map(|s| SelectKey::JustSelect(s.clone()))
        .chain(gets.iter().map(|g| SelectKey::JustGet(*g)))
        .collect(),
      &EntryWithDeps::Inner(InnerEntry {
        rule: Rule::Intrinsic(Intrinsic { ref input, .. }),
        ..
      }) => vec![SelectKey::JustSelect(Select::new(*input))],
    }
  }

  ///
  /// Given a set of used parameters (which must be a subset of the parameters available here),
  /// return a clone of this entry with its parameter set reduced to the used parameters.
  ///
  fn simplified(&self, used_params: ParamTypes) -> EntryWithDeps {
    let mut simplified = self.clone();
    {
      let simplified_params = match &mut simplified {
        &mut EntryWithDeps::Inner(ref mut ie) => &mut ie.params,
        &mut EntryWithDeps::Root(ref mut re) => &mut re.params,
      };

      let unavailable_params: ParamTypes =
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
pub enum Entry {
  Param(TypeId),
  WithDeps(EntryWithDeps),
  Singleton(Key, TypeConstraint),
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct RootEntry {
  params: ParamTypes,
  // TODO: A RootEntry can only have one declared `Select`, and no declared `Get`s, but these
  // are shaped as Vecs to temporarily minimize the re-shuffling in `_construct_graph`. Remove in
  // a future commit.
  clause: Vec<Select>,
  gets: Vec<Get>,
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum Rule {
  // Intrinsic rules are implemented in rust.
  Intrinsic(Intrinsic),
  // Task rules are implemented in python.
  Task(Task),
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct InnerEntry {
  params: ParamTypes,
  rule: Rule,
}

impl InnerEntry {
  pub fn rule(&self) -> &Rule {
    &self.rule
  }
}

///
/// A key for the Selects used from a rule. Rules are only picked up by Select selectors. These keys
/// uniquely identify the selects used by a particular entry in the rule graph so that they can be
/// mapped to the dependencies they correspond to.
///
#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum SelectKey {
  // A Get for a particular product/subject pair.
  JustGet(Get),
  // A bare select with no projection.
  JustSelect(Select),
}

type RuleDependencyEdges = HashMap<EntryWithDeps, RuleEdges>;
type UnfulfillableRuleMap = HashMap<EntryWithDeps, Vec<Diagnostic>>;

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct Diagnostic {
  params: ParamTypes,
  reason: String,
  details: Vec<String>,
}

impl Diagnostic {
  fn ambiguous(available_params: &ParamTypes, key: &SelectKey, entries: Vec<&Entry>) -> Diagnostic {
    let params_clause = match available_params.len() {
      0 => "",
      1 => " with parameter type ",
      _ => " with parameter types ",
    };
    Diagnostic {
      params: available_params.clone(),
      reason: format!(
        "ambiguous rules for {}{}{}",
        select_key_str(&key),
        params_clause,
        params_str(&available_params),
      ),
      details: entries.into_iter().map(entry_str).collect(),
    }
  }
}

enum ConstructGraphResult {
  // The Entry was satisfiable without waiting for any additional nodes to be satisfied. The result
  // contains copies of the input Entry for each set subset of the parameters that satisfy it.
  Fulfilled(Vec<EntryWithDeps>),
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
    cyclic_deps: HashSet<EntryWithDeps>,
    partial_simplified_entries: Vec<EntryWithDeps>,
  },
}

// Given the task index and the root subjects, it produces a rule graph that allows dependency nodes
// to be found statically rather than dynamically.
pub struct GraphMaker<'t> {
  tasks: &'t Tasks,
  root_param_types: ParamTypes,
}

impl<'t> GraphMaker<'t> {
  pub fn new(tasks: &'t Tasks, root_param_types: Vec<TypeId>) -> GraphMaker<'t> {
    let root_param_types = root_param_types.into_iter().collect();
    GraphMaker {
      tasks,
      root_param_types,
    }
  }

  pub fn sub_graph(&self, param_type: TypeId, product_type: &TypeConstraint) -> RuleGraph {
    // TODO: Update to support rendering a subgraph given a set of ParamTypes.
    let param_types = vec![param_type].into_iter().collect();

    if let Some(beginning_root) = self.gen_root_entry(&param_types, product_type) {
      self.construct_graph(vec![beginning_root])
    } else {
      RuleGraph::default()
    }
  }

  pub fn full_graph(&self) -> RuleGraph {
    self.construct_graph(self.gen_root_entries(&self.tasks.all_product_types()))
  }

  pub fn construct_graph(&self, roots: Vec<RootEntry>) -> RuleGraph {
    let mut dependency_edges: RuleDependencyEdges = HashMap::new();
    let mut simplified_entries = HashMap::new();
    let mut unfulfillable_rules: UnfulfillableRuleMap = HashMap::new();

    for beginning_root in roots {
      self.construct_graph_helper(
        &mut dependency_edges,
        &mut simplified_entries,
        &mut unfulfillable_rules,
        EntryWithDeps::Root(beginning_root),
      );
    }

    let unreachable_rules = self.unreachable_rules(&dependency_edges, &unfulfillable_rules);

    RuleGraph {
      root_param_types: self.root_param_types.clone(),
      rule_dependency_edges: dependency_edges,
      unfulfillable_rules: unfulfillable_rules,
      unreachable_rules: unreachable_rules,
    }
  }

  fn unreachable_rules(
    &self,
    full_dependency_edges: &RuleDependencyEdges,
    full_unfulfillable_rules: &UnfulfillableRuleMap,
  ) -> Vec<UnreachableError> {
    let rules_in_graph: HashSet<_> = full_dependency_edges
      .keys()
      .filter_map(|entry| match entry {
        &EntryWithDeps::Inner(InnerEntry {
          rule: Rule::Task(ref task_rule),
          ..
        }) => Some(task_rule.clone()),
        _ => None,
      }).collect();
    let unfulfillable_discovered_during_construction: HashSet<_> = full_unfulfillable_rules
      .keys()
      .filter_map(|f| f.task_rule())
      .cloned()
      .collect();
    self
      .tasks
      .all_tasks()
      .iter()
      .filter(|r| !rules_in_graph.contains(r))
      .filter(|r| !unfulfillable_discovered_during_construction.contains(r))
      .map(|&r| UnreachableError::new(r.clone()))
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
    rule_dependency_edges: &mut RuleDependencyEdges,
    all_simplified_entries: &mut HashMap<EntryWithDeps, Vec<EntryWithDeps>>,
    unfulfillable_rules: &mut UnfulfillableRuleMap,
    entry: EntryWithDeps,
  ) -> ConstructGraphResult {
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
    rule_dependency_edges: &mut RuleDependencyEdges,
    all_simplified_entries: &mut HashMap<EntryWithDeps, Vec<EntryWithDeps>>,
    unfulfillable_rules: &mut UnfulfillableRuleMap,
    entry: EntryWithDeps,
  ) -> Result<ConstructGraphResult, ()> {
    let mut fulfillable_candidates_by_key = HashMap::new();
    let mut cycled_on = HashSet::new();
    let mut unfulfillable_diagnostics = Vec::new();

    let dependency_keys = entry.dependency_keys();

    for select_key in dependency_keys {
      let (params, product) = match &select_key {
        &SelectKey::JustSelect(ref s) => (entry.params().clone(), s.product),
        &SelectKey::JustGet(ref g) => {
          // Unlike Selects, Gets introduce new parameter values into a subgraph.
          let get_params = {
            let mut p = entry.params().clone();
            p.insert(g.subject);
            p
          };
          (get_params, g.product)
        }
      };

      // Collect fulfillable candidates, used parameters, and cyclic deps.
      let mut cycled = false;
      let mut fulfillable_candidates = fulfillable_candidates_by_key
        .entry(select_key.clone())
        .or_insert_with(Vec::new);
      for candidate in rhs(&self.tasks, &params, &product) {
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
          s @ Entry::Singleton { .. } => {
            fulfillable_candidates.push(vec![s]);
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
          reason: if params_str(&params) == "()" {
            format!(
              "No root rule found to compute {}. Maybe declare it as a RootRule({}).",
              type_constraint_str(product),
              type_constraint_str(product),
            )
          } else {
            format!(
              "no rule was available to compute {} with parameter type{} {}",
              type_constraint_str(product),
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
    //
    // If this is an Aggregration, flatten the candidates by duplicating the SelectKey to treat
    // each concrete rule as a group of candidates. Otherwise, flatten each group of candidates.
    let flattened_fulfillable_candidates_by_key = fulfillable_candidates_by_key
      .into_iter()
      .map(|(k, candidate_group)| (k, Itertools::flatten(candidate_group.into_iter()).collect()))
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
    entry: &EntryWithDeps,
    deps: &[(SelectKey, Vec<Entry>)],
  ) -> Result<HashMap<EntryWithDeps, RuleEdges>, Vec<Diagnostic>> {
    // Collect the powerset of the union of used parameters, ordered by set size.
    let params_powerset: Vec<Vec<TypeId>> = {
      let mut all_used_params = BTreeSet::new();
      for (key, inputs) in deps {
        for input in inputs {
          all_used_params.extend(Self::used_params(key, input));
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
    let mut combinations: HashMap<EntryWithDeps, _> = HashMap::new();
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
    available_params: &ParamTypes,
    deps: &'a [(SelectKey, Vec<Entry>)],
  ) -> Result<Option<Vec<(&'a SelectKey, &'a Entry)>>, Diagnostic> {
    let mut combination = Vec::new();
    for (key, input_entries) in deps {
      let satisfiable_entries = input_entries
        .iter()
        .filter(|input_entry| {
          Self::used_params(key, input_entry)
            .iter()
            .all(|p| available_params.contains(p))
        }).collect::<Vec<_>>();

      let chosen_entries = Self::choose_dependency(satisfiable_entries);
      match chosen_entries.len() {
        0 => {
          return Ok(None);
        }
        1 => {
          combination.push((key, chosen_entries[0]));
        }
        _ => {
          return Err(Diagnostic::ambiguous(available_params, key, chosen_entries));
        }
      }
    }

    Ok(Some(combination))
  }

  fn choose_dependency<'a>(satisfiable_entries: Vec<&'a Entry>) -> Vec<&'a Entry> {
    if satisfiable_entries.is_empty() {
      // No source of this dependency was satisfiable with these Params.
      return vec![];
    }

    // Prefer a Singleton, then a Param, then the non-ambiguous rule with the smallest set of
    // input Params.
    // TODO: We should likely prefer Rules to Params.
    if satisfiable_entries.len() == 1 {
      satisfiable_entries
    } else if let Some(singleton) = satisfiable_entries.iter().find(|e| match e {
      &Entry::Singleton { .. } => true,
      _ => false,
    }) {
      vec![*singleton]
    } else if let Some(param) = satisfiable_entries.iter().find(|e| match e {
      &Entry::Param(_) => true,
      _ => false,
    }) {
      vec![*param]
    } else {
      // Group by the simplified version of each rule: if exactly one, we're finished. We prefer
      // the non-ambiguous rule with the smallest set of Params, as that minimizes Node identities
      // in the graph and biases toward receiving values from dependencies (which do not affect our
      // identity) rather than dependents.
      let mut rules_by_kind: HashMap<EntryWithDeps, (usize, &Entry)> = HashMap::new();
      for satisfiable_entry in &satisfiable_entries {
        if let &Entry::WithDeps(ref wd) = satisfiable_entry {
          rules_by_kind
            .entry(wd.simplified(BTreeSet::new()))
            .and_modify(|e| {
              if e.0 > wd.params().len() {
                *e = (wd.params().len(), satisfiable_entry);
              }
            }).or_insert((wd.params().len(), satisfiable_entry));
        }
      }

      rules_by_kind
        .into_iter()
        .map(|(_, (_, rule))| rule)
        .collect::<Vec<_>>()
    }
  }

  ///
  /// Computes the parameters used by the given SelectKey and Entry.
  ///
  fn used_params(key: &SelectKey, entry: &Entry) -> Vec<TypeId> {
    // `Get`s introduce new Params to a subgraph, so using a Param provided by a Get does not
    // count toward an Entry's used params.
    let provided_param = match &key {
      &SelectKey::JustSelect(_) => None,
      &SelectKey::JustGet(ref g) => Some(&g.subject),
    };

    match &entry {
      &Entry::WithDeps(ref e) => e
        .params()
        .iter()
        .filter(|&type_id| Some(type_id) != provided_param)
        .cloned()
        .collect(),
      &Entry::Param(ref type_id) if Some(type_id) != provided_param => vec![*type_id],
      &Entry::Singleton { .. } | &Entry::Param(_) => vec![],
    }
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

  fn gen_root_entries(&self, product_types: &HashSet<TypeConstraint>) -> Vec<RootEntry> {
    product_types
      .iter()
      .filter_map(|product_type| self.gen_root_entry(&self.root_param_types, product_type))
      .collect()
  }

  fn gen_root_entry(
    &self,
    param_types: &ParamTypes,
    product_type: &TypeConstraint,
  ) -> Option<RootEntry> {
    let candidates = rhs(&self.tasks, param_types, product_type);
    if candidates.is_empty() {
      None
    } else {
      Some(RootEntry {
        params: param_types.clone(),
        clause: vec![Select::new(*product_type)],
        gets: vec![],
      })
    }
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
#[derive(Debug, Default)]
pub struct RuleGraph {
  root_param_types: ParamTypes,
  rule_dependency_edges: RuleDependencyEdges,
  unfulfillable_rules: UnfulfillableRuleMap,
  unreachable_rules: Vec<UnreachableError>,
}

// TODO: Take by reference.
fn type_constraint_str(type_constraint: TypeConstraint) -> String {
  let str_val = externs::call_method(&to_val(type_constraint), "graph_str", &[])
    .expect("string from calling repr");
  externs::val_to_str(&str_val)
}

fn to_val(type_constraint: TypeConstraint) -> Value {
  externs::val_for(&type_constraint.0)
}

fn to_val_from_func(func: &Function) -> Value {
  externs::val_for(&func.0)
}

fn function_str(func: &Function) -> String {
  let as_val = to_val_from_func(func);
  val_name(&as_val)
}

pub fn type_str(type_id: TypeId) -> String {
  if type_id == ANY_TYPE {
    "Any".to_string()
  } else {
    externs::type_to_str(type_id)
  }
}

pub fn params_str(params: &ParamTypes) -> String {
  let mut param_names = params
    .iter()
    .map(|type_id| type_str(*type_id))
    .collect::<Vec<_>>();
  param_names.sort();
  match param_names.len() {
    0 => "()".to_string(),
    1 => param_names.iter().next().unwrap().to_string(),
    _ => format!("({})", param_names.join("+")),
  }
}

fn val_name(val: &Value) -> String {
  externs::project_str(val, "__name__")
}

pub fn select_key_str(select_key: &SelectKey) -> String {
  match select_key {
    &SelectKey::JustSelect(ref s) => select_str(s),
    &SelectKey::JustGet(ref g) => get_str(g),
  }
}

pub fn select_str(select: &Select) -> String {
  format!("Select({})", type_constraint_str(select.product)).to_string() // TODO variant key
}

fn get_str(get: &Get) -> String {
  format!(
    "Get({}, {})",
    type_constraint_str(get.product),
    type_str(get.subject)
  )
}

///
/// TODO: Move all of these methods to Display impls.
///
pub fn entry_str(entry: &Entry) -> String {
  match entry {
    &Entry::WithDeps(ref e) => entry_with_deps_str(e),
    &Entry::Param(type_id) => format!("Param({})", type_str(type_id)),
    &Entry::Singleton(value, product) => format!(
      "Singleton({}, {})",
      externs::key_to_str(&value),
      type_constraint_str(product)
    ),
  }
}

fn entry_with_deps_str(entry: &EntryWithDeps) -> String {
  match entry {
    &EntryWithDeps::Inner(InnerEntry {
      rule: Rule::Task(ref task_rule),
      ref params,
    }) => format!("{} for {}", task_display(task_rule), params_str(params)),
    &EntryWithDeps::Inner(InnerEntry {
      rule: Rule::Intrinsic(ref intrinsic),
      ref params,
    }) => format!(
      "({}, ({},) for {}",
      type_constraint_str(intrinsic.product),
      type_constraint_str(intrinsic.input),
      params_str(params)
    ),
    &EntryWithDeps::Root(ref root) => format!(
      "{} for {}",
      root
        .clause
        .iter()
        .map(|s| select_str(s))
        .collect::<Vec<_>>()
        .join(", "),
      params_str(&root.params)
    ),
  }
}

fn task_display(task: &Task) -> String {
  let product = type_constraint_str(task.product);
  let mut clause_portion = task
    .clause
    .iter()
    .map(|c| select_str(c))
    .collect::<Vec<_>>()
    .join(", ");
  clause_portion = format!("[{}]", clause_portion);
  let mut get_portion = task
    .gets
    .iter()
    .map(|g| get_str(g))
    .collect::<Vec<_>>()
    .join(", ");
  get_portion = if task.gets.is_empty() {
    "".to_string()
  } else {
    format!("[{}], ", get_portion)
  };
  let function_name = function_str(&&task.func);
  format!(
    "({}, {}, {}{})",
    product, clause_portion, get_portion, function_name
  ).to_string()
}

impl RuleGraph {
  pub fn new(tasks: &Tasks, root_param_types: Vec<TypeId>) -> RuleGraph {
    GraphMaker::new(tasks, root_param_types).full_graph()
  }

  pub fn find_root_edges(&self, param_type: TypeId, select: Select) -> Option<RuleEdges> {
    // TODO: Support more than one root parameter... needs some API work.
    //   see https://github.com/pantsbuild/pants/issues/6478
    let root = RootEntry {
      params: vec![param_type].into_iter().collect(),
      clause: vec![select],
      gets: vec![],
    };
    self
      .rule_dependency_edges
      .get(&EntryWithDeps::Root(root))
      .cloned()
  }

  ///
  /// TODO: It's not clear what is preventing `Node` implementations from ending up with non-Inner
  /// entries, but it would be good to make it typesafe instead.
  ///
  pub fn edges_for_inner(&self, entry: &Entry) -> Option<RuleEdges> {
    if let &Entry::WithDeps(ref e) = entry {
      self.rule_dependency_edges.get(e).cloned()
    } else {
      panic!("not an inner entry! {:?}", entry)
    }
  }

  pub fn validate(&self) -> Result<(), String> {
    let mut collated_errors: HashMap<Task, Vec<Diagnostic>> = HashMap::new();

    let used_rules: HashSet<_> = self
      .rule_dependency_edges
      .keys()
      .filter_map(|entry| match entry {
        &EntryWithDeps::Inner(InnerEntry {
          rule: Rule::Task(ref task_rule),
          ..
        }) => Some(task_rule),
        _ => None,
      }).collect();

    let rule_diagnostics = self
      .unfulfillable_rules
      .iter()
      .filter_map(|(e, diagnostics)| match e {
        &EntryWithDeps::Inner(InnerEntry {
          rule: Rule::Task(ref task_rule),
          ..
        }) => Some((task_rule, diagnostics.clone())),
        _ => {
          // We're only checking rule usage not entry usage generally, so we ignore intrinsics.
          None
        }
      }).chain(
        self
          .unreachable_rules
          .iter()
          .map(|u| (&u.task_rule, vec![u.diagnostic.clone()])),
      );
    for (task_rule, diagnostics) in rule_diagnostics {
      if used_rules.contains(&task_rule) {
        continue;
      }
      for d in diagnostics {
        collated_errors
          .entry(task_rule.clone())
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
          }).collect::<Vec<_>>()
          .join("\n    ");
        format!("{}:\n    {}", task_display(&rule), errors)
      }).collect();
    msgs.sort();

    Err(format!("Rules with errors: {}\n  {}", msgs.len(), msgs.join("\n  ")).to_string())
  }

  pub fn visualize(&self, f: &mut io::Write) -> io::Result<()> {
    let mut root_subject_type_strs = self
      .root_param_types
      .iter()
      .map(|&t| type_str(t))
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
        &EntryWithDeps::Root(_) => {
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
      }).collect::<Vec<String>>();
    root_rule_strs.sort();
    writeln!(f, "{}", root_rule_strs.join("\n"))?;

    writeln!(f, "  // internal entries")?;
    let mut internal_rule_strs = self
      .rule_dependency_edges
      .iter()
      .filter_map(|(k, deps)| match k {
        &EntryWithDeps::Inner(_) => {
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
      }).collect::<Vec<String>>();
    internal_rule_strs.sort();
    writeln!(f, "{}", internal_rule_strs.join("\n"))?;
    writeln!(f, "}}")
  }
}

///
/// Records the dependency rules for a rule.
///
#[derive(Eq, PartialEq, Clone, Debug, Default)]
pub struct RuleEdges {
  dependencies: HashMap<SelectKey, Vec<Entry>>,
}

impl RuleEdges {
  pub fn entry_for(&self, select_key: &SelectKey) -> Option<&Entry> {
    self
      .dependencies
      .get(select_key)
      .and_then(|entries| entries.first())
  }

  pub fn all_dependencies(&self) -> impl Iterator<Item = &Entry> {
    Itertools::flatten(self.dependencies.values())
  }

  fn add_edge(&mut self, select_key: SelectKey, new_dependency: Entry) {
    self
      .dependencies
      .entry(select_key)
      .or_insert_with(Vec::new)
      .push(new_dependency);
  }
}

///
/// Select Entries that can provide the given product type with the given parameters.
///
fn rhs(tasks: &Tasks, params: &ParamTypes, product_type: &TypeConstraint) -> Vec<Entry> {
  if let Some(&(ref key, _)) = tasks.gen_singleton(product_type) {
    return vec![Entry::Singleton(*key, *product_type)];
  }

  let mut entries = Vec::new();
  if let Some(type_id) = params
    .iter()
    .find(|&&type_id| externs::satisfied_by_type(product_type, type_id))
  {
    // TODO: We only match the first param type here that satisfies the constraint although it's
    // possible that multiple parameters could. Would be nice to be able to remove TypeConstraint.
    entries.push(Entry::Param(*type_id));
  }
  if let Some(matching_intrinsic) = tasks.gen_intrinsic(product_type) {
    entries.push(Entry::WithDeps(EntryWithDeps::Inner(InnerEntry {
      params: params.clone(),
      rule: Rule::Intrinsic(*matching_intrinsic),
    })));
  }
  if let Some(matching_tasks) = tasks.gen_tasks(product_type) {
    entries.extend(matching_tasks.iter().map(|task_rule| {
      Entry::WithDeps(EntryWithDeps::Inner(InnerEntry {
        params: params.clone(),
        rule: Rule::Task(task_rule.clone()),
      }))
    }));
  }
  entries
}
