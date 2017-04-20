// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).


use std::collections::{hash_map, HashMap, HashSet, VecDeque};
use std::hash::Hash;
use std::fmt;
use std::io;

use core::{ANY_TYPE, Function, Id, Key, TypeConstraint, TypeId, Value};
use externs;
use selectors::{Select, SelectDependencies, SelectTransitive, Selector};
use tasks::{Task, Tasks};

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum Entry {
  SubjectIsProduct {
    subject_type: TypeId
  },

  Root(RootEntry),

  InnerEntry(InnerEntry),

  Singleton {
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

impl Entry {

  pub fn matches_subject_type(&self, actual_subject_type: TypeId) -> bool {
    match *self {
      Entry::SubjectIsProduct { subject_type } |
      Entry::Root(RootEntry { subject_type, .. }) |
      Entry::InnerEntry(InnerEntry { subject_type, .. }) =>
        subject_type == actual_subject_type,
      Entry::Singleton { .. } =>
        true,
      Entry::Unreachable { .. }=>
        panic!("Shouldn't compare to an unreachable entry!")
    }
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct RootEntry {
  subject_type: TypeId,
  clause: Vec<Selector>,
}

impl From<RootEntry> for Entry {
  fn from(entry: RootEntry) -> Entry {
    Entry::Root(entry)
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct InnerEntry {
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

  fn new_singleton(value: Key, product: TypeConstraint) -> Entry {
    Entry::Singleton {
      value: value,
      product: product
    }
  }

  fn can_have_dependencies(&self) -> bool {
    match self {
      &Entry::SubjectIsProduct {..} => false,
      &Entry::Singleton { .. } => false,
      &Entry::InnerEntry(_) => true,
      &Entry::Root(_) => true,
      &Entry::Unreachable { .. } => false,
    }
  }

  fn can_be_dependency(&self) -> bool {
    match self {
      &Entry::SubjectIsProduct { .. } => true,
      &Entry::Singleton { .. } => true,
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


///
/// A key for the Selects used from a rule. Rules are only picked up by Select selectors. These keys uniquely identify the
/// selects used by a particular entry in the rule graph so that they can be mapped to the dependencies they correspond
/// to.
///
#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum SelectKey {
  // A bare select with no projection.
  JustSelect(Select),
  // The initial select of a multi-select operator, eg SelectDependencies.
  NestedSelect(Selector, Select),
  // The projected select of a multi-select operator when there can be only be one projected type.
  ProjectedNestedSelect(Selector, TypeId, Select),
  // The projected select of a multi-select operator when there can be multiple projected types.
  ProjectedMultipleNestedSelect(Selector, Vec<TypeId>, Select),
  // No selector. Used for tasks with no dependencies.
  Nothing
}

pub type Entries = Vec<Entry>;
type RootRuleDependencyEdges = HashMap<RootEntry, RuleEdges>;
type RuleDependencyEdges = HashMap<InnerEntry, RuleEdges>;
type RuleDiagnostics = Vec<Diagnostic>;
type UnfulfillableRuleMap = HashMap<Entry, RuleDiagnostics>;

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct Diagnostic {
  subject_type: TypeId,
  reason: String
}

// Given the task index and the root subjects, it produces a rule graph that allows dependency nodes
// to be found statically rather than dynamically.
pub struct GraphMaker<'t> {
    tasks: &'t Tasks,
    root_subject_types: Vec<TypeId>
}

impl <'t> GraphMaker<'t> {
  pub fn new(tasks: &'t Tasks, root_subject_types: Vec<TypeId>) -> GraphMaker<'t> {
    GraphMaker { tasks: tasks, root_subject_types: root_subject_types }
  }

  pub fn sub_graph(&self, subject_type: &TypeId, product_type: &TypeConstraint) -> RuleGraph {
    let mut full_root_rule_dependency_edges: RootRuleDependencyEdges = HashMap::new();
    let mut full_dependency_edges: RuleDependencyEdges = HashMap::new();
    let mut full_unfulfillable_rules: UnfulfillableRuleMap = HashMap::new();

    let beginning_root = if let Some(beginning_root) = self.gen_root_entry(subject_type, product_type) {
      beginning_root
    } else {
      return RuleGraph {   root_subject_types: vec![],
        root_dependencies: full_root_rule_dependency_edges,
        rule_dependency_edges: full_dependency_edges,
        unfulfillable_rules: full_unfulfillable_rules,
      }
    };

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

    self.add_unreachable_rule_diagnostics(&full_dependency_edges, &mut full_unfulfillable_rules);

    let mut unfinished_graph = RuleGraph {
      root_subject_types: self.root_subject_types.clone(),
      root_dependencies: full_root_rule_dependency_edges,
      rule_dependency_edges: full_dependency_edges,
      unfulfillable_rules: full_unfulfillable_rules
    };

    self._remove_unfulfillable_rules_and_dependents(&mut unfinished_graph);
    unfinished_graph
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

    self.add_unreachable_rule_diagnostics(&full_dependency_edges, &mut full_unfulfillable_rules);

    let mut in_progress_graph = RuleGraph {
      root_subject_types: self.root_subject_types.clone(),
      root_dependencies: full_root_rule_dependency_edges,
      rule_dependency_edges: full_dependency_edges,
      unfulfillable_rules: full_unfulfillable_rules
    };

    self._remove_unfulfillable_rules_and_dependents(&mut in_progress_graph);
    in_progress_graph
  }

  fn add_unreachable_rule_diagnostics(&self, full_dependency_edges: &RuleDependencyEdges, full_unfulfillable_rules: &mut UnfulfillableRuleMap) {
    let rules_in_graph: HashSet<_> = full_dependency_edges.keys().map(|f| f.rule.clone()).collect();
    let unfulfillable_discovered_during_construction: HashSet<_> = full_unfulfillable_rules.keys().map(|f| f.rule().clone()).collect();
    let unreachable_rules: HashSet<_> = self.tasks.all_tasks().iter()
      .filter(|r| !rules_in_graph.contains(r))
      .filter(|r| !unfulfillable_discovered_during_construction.contains(r))
      .map(|&r| r)
      .collect();

    for rule in unreachable_rules {
      let diagnostics = full_unfulfillable_rules.entry(Entry::new_unreachable(rule)).or_insert(vec![]);
      diagnostics.push(Diagnostic { subject_type: ANY_TYPE, reason: "Unreachable".to_string() });
    }
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
                                     format!("no matches for {}", selector_str(selector)));
                  was_unfulfillable = true;
                  continue;
                }
                add_rules_to_graph(&mut rules_to_traverse,
                                   &mut rule_dependency_edges,
                                   &mut unfulfillable_rules,
                                   &mut root_rule_dependency_edges,
                                   &entry,
                                   SelectKey::JustSelect(select.clone()),
                                   rules_or_literals_for_selector);
              },
              &Selector::SelectDependencies(SelectDependencies{ref product, ref dep_product, ref field_types, ..}) |
              &Selector::SelectTransitive(SelectTransitive{ref product, ref dep_product, ref field_types, ..}) => {
                let initial_selector = *dep_product;
                let initial_rules_or_literals = rhs_for_select(&self.tasks,
                                                               entry.subject_type(),
                                                               &Select::without_variant(initial_selector));
                if initial_rules_or_literals.is_empty() {
                  mark_unfulfillable(&mut unfulfillable_rules,
                                     &entry,
                                     entry.subject_type(),
                                     format!("no matches for {} when resolving {}",
                                             selector_str(&Selector::Select(Select::without_variant(initial_selector))),
                                             selector_str(selector)));
                  was_unfulfillable = true;
                  continue;
                }
                let mut rules_for_dependencies = vec![];
                for field_type in field_types {
                  let rules_for_field_subjects = rhs_for_select(&self.tasks,
                                                                field_type.clone(),
                                                                &Select { product: *product, variant_key: None });
                  rules_for_dependencies.extend(rules_for_field_subjects);
                }
                if rules_for_dependencies.is_empty() {
                    for t in field_types {
                        mark_unfulfillable(&mut unfulfillable_rules,
                                           &entry,
                                           t.clone(),
                                           format!("no matches for {} when resolving {}",
                                                   selector_str(&Selector::Select(Select::without_variant(*product))),
                                                   selector_str(selector))
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
                                   SelectKey::NestedSelect(
                                     selector.clone(),
                                     Select::without_variant(*dep_product)),
                                   initial_rules_or_literals);

                add_rules_to_graph(&mut rules_to_traverse,
                                   &mut rule_dependency_edges,
                                   &mut unfulfillable_rules,
                                   &mut root_rule_dependency_edges,
                                   &entry,
                                   SelectKey::ProjectedMultipleNestedSelect(
                                     selector.clone(),
                                     field_types.clone(),
                                     Select::without_variant(*product)),
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
                                     format!("no matches for {} when resolving {}",
                                             selector_str(&Selector::Select(Select::without_variant(initial_selector))),
                                             selector_str(selector)));
                  was_unfulfillable = true;
                  continue
                }

                let projected_rules_or_literals = rhs_for_select(&self.tasks,
                                                                 select.projected_subject,
                                                                 &Select::without_variant(select.product));
                if projected_rules_or_literals.is_empty() {
                  mark_unfulfillable(&mut unfulfillable_rules,
                                     &entry,
                                     select.projected_subject,
                                     format!("no matches for {} when resolving {}",
                                             selector_str(&Selector::Select(Select::without_variant(select.product))),
                                             selector_str(selector)));
                  was_unfulfillable = true;
                  continue

                }
                add_rules_to_graph(&mut rules_to_traverse,
                                   &mut rule_dependency_edges,
                                   &mut unfulfillable_rules,
                                   &mut root_rule_dependency_edges,
                                   &entry,
                                   SelectKey::NestedSelect(
                                     selector.clone(),
                                     Select::without_variant(initial_selector)),
                                   initial_rules_or_literals);
                add_rules_to_graph(&mut rules_to_traverse,
                                   &mut rule_dependency_edges,
                                   &mut unfulfillable_rules,
                                   &mut root_rule_dependency_edges,
                                   &entry,
                                   SelectKey::ProjectedNestedSelect(
                                     selector.clone(),
                                     select.projected_subject,
                                     Select::without_variant(select.product)),
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
                           SelectKey::Nothing,
                           vec![]);
      }
    }
    RuleGraph {
      root_subject_types: self.root_subject_types.clone(),
      root_dependencies: root_rule_dependency_edges,
      rule_dependency_edges: rule_dependency_edges,
      unfulfillable_rules: unfulfillable_rules
    }
  }

  fn _remove_unfulfillable_rules_and_dependents(&self,
                                                rule_graph: &mut RuleGraph) {
    // Removes all unfulfillable rules transitively from the roots and the dependency edges.
    //
    // Takes the current root rule set and dependency table and removes all rules that are not
    // transitively fulfillable.
    //
    // Deforestation. Leaping from tree to tree.

    let mut removal_traversal: VecDeque<_> = rule_graph.unfulfillable_rules.keys()
      .cloned()
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
  }

  fn gen_root_entries(&self, product_types: &HashSet<TypeConstraint>) -> Vec<RootEntry> {
    let mut result: Vec<RootEntry> = Vec::new();
    for subj_type in &self.root_subject_types {
      for pt in product_types {
        if let Some(entry) = self.gen_root_entry(subj_type, pt) {
          result.push(entry);
        }
      }
    }
    result
  }

  fn gen_root_entry(&self, subject_type: &TypeId, product_type: &TypeConstraint) -> Option<RootEntry> {
    self.tasks.gen_tasks(product_type)
      .and_then(|tasks| if !tasks.is_empty() { Some(tasks) } else { None })
      .map(|_| {
        RootEntry {
          subject_type: subject_type.clone(),
          clause: vec![
            Selector::Select(Select {
              product: product_type.clone(),
              variant_key: None
            })
          ]
        }
      })
  }
}


///
/// A graph containing rules mapping rules to their dependencies taking into account subject types.
///
/// This is a graph of rules. It models dependencies between rules, along with the subject types for
/// those rules. This allows the resulting graph to include cases where a selector is fulfilled by the
/// subject of the graph.
///
///
/// `root_subject_types` the root subject types this graph was generated with.
/// `root_dependencies` A map from root rules, ie rules representing the expected selector / subject types
///   for requests, to the rules that can fulfill them.
/// `rule_dependency_edges` A map from rule entries to the rule entries they depend on.
///   The collections of dependencies are contained by RuleEdges objects.
/// `unfulfillable_rules` A map of rule entries to collections of Diagnostics
///   containing the reasons why they were eliminated from the graph.
#[derive(Debug)]
pub struct RuleGraph {
  root_subject_types: Vec<TypeId>,
  root_dependencies: RootRuleDependencyEdges,
  rule_dependency_edges: RuleDependencyEdges,
  unfulfillable_rules: UnfulfillableRuleMap,
}

fn type_constraint_str(type_constraint: TypeConstraint) -> String {
  let val = to_val(type_constraint);
  call_on_val(&val, "graph_str")
}

fn to_val(type_constraint: TypeConstraint) -> Value {
  to_val_from_id(type_constraint.0)
}

fn to_val_from_func(func: &Function) -> Value {
  to_val_from_id(func.0)
}

fn to_val_from_id(id: Id) -> Value {
  externs::val_for_id(id)
}

fn call_on_val(value: &Value, method: &str) -> String {
  let rpr_val = externs::project_ignoring_type(&value, method);

  let invoke_result  = externs::invoke_runnable(&rpr_val, &[], false)
                              .expect("string from calling repr");
  externs::val_to_str(&invoke_result)
}


fn function_str(func: &Function) -> String {
  let as_val = to_val_from_func(func);
  val_name(&as_val)
}


pub fn type_str(type_id: TypeId) -> String {
  if type_id == ANY_TYPE {
    "Any".to_string()
  } else {
    let as_val = to_val_from_id(type_id.0);
    val_name(&as_val)
  }
}

fn val_name(val: &Value) -> String {
  externs::project_str(val, "__name__")
}

pub fn selector_str(selector: &Selector) -> String {
  match selector {
    &Selector::Select(ref s) => format!("Select({})", type_constraint_str(s.product)).to_string(), // TODO variant key
    &Selector::SelectDependencies(ref s) => format!("{}({}, {}, {}field_types=({},))",
                                                   "SelectDependencies",
                                                    type_constraint_str(s.product),
                                                    type_constraint_str(s.dep_product),
                                                    if s.field == "dependencies" { "".to_string() } else {format!("'{}', ", s.field)},
                                                    s.field_types.iter()
                                                                 .map(|&f| type_str(f))
                                                                 .collect::<Vec<String>>()
                                                                 .join(", ")
    ),
    &Selector::SelectTransitive(ref s) => format!("{}({}, {}, {}field_types=({},))",
                                                   "SelectTransitive",
                                                    type_constraint_str(s.product),
                                                    type_constraint_str(s.dep_product),
                                                    if s.field == "dependencies" { "".to_string() } else {format!("'{}', ", s.field)},
                                                    s.field_types.iter()
                                                                 .map(|&f| type_str(f))
                                                                 .collect::<Vec<String>>()
                                                                 .join(", ")
    ),
    &Selector::SelectProjection(ref s) => format!("SelectProjection({}, {}, '{}', {})",
                                                  type_constraint_str(s.product),
                                                  type_str(s.projected_subject),
                                                  s.field,
                                                  type_constraint_str(s.input_product),
    ),
  }
}

fn entry_str(entry: &Entry) -> String {
  match entry {
    &Entry::InnerEntry(ref inner) => {
      format!("{} of {}", task_display(&inner.rule), type_str(inner.subject_type))
    }
    &Entry::Root(ref root) => {
      format!("{} for {}",
             root.clause.iter().map(|s| selector_str(s)).collect::<Vec<_>>().join(", "),
             type_str(root.subject_type))
    }
    &Entry::SubjectIsProduct { subject_type } => {
      format!("SubjectIsProduct({})", type_str(subject_type))
    }
    &Entry::Singleton { ref value, product } => {
      format!("Singleton({}, {})", externs::key_to_str(value), type_constraint_str(product))
    }
    &Entry::Unreachable { ref rule, ref reason } => {
      format!("Unreachable({}, {:?})", task_display(rule), reason)
    }
  }
}

fn task_display(task: &Task) -> String {
  let product = type_constraint_str(task.product);
  let mut clause_portion = task.clause.iter().map(|c| selector_str(c)).collect::<Vec<_>>().join(", ");
  if task.clause.len() <= 1 {
    clause_portion = format!("({},)", clause_portion)
  } else {
    clause_portion = format!("({})", clause_portion)
  }
  let function_name = function_str(&&task.func);
  format!("({}, {}, {})", product, clause_portion, function_name).to_string()
}

impl RuleGraph {
  pub fn new(tasks: &Tasks, root_subject_types: Vec<TypeId>) -> RuleGraph {
    let maker = GraphMaker::new(tasks, root_subject_types);

    maker.full_graph()
  }

  pub fn find_root_edges(&self, subject_type: TypeId, selector: Selector) -> Option<RuleEdges> { // TODO return Result instead
    let root = RootEntry { subject_type: subject_type, clause: vec![selector] };
    self.root_dependencies.get(&root).map(|e|e.clone())
  }

  pub fn task_for_inner(&self, entry: &Entry) -> Task {
    if let &Entry::InnerEntry(ref inner) = entry {
      inner.rule.clone()
    } else {
      panic!("not an inner entry! {:?}", entry)
    }
  }

  pub fn edges_for_inner(&self, entry: &Entry) -> Option<RuleEdges> {
    if let &Entry::InnerEntry(ref inner) = entry {
      self.edges_for_inner_entry(inner)
    } else {
      panic!("not an inner entry! {:?}", entry)
    }
  }

  pub fn edges_for_inner_entry(&self, inner_entry: &InnerEntry) -> Option<RuleEdges> {
    self.rule_dependency_edges.get(inner_entry).map(|e| e.clone())
  }

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
        &Entry::InnerEntry(InnerEntry {ref rule, ..}) |
        &Entry::Unreachable {ref rule, ..} => {
          if used_rules.contains(&rule) {
            continue
          }
          for d in diagnostics {
            let mut msg_to_type = collated_errors.entry(rule.clone())
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

    format!("Rules with errors: {}\n  {}", msgs.len(), msgs.join("\n  ")).to_string()
  }

  fn has_errors(&self) -> bool {
    let used_rules: HashSet<_> = self.rule_dependency_edges.keys().map(|entry| &entry.rule).collect();
    self.unfulfillable_rules.iter().any(|(&ref entry, &ref diagnostics)| match entry {
      &Entry::InnerEntry(ref inner) => !used_rules.contains(&inner.rule) &&
                                       !diagnostics.is_empty(),
      &Entry::Unreachable { .. } => true,
      _ => false,
    })
  }

  // TODO instead of this, make own fmt thing that accepts externs
  pub fn visualize(&self, f: &mut io::Write) -> io::Result<()> {
    if self.root_dependencies.is_empty() && self.rule_dependency_edges.is_empty() {
      write!(f, "digraph {{\n")?;
      write!(f, "  // empty graph\n")?;
      return write!(f, "}}");
    }


    let mut root_subject_type_strs = self.root_subject_types.iter()
      .map(|&t| type_str(t))
      .collect::<Vec<String>>();
    root_subject_type_strs.sort();
    write!(f, "digraph {{\n")?;
    write!(f, "  // root subject types: {}\n", root_subject_type_strs.join(", "))?;
    write!(f, "  // root entries\n")?;
    let mut root_rule_strs = self.root_dependencies.iter()
      .map(|(k, deps)| {
        let root_str = entry_str(&Entry::from(k.clone()));
        format!("    \"{}\" [color=blue]\n    \"{}\" -> {{{}}}",
                root_str,
                root_str,
                deps.dependencies.iter()
                  .map(|d| format!("\"{}\"", entry_str(d)))
                  .collect::<Vec<String>>()
                  .join(" "))
      })
      .collect::<Vec<String>>();
    root_rule_strs.sort();
    write!(f, "{}\n", root_rule_strs.join("\n"))?;


    write!(f, "  // internal entries\n")?;
    let mut internal_rule_strs = self.rule_dependency_edges.iter()
      .map(|(k, deps)| format!("    \"{}\" -> {{{}}}", entry_str(&Entry::from(k.clone())), deps.dependencies.iter()
        .map(|d| format!("\"{}\"", entry_str(d)))
        .collect::<Vec<String>>()
        .join(" ")))
      .collect::<Vec<String>>();
    internal_rule_strs.sort();
    write!(f, "{}\n", internal_rule_strs.join("\n"))?;
    write!(f, "}}")
  }
}

#[derive(Eq, PartialEq, Clone, Debug)]
pub struct RuleEdges {
  dependencies: Entries,
  dependencies_by_select_key: HashMap<SelectKey, Entries>
}


impl RuleEdges {

  pub fn new() -> RuleEdges {
    RuleEdges {
      dependencies: vec![],
      dependencies_by_select_key: HashMap::new()
    }
  }

  pub fn entries_for(&self, select_key: &SelectKey) -> Entries {
    self.dependencies_by_select_key.get(select_key).cloned().unwrap_or_else(|| Vec::new())
  }

  pub fn is_empty(&self) -> bool {
    self.dependencies.is_empty()
  }

  fn add_edges_via(&mut self, select_key: SelectKey, new_dependencies: &Entries) {
    if SelectKey::Nothing == select_key && !new_dependencies.is_empty() {
      panic!("Cannot specify a None selector with non-empty dependencies!")
    }
    let mut deps_for_selector = self.dependencies_by_select_key.entry(select_key).or_insert(vec![]);
    for d in new_dependencies {
      if !deps_for_selector.contains(d) {
        deps_for_selector.push(d.clone());
      }
      if !self.dependencies.contains(d) {
        self.dependencies.push(d.clone());
      }
    }
  }

  fn has_edges_for(&self, select_key: &SelectKey) -> bool {
    self.dependencies_by_select_key.contains_key(select_key)
  }

  fn makes_unfulfillable(&self, dep_to_eliminate: &Entry) -> bool {
    // Returns true if removing dep_to_eliminate makes this set of edges unfulfillable.
    if self.dependencies.len() == 1 && &self.dependencies[0] == dep_to_eliminate {
      true
    } else if self.dependencies_by_select_key.values().any(|deps| deps.len() == 1 && &deps[0] == dep_to_eliminate) {
      true
    } else {
      false
    }
  }

  fn remove_rule(&mut self, dep: &Entry) {
    self.dependencies.retain(|d| d != dep);
    for (_, deps) in self.dependencies_by_select_key.iter_mut() {
      deps.retain(|d| d != dep);
    }
  }
}

fn update_edges_based_on_unfulfillable_entry<K>(edge_container: &mut HashMap<K, RuleEdges>,
                                                new_unfulfillable_rules: &mut UnfulfillableRuleMap,
                                                removal_traversal: &mut VecDeque<Entry>,
                                                unfulfillable_entry: &Entry
)
  where Entry: From<K>,
        K: Eq + Hash + Clone + fmt::Debug
{
  let keys: Vec<_> = edge_container.keys()
    .cloned()
    .collect();

  for current_entry in keys {
    if let hash_map::Entry::Occupied(mut o) = edge_container.entry(current_entry) {
      if new_unfulfillable_rules.contains_key(&Entry::from(o.key().clone())) {
        o.remove();
      } else if o.get().makes_unfulfillable(&unfulfillable_entry) {
        let key_entry = Entry::from(o.key().clone());

        let entry_subject = key_entry.subject_type();
        let mut diagnostics = new_unfulfillable_rules.entry(key_entry.clone()).or_insert(vec![]);
        diagnostics.push(Diagnostic {
          subject_type: entry_subject,
          reason: format!("depends on unfulfillable {}", entry_str(unfulfillable_entry))
        });

        removal_traversal.push_back(key_entry.clone());

        o.remove();
      } else {
        o.get_mut().remove_rule(&unfulfillable_entry);
      }
    }
  }
}

fn rhs_for_select(tasks: &Tasks, subject_type: TypeId, select: &Select) -> Entries {
  if externs::satisfied_by_type(&select.product, &subject_type) {
    // NB a matching subject is always picked first
    vec![Entry::new_subject_is_product(subject_type)]
  } else if let Some(&(ref key, _)) = tasks.gen_singleton(&select.product) {
    vec![Entry::new_singleton(key.clone(), select.product.clone())]
  } else {
    match tasks.gen_tasks(&select.product) {
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
                      select_key: SelectKey,
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
      .cloned();
    rules_to_traverse.extend(unseen_dep_rules);
  }
  match entry {
    &Entry::Root(ref root_entry) => {
      let mut edges = root_rule_dependency_edges.entry(root_entry.clone()).or_insert(RuleEdges::new());
      edges.add_edges_via(select_key, &dep_rules);
    },
    &Entry::InnerEntry(ref inner_entry) => {
      let mut edges = rule_dependency_edges.entry(inner_entry.clone()).or_insert(RuleEdges::new());
      if edges.has_edges_for(&select_key) {
        // This is an error that should only happen if there's a bug in the algorithm, but it
        // might make sense to expose it in a more friendly way.
        panic!("Rule {:?} already has dependencies set for selector {:?}", entry, select_key)
      }
      edges.add_edges_via(select_key, &dep_rules);
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
            subject_types.iter().map(|&t| type_str(t)).collect::<Vec<String>>().join(", "))
  ).collect();
  errors.sort();
  format!("{}:\n    {}", task_display(rule), errors.join("\n    "))
}
