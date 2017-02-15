// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).


use std::collections::{hash_map, HashMap, HashSet, VecDeque};
use std::hash::Hash;

use core::{ANY_TYPE, Key, TypeConstraint, TypeId};
use externs;
use selectors::{Select, Selector};
use tasks::{Task, Tasks};

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
enum Entry {
  SubjectIsProduct {
    subject_type: TypeId
  },

  Root(RootEntry),

  InnerEntry(InnerEntry),

  Literal {
    value: Key,
    product: TypeConstraint
  },

  Unreachable {
    // NB: unreachable is an error type, it might be better to name it error, but currently
    //     unreachable is the only error entry type.
    rule: Task,
    reason: Diagnostic
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct RootEntry {
  subject_type: TypeId,
  clause: Vec<Selector>,
}

impl From<RootEntry> for Entry {
  fn from(entry: RootEntry) -> Entry {
    Entry::Root(entry)
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct InnerEntry {
  subject_type: TypeId,
  rule: Task
}

impl From<InnerEntry> for Entry {
  fn from(entry: InnerEntry) -> Entry {
    Entry::InnerEntry(entry)
  }
}

impl Entry {

  fn new_inner(subject_type: TypeId, rule: &Task) -> Entry {
    Entry::InnerEntry(InnerEntry {
      subject_type: subject_type,
      rule: rule.clone(),
    })
  }

  fn new_subject_is_product(subject_type: TypeId) -> Entry {
    Entry::SubjectIsProduct {
      subject_type: subject_type,

    }
  }

  fn new_unreachable(rule: &Task) -> Entry {
    Entry::Unreachable {
      rule: rule.clone(),
      reason: Diagnostic { subject_type: ANY_TYPE, reason: "".to_string() },
    }
  }

  fn new_literal(value: Key, product: TypeConstraint) -> Entry {
    Entry::Literal {
      value: value,
      product: product
    }
  }

  fn can_have_dependencies(&self) -> bool {
    match self {
      &Entry::SubjectIsProduct {..} => false,
      &Entry::Literal { .. } => false,
      &Entry::InnerEntry(_) => true,
      &Entry::Root(_) => true,
      &Entry::Unreachable { .. } => false,
    }
  }

  fn can_be_dependency(&self) -> bool {
    match self {
      &Entry::SubjectIsProduct { .. } => true,
      &Entry::Literal { .. } => true,
      &Entry::InnerEntry(_) => true,
      &Entry::Root(_) => false,
      &Entry::Unreachable { .. } => false,
    }
  }

  fn subject_type(&self) -> TypeId {
    match self {
      &Entry::InnerEntry(ref inner) => inner.subject_type,
      &Entry::Root(ref root) => root.subject_type,
      &Entry::SubjectIsProduct { subject_type, .. } => subject_type,
      _ => panic!("has no subject type"),

    }
  }

  fn rule(&self) -> &Task {
    match self {
      &Entry::InnerEntry(ref inner) => &inner.rule,
      &Entry::Unreachable { ref rule, .. } => rule,
      _ => panic!("no rule"),
    }
  }
}

type Entries = Vec<Entry>;
type RootRuleDependencyEdges = HashMap<RootEntry, RuleEdges>;
type Rule = Task;
type RuleDependencyEdges = HashMap<InnerEntry, RuleEdges>;
type RuleDiagnostics = Vec<Diagnostic>;
type UnfulfillableRuleMap = HashMap<Entry, RuleDiagnostics>;

#[derive(Debug)]
pub struct RootSubjectTypes {
  pub subject_types: Vec<TypeId>
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct Diagnostic {
  subject_type: TypeId,
  reason: String
}

// Given the task index and the root subjects, it produces a rule graph that allows dependency nodes
// to be found statically rather than dynamically.
pub struct GraphMaker<'t, 'e> {
  tasks: &'t Tasks,
  root_subject_types: RootSubjectTypes
}

impl <'t, 'e> GraphMaker<'t, 'e> {
  pub fn new(tasks: &'t Tasks, root_subject_types: RootSubjectTypes) -> GraphMaker<'t, 'e> {
    GraphMaker {
      tasks: tasks,
      root_subject_types: root_subject_types
    }
  }

  pub fn full_graph(&self) -> RuleGraph {
    let mut full_root_rule_dependency_edges: RootRuleDependencyEdges = HashMap::new();
    let mut full_dependency_edges: RuleDependencyEdges = HashMap::new();
    let mut full_unfulfillable_rules: UnfulfillableRuleMap = HashMap::new();

    let product_types = self.tasks.all_product_types();
    for beginning_root in self.gen_root_entries(&product_types) {
      let constructed_graph = self._construct_graph(
        beginning_root,
        full_root_rule_dependency_edges,
        full_dependency_edges,
        full_unfulfillable_rules
      );

      // less than ideal, the copying
      full_root_rule_dependency_edges = constructed_graph.root_dependencies.clone();
      full_dependency_edges = constructed_graph.rule_dependency_edges.clone();
      full_unfulfillable_rules = constructed_graph.unfulfillable_rules.clone();
    }
    let rules_in_graph: HashSet<_> = full_dependency_edges.keys().map(|f| f.rule.clone()).collect();
    let unfulfillable_discovered_during_construction: HashSet<_> = full_unfulfillable_rules.keys().map(|f| f.rule().clone()).collect();
    let declared_rules = self.tasks.all_rules();
    let unreachable_rules: HashSet<_> = declared_rules.iter()
      .filter(|r| !rules_in_graph.contains(r))
      .filter(|r| !unfulfillable_discovered_during_construction.contains(r))
      .filter(|r| !self.tasks.is_singleton_task(r))
      .filter(|r| !self.tasks.is_intrinsic_task(r))
      .map(|&r| r)
      .collect();

    for rule in unreachable_rules {
      let diagnostics = full_unfulfillable_rules.entry(Entry::new_unreachable(rule)).or_insert(vec![]);
      diagnostics.push(Diagnostic{subject_type: ANY_TYPE, reason:"Unreachable".to_string()});
    }

    let unfinished_graph = RuleGraph {
      root_dependencies: full_root_rule_dependency_edges,
      rule_dependency_edges: full_dependency_edges,
      unfulfillable_rules: full_unfulfillable_rules
    };

    self._remove_unfulfillable_rules_and_dependents(unfinished_graph)
  }

  fn _construct_graph(&self,
                      beginning_rule: RootEntry,
                      mut root_rule_dependency_edges: RootRuleDependencyEdges,
                      mut rule_dependency_edges: RuleDependencyEdges,
                      mut unfulfillable_rules: UnfulfillableRuleMap) -> RuleGraph {

    let mut rules_to_traverse: VecDeque<Entry> = VecDeque::new();
    rules_to_traverse.push_back(Entry::from(beginning_rule));
    while let Some(entry) = rules_to_traverse.pop_front() {
      if entry.can_be_dependency() && !entry.can_have_dependencies() {
        continue
      }
      if !entry.can_have_dependencies() {
        panic!("Cannot determine dependencies of entry not of type CanHaveDependencies: {:?}", entry)
      }
      if unfulfillable_rules.contains_key(&entry) {
        continue
      }
      if let Entry::InnerEntry(ref inner_entry) = entry {
        if rule_dependency_edges.contains_key(inner_entry) {
          continue
        }
      }
      let mut was_unfulfillable = false;
      match entry {
        Entry::InnerEntry(InnerEntry { rule: Task { ref clause, .. }, .. }) |
        Entry::Root(RootEntry { ref clause, .. }) => {
          for selector in clause {
            match selector {
              &Selector::Select(ref select) =>{
                // TODO, handle the Addresses / Variants case
                let rules_or_literals_for_selector = rhs_for_select(&self.tasks,
                                                                    entry.subject_type(),
                                                                    &select);
                if rules_or_literals_for_selector.is_empty() {
                  mark_unfulfillable(&mut unfulfillable_rules,
                                     &entry,
                                     entry.subject_type(),
                                     // might be better as {} with display derived
                                     format!("no matches for {:?}", select));
                  was_unfulfillable = true;
                  continue;
                }
                add_rules_to_graph(&mut rules_to_traverse,
                                   &mut rule_dependency_edges,
                                   &mut unfulfillable_rules,
                                   &mut root_rule_dependency_edges,
                                   &entry,
                                   vec![Selector::Select(select.clone())],
                                   rules_or_literals_for_selector);
              },
              &Selector::SelectLiteral(ref select) =>{
                add_rules_to_graph(&mut rules_to_traverse,
                                   &mut rule_dependency_edges,
                                   &mut unfulfillable_rules,
                                   &mut root_rule_dependency_edges,
                                   &entry,
                                   vec![selector.clone()],
                                   vec![Entry::new_literal(select.subject.clone(),
                                                               select.product.clone())]);
              },
              &Selector::SelectDependencies(ref select) => {
                let initial_selector = select.dep_product;
                let initial_rules_or_literals = rhs_for_select(&self.tasks,
                                                               entry.subject_type(),
                                                               &Select { product: initial_selector, variant_key: None });
                if initial_rules_or_literals.is_empty() {
                  mark_unfulfillable(&mut unfulfillable_rules,
                                     &entry,
                                     entry.subject_type(),
                                     format!("no matches for {:?} when resolving {:?}", entry.subject_type(), initial_selector)); // might be better as {} with display derived
                  was_unfulfillable = true;
                  continue;
                }
                let mut rules_for_dependencies = vec![];
                for field_type in &select.field_types {
                  let rules_for_field_subjects = rhs_for_select(&self.tasks,
                                                                field_type.clone(),
                                                                &Select { product: select.product, variant_key: None });
                  rules_for_dependencies.extend(rules_for_field_subjects);
                }
                if rules_for_dependencies.is_empty() {
                    for t in &select.field_types {
                        mark_unfulfillable(&mut unfulfillable_rules,
                                           &entry,
                                           t.clone(),
                                           format!("no matches for {:?} when resolving {:?}", select.product, select)
                        );
                    }
                  was_unfulfillable = true;
                  continue;
                }
                add_rules_to_graph(&mut rules_to_traverse,
                                   &mut rule_dependency_edges,
                                   &mut unfulfillable_rules,
                                   &mut root_rule_dependency_edges,
                                   &entry,
                                   vec![selector.clone(), Selector::Select(Select { product: select.dep_product, variant_key: None})],
                                   initial_rules_or_literals);

                add_rules_to_graph(&mut rules_to_traverse,
                                   &mut rule_dependency_edges,
                                   &mut unfulfillable_rules,
                                   &mut root_rule_dependency_edges,
                                   &entry,
                                   vec![selector.clone(), Selector::Select(Select { product: select.product, variant_key: None})],
                                   rules_for_dependencies);
              },
              &Selector::SelectProjection(ref select) =>{
                let initial_selector = select.input_product;
                let initial_rules_or_literals = rhs_for_select(&self.tasks,
                                                               entry.subject_type(),
                                                               &Select { product: initial_selector, variant_key: None });
                if initial_rules_or_literals.is_empty() {
                  mark_unfulfillable(&mut unfulfillable_rules,
                                     &entry,
                                     entry.subject_type(),
                                     format!("no matches for {:?} when resolving {:?}", initial_selector, initial_selector)); // might be better as {} with display derived
                  was_unfulfillable = true;
                  continue
                }

                let projected_rules_or_literals = rhs_for_select(&self.tasks,
                                                                 select.projected_subject,
                                                                 &Select { product: select.product, variant_key: None });
                if projected_rules_or_literals.is_empty() {
                  mark_unfulfillable(&mut unfulfillable_rules,
                                     &entry,
                                     select.projected_subject,
                                     format!("no matches for {:?} when resolving {:?}", select.product, select)); // might be better as {} with display derived
                  was_unfulfillable = true;
                  continue

                }
                add_rules_to_graph(&mut rules_to_traverse,
                                   &mut rule_dependency_edges,
                                   &mut unfulfillable_rules,
                                   &mut root_rule_dependency_edges,
                                   &entry,
                                   vec![Selector::SelectProjection(select.clone()),
                                        Selector::Select(Select { product: initial_selector, variant_key: None })
                                   ],
                                   initial_rules_or_literals);
                add_rules_to_graph(&mut rules_to_traverse,
                                   &mut rule_dependency_edges,
                                   &mut unfulfillable_rules,
                                   &mut root_rule_dependency_edges,
                                   &entry,
                                   vec![Selector::SelectProjection(select.clone()),
                                        Selector::Select(Select { product: select.product, variant_key: None })
                                   ],
                                   projected_rules_or_literals);
              },
            }
          }
        },
        _ => { panic!("Entry type that cannot dependencies was not filtered out {:?}", entry) }
      }
      // TODO handle snapshot rules
      if !was_unfulfillable {
        // NB: In this case there were no selectors
        add_rules_to_graph(&mut rules_to_traverse,
                           &mut rule_dependency_edges,
                           &mut unfulfillable_rules,
                           &mut root_rule_dependency_edges,
                           &entry,
                           vec![],
                           vec![]);
      }
    }
    RuleGraph {root_dependencies: root_rule_dependency_edges, rule_dependency_edges: rule_dependency_edges, unfulfillable_rules: unfulfillable_rules}
  }

  fn _remove_unfulfillable_rules_and_dependents(&self,
                                                mut rule_graph: RuleGraph) -> RuleGraph {
    // Removes all unfulfillable rules transitively from the roots and the dependency edges.
    //
    // Takes the current root rule set and dependency table and removes all rules that are not
    // transitively fulfillable.
    //
    // Deforestation. Leaping from tree to tree.

    let mut removal_traversal: VecDeque<_> = rule_graph.unfulfillable_rules.keys()
      .map(|r| r.clone())
      .collect();
    // could experiment with doing this for each rule added and deduping the traversal list
    while let Some(unfulfillable_entry) = removal_traversal.pop_front() {
      update_edges_based_on_unfulfillable_entry(&mut rule_graph.rule_dependency_edges,
                                                &mut rule_graph.unfulfillable_rules,
                                                &mut removal_traversal,
                                                &unfulfillable_entry);
      update_edges_based_on_unfulfillable_entry(&mut rule_graph.root_dependencies,
                                                &mut rule_graph.unfulfillable_rules,
                                                &mut removal_traversal,
                                                &unfulfillable_entry);
    }

    // blow up if there's something off.
    // TODO do this with types on add rather than blowing up after.
    // I think I could make it impossible rather than fixing up after the fact.
    for (ref root_rule, ref deps)  in &rule_graph.root_dependencies {
      for d in &deps.dependencies {
        match d {
          &Entry::InnerEntry(ref inner) => {
            if !rule_graph.rule_dependency_edges.contains_key(inner) {
              panic!("All referenced dependencies should have entries in the graph, but {:?} had {:?}, \
                  which is missing!", root_rule, d)
            }
          },
          // TODO, this should be ensured on edge add.
          &Entry::Root(_) => panic!("Root entries cannot be depended on"),
          _ => {
            // ok
          }
        }
      }
    }
    rule_graph
  }

  fn gen_root_entries(&self, product_types: &Vec<TypeConstraint>) -> Vec<RootEntry> {
    let mut result: Vec<RootEntry> = Vec::new();
    for subj_type in &self.root_subject_types.subject_types {
      for pt in product_types {
        if let Some(tasks) = self.tasks.gen_tasks(subj_type, pt) {
          if !tasks.is_empty() {
            result.push(RootEntry {
              subject_type: subj_type.clone(),
              clause: vec![Selector::Select(Select {
                product: pt.clone(),
                variant_key: None
              })]
            });
          }
        }
      }
    }
    result
  }
}

#[derive(Debug)]
pub struct RuleGraph {
  root_dependencies: RootRuleDependencyEdges,
  rule_dependency_edges: RuleDependencyEdges,
  unfulfillable_rules: UnfulfillableRuleMap,
}

impl RuleGraph {
  pub fn validate(&self) -> Result<(), String> {
    if self.has_errors() {
      Result::Err(self.build_error_msg())
    } else {
      Result::Ok(())
    }
  }

  fn build_error_msg(&self) -> String {
    // TODO the rule display is really unfriendly right now. Next up should be to improve it.
    let mut collated_errors: HashMap<Task, HashMap<String, HashSet<TypeId>>> = HashMap::new();

    let used_rules: HashSet<_> = self.rule_dependency_edges.keys().map(|entry| &entry.rule).collect();
    for (rule_entry, diagnostics) in &self.unfulfillable_rules {
      match rule_entry {
        &Entry::InnerEntry(ref inner) => {
          if used_rules.contains(&inner.rule) {
            continue
          }
          for d in diagnostics {
            let mut msg_to_type = collated_errors.entry(inner.rule.clone())
              .or_insert(HashMap::new());
            let mut subject_set = msg_to_type.entry(d.reason.clone())
              .or_insert(HashSet::new());
            subject_set.insert(d.subject_type.clone());
          }
        },
        _ => { } // We're only checking rule usage not entry usage generally.
                 // So we ignore entries that do not have rules.
      }
    }
    let mut msgs: Vec<String> = collated_errors.into_iter()
      .map(|(ref rule, ref subject_types_by_reasons)| format_msgs(rule, subject_types_by_reasons))
      .collect();
    msgs.sort();

    format!("Rules with errors {}:\n  {}", msgs.len(), msgs.join("\n  ")).to_string()
  }

  fn has_errors(&self) -> bool {
    let used_rules: HashSet<_> = self.rule_dependency_edges.keys().map(|entry| &entry.rule).collect();
    self.unfulfillable_rules.iter().any(|(&ref entry, &ref diagnostics)| match entry {
      &Entry::InnerEntry(ref inner) => !used_rules.contains(&inner.rule) &&
                                       !diagnostics.is_empty(),
      _ => false,
    })
  }
}

#[derive(Eq, PartialEq, Clone, Debug)]
pub struct RuleEdges {
  dependencies: Entries,
  selector_to_dependencies: HashMap<Vec<Selector>, Entries>
}

impl RuleEdges {

  fn new() -> RuleEdges {
    RuleEdges {
      dependencies: vec![],
      selector_to_dependencies: HashMap::new()
    }
  }

  fn add_edges_via(&mut self, selector_path: Vec<Selector>, new_dependencies: &Entries) {
    if selector_path.is_empty() && !new_dependencies.is_empty() {
      panic!("Cannot specify a None selector with non-empty dependencies!")
    }
    let mut deps_for_selector = self.selector_to_dependencies.entry(selector_path).or_insert(vec![]);
    for d in new_dependencies {
      deps_for_selector.push(d.clone());
      self.dependencies.push(d.clone());
    }
  }

  fn has_edges_for(&self, selector_path: Vec<Selector>) -> bool {
    self.selector_to_dependencies.contains_key(&selector_path)
  }

  fn makes_unfulfillable(&self, dep_to_eliminate: &Entry) -> bool {
    // Returns true if removing dep_to_eliminate makes this set of edges unfulfillable.
    if self.dependencies.len() == 1 && &self.dependencies[0] == dep_to_eliminate {
      true
    } else if self.selector_to_dependencies.values().any(|deps| deps.len() == 1 && &deps[0] == dep_to_eliminate) {
      true
    } else {
      false
    }
  }

  fn without_rule(&self, dep: &Entry) -> RuleEdges {
    let new_deps: Entries = self.dependencies.iter().filter(|&d| d != dep).map(|d|d.clone()).collect();
    if new_deps.len() == self.dependencies.len() {
      return self.clone();
    }
    let mut new_selector_deps: HashMap<Vec<Selector>, Entries> = HashMap::new();
    for (selector, deps) in &self.selector_to_dependencies {
      new_selector_deps.insert(selector.clone(), deps.iter().filter(|&d| d != dep).map(|d| d.clone()).collect());
    }
    RuleEdges { dependencies: new_deps, selector_to_dependencies: new_selector_deps}
  }
}

fn update_edges_based_on_unfulfillable_entry<K>(edge_container: &mut HashMap<K, RuleEdges>,
                                                new_unfulfillable_rules: &mut UnfulfillableRuleMap,
                                                removal_traversal: &mut VecDeque<Entry>,
                                                unfulfillable_entry: &Entry
)
  where Entry: From<K>,
        K: Eq + Hash + Clone
{
  let keys: Vec<_> = edge_container.keys()
    .filter(|&c| !new_unfulfillable_rules.contains_key(&Entry::from(c.clone())))
    .map(|c| c.clone())
    .collect();
  for current_entry in keys {
    if let hash_map::Entry::Occupied(mut o) = edge_container.entry(current_entry) {
      if o.get().makes_unfulfillable(&unfulfillable_entry) {
        let key_entry = Entry::from(o.key().clone());

        let entry_subject = key_entry.subject_type();
        let mut diagnostics = new_unfulfillable_rules.entry(key_entry.clone()).or_insert(vec![]);
        diagnostics.push(Diagnostic {
          subject_type: entry_subject,
          reason: format!("depends on unfulfillable {:?}", unfulfillable_entry)
        });

        removal_traversal.push_back(key_entry.clone());

        o.remove();
      } else {
        let deps_without_rule = o.get().without_rule(&unfulfillable_entry);
        o.insert(deps_without_rule);
      }
    }
  }
}

fn rhs_for_select(tasks: &Tasks, subject_type: TypeId, select: &Select) -> Entries {
  if externs::satisfied_by(&select.product, &subject_type) {
    // NB a matching subject is always picked first
    vec![Entry::new_subject_is_product(subject_type)]
  } else {
    match tasks.gen_tasks(&subject_type, &select.product) {
      Some(ref matching_tasks) => {
        matching_tasks.iter().map(|t| Entry::new_inner(subject_type, t)).collect()
      }
      None => vec![]
    }
  }
}

fn mark_unfulfillable(unfulfillable_rules: &mut UnfulfillableRuleMap, entry: &Entry, subject_type: TypeId, reason: String) {
  // instead of being modifiable, this could return a UnfulfillableRuleMap that then gets merged.
  let ref mut diagnostics_for_entry = *unfulfillable_rules.entry(entry.clone()).or_insert(vec![]);
  diagnostics_for_entry.push(Diagnostic { subject_type: subject_type, reason: reason });
}

fn add_rules_to_graph(rules_to_traverse: &mut VecDeque<Entry>,
                      rule_dependency_edges: &mut RuleDependencyEdges,
                      unfulfillable_rules: &mut UnfulfillableRuleMap,
                      root_rule_dependency_edges: &mut RootRuleDependencyEdges,
                      entry: &Entry,
                      selector_path: Vec<Selector>,
                      dep_rules: Entries) {
  {
    let rule_deps: &RuleDependencyEdges = rule_dependency_edges;
    let unseen_dep_rules = dep_rules.iter()
      .filter(|g| !unfulfillable_rules.contains_key(g))
      .filter(|g| match *g {
        &Entry::InnerEntry(ref r) => !rule_deps.contains_key(&r),
        &Entry::Root(ref r) => !root_rule_dependency_edges.contains_key(&r),
        _ => true
      })
      .map(|g| g.clone());
    rules_to_traverse.extend(unseen_dep_rules);
  }
  match entry {
    &Entry::Root(ref root_entry) => {
      let mut edges = root_rule_dependency_edges.entry(root_entry.clone()).or_insert(RuleEdges::new());
      edges.add_edges_via(selector_path, &dep_rules);
    },
    &Entry::InnerEntry(ref inner_entry) => {
      let mut edges = rule_dependency_edges.entry(inner_entry.clone()).or_insert(RuleEdges::new());
      if edges.has_edges_for(selector_path.clone()) {
        // This is an error that should only happen if there's a bug in the algorithm, but it
        // might make sense to expose it in a more friendly way.
        panic!("Rule {:?} already has dependencies set for selector {:?}", entry, selector_path)
      }
      edges.add_edges_via(selector_path, &dep_rules);
    },
    _ => {
      // these should have already been filtered out before this was called.
      // TODO enforce ^^ more clearly
      panic!("expected this entry type to have already been filtered out {:?}", entry)
    }
  }
}

fn format_msgs(rule: &Task, subject_types_by_reasons: &HashMap<String, HashSet<TypeId>>) -> String {
  let mut errors: Vec<_> = subject_types_by_reasons.iter().map(|(reason, subject_types)|
    format!("{} with subject types: {}",
            reason,
            subject_types.iter().map(|t| externs::id_to_str(t.0)).collect::<Vec<String>>().join(", "))
  ).collect();
  errors.sort();
  format!("{:?}: {}", rule, errors.join("\n    "))
}
