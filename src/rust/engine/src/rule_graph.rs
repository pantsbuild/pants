// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use core::{Key, TypeConstraint, TypeId};

use selectors::{Select, Selector, Task};

use std::collections::HashMap;
use std::collections::HashSet;
use std::collections::VecDeque;

use tasks::Tasks;

// I think I ought to be able to replace the below with a set of structs keyed by EntryType.
// My first couple attempts failed.
#[derive(Eq, Hash, PartialEq, Clone, Debug)]
enum EntryType {
  SubjectIsProduct,
  // has subject_type
  // can be dependency

  Root,
  // has subject_type, selector/typeconstriant
  // can have dependencies

  InnerEntry,
  // has subject_type, rule
  // can be dependency
  // can have dependencies

  Literal,
  // has value
  // can be dependency

  Unreachable
  // has a reason for the failure and a rule
  // NB: unreachable is an error type, it might be better to name it error, but currently
  //     unreachable is the only error entry type.
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct Entry {
  entry_type: EntryType,
  subject_type: Option<TypeId>,
  value: Option<Key>,
  rule: Option<Task>,
  selector: Option<TypeConstraint>,
  reason: Option<Diagnostic>
}

impl Entry {
  fn new_root(subject_type: TypeId, selector: TypeConstraint) -> Entry {
    Entry {
      entry_type: EntryType::Root,
      subject_type: Some(subject_type),
      value: None,
      rule: None,
      selector: Some(selector),
      reason: None,
    }
  }

  fn new_inner(subject_type: TypeId, rule: &Task) -> Entry {
    Entry {
      entry_type: EntryType::InnerEntry,
      subject_type: Some(subject_type),
      value: None,
      rule: Some(rule.clone()), // TODO decide on clone vs lifetimes
      selector: None,
      reason: None,
    }
  }

  fn new_subject_is_product(subject_type: TypeId) -> Entry {
    Entry {
      entry_type: EntryType::SubjectIsProduct,
      subject_type: Some(subject_type),
      value: None,
      rule: None,
      selector: None,
      reason: None,
    }
  }

  fn new_unreachable(rule: &Task) -> Entry {
    Entry {
      entry_type: EntryType::Unreachable,
      subject_type: None,
      value: None,
      rule: Some(rule.clone()), // TODO decide on clone vs lifetimes
      selector: None,
      reason: None,
    }
  }
  fn new_literal(value: Key, product: TypeConstraint) -> Entry {
    Entry {
      entry_type: EntryType::Literal,
      subject_type: None,
      value: Some(value),
      rule: None,
      selector: Some(product),
      reason: None,
    }
  }

  fn subject_type(&self) -> TypeId {
    if let Some(subject_type) = self.subject_type {
      subject_type
    } else {
      panic!("no subject type")
    }
  }

  fn rule(&self) -> &Task {
    if let Some(ref rule) = self.rule {
      rule
    } else {
      panic!("no rule")
    }
  }
  fn input_selectors(&self) -> Vec<Selector> {
    match self.entry_type {
      EntryType::InnerEntry =>
        match self.rule {
          Some(ref task) => {
            task.clause.clone()
          },
          None => vec![] // Could also panic
        },
      EntryType::Root => match self.selector {
        Some(s) => vec![Selector::Select(Select { product: s, variant_key: None })],
        None => vec![]
      },
      _ => panic!("this entry doesn't have selectors")
    }
  }

  fn can_have_dependencies(&self) -> bool {
    match self.entry_type {
      EntryType::SubjectIsProduct => false,
      EntryType::Literal => false,
      EntryType::InnerEntry => true,
      EntryType::Root => true,
      EntryType::Unreachable => false,
    }
  }
  fn can_be_dependency(&self) -> bool {
    match self.entry_type {
      EntryType::SubjectIsProduct => true,
      EntryType::Literal => true,
      EntryType::InnerEntry => true,
      EntryType::Root => false,
      EntryType::Unreachable => false,
    }
  }
}

type Entries = Vec<Entry>;
type RootRuleDependencyEdges = HashMap<Entry, RuleEdges>; // Root -> InternalEntry
type Rule = Task;
type RuleDependencyEdges = HashMap<Entry, RuleEdges>; // InternalEntry -> InternalEntry
type RuleDiagnostics = Vec<Diagnostic>;
type UnfulfillableRuleMap = HashMap<Entry, RuleDiagnostics>;

#[derive(Debug)]
pub struct RootSubjectTypes<'a> {
  pub subject_types: &'a Vec<TypeId>
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct Diagnostic {
  subject_type: TypeId,
  reason: String
}

/*
 * Given the task index and the root subjects, it produces a rule graph that allows dependency nodes
 * to be found statically rather than dynamically.
 */
pub struct GraphMaker<'a> {
    tasks: Tasks,
    root_subject_types: RootSubjectTypes<'a>
}

impl<'a> GraphMaker<'a> {
  pub fn new(tasks: &Tasks, root_subject_types: RootSubjectTypes<'a>) -> GraphMaker<'a> {
    let cloned_tasks = tasks.clone();
    GraphMaker { tasks: cloned_tasks, root_subject_types: root_subject_types }
  }

  pub fn full_graph(&self) -> RuleGraph {
    let mut full_root_rule_dependency_edges: RootRuleDependencyEdges = HashMap::new();
    let mut full_dependency_edges: RuleDependencyEdges = HashMap::new();
    let mut full_unfulfillable_rules: UnfulfillableRuleMap = HashMap::new();
    // for root_subj_type, selectorfn in root_subj_selector_fn.items():...

    //let product_types = self.tasks.all_product_types(&beginning_root.subject_type);
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
    let rules_in_graph: HashSet<Task> = full_dependency_edges.keys().map(|f| f.rule().clone()).collect();
    let unfulfillable_discovered_during_construction: HashSet<Task> = full_unfulfillable_rules.keys().map(|f| f.rule().clone()).collect();
    let declared_rules = self.tasks.all_rules();
    let unreachable_rules: HashSet<&Task> = declared_rules.iter()
      .filter(|r| !rules_in_graph.contains(r))
      .filter(|r| !unfulfillable_discovered_during_construction.contains(r))
      .filter(|r| !self.tasks.is_singleton_task(r))
      .filter(|r| !self.tasks.is_intrinsic_task(r))
      .collect();

    for rule in unreachable_rules {
      let diagnostics = full_unfulfillable_rules.entry(Entry::new_unreachable(rule)).or_insert(vec![]);
      let terrible_type = TypeId(0); // need to come up with something better.
      // This is used to collate the error messages by subject. It could use either a well known
      // special value or I could make the subject type an option and use None here.

      diagnostics.push(Diagnostic{subject_type: terrible_type, reason:"Unreachable".to_string()});
    }

    RuleGraph {
      root_dependencies: full_root_rule_dependency_edges,
      rule_dependency_edges: full_dependency_edges,
      unfulfillable_rules: full_unfulfillable_rules
    }
  }

  fn _construct_graph(&self,
                      beginning_rule: Entry, // Root Entry
                      mut root_rule_dependency_edges: RootRuleDependencyEdges,
                      mut rule_dependency_edges: RuleDependencyEdges,
                      mut unfulfillable_rules: UnfulfillableRuleMap) -> RuleGraph {

    fn rhs_for_select(tasks: &Tasks, subject_type: TypeId, select: &Select) -> Entries {
      // technically, selector here is always a Select. I could adapt ^^ to ensure that

      //let subject_type = TypeConstraint(subject_type.0);

      if tasks.externs.satisfied_by(&select.product, &subject_type) {
        vec![ Entry::new_subject_is_product(subject_type)]
      } else {
        match tasks.gen_tasks(&subject_type, &select.product) {
          Some(ref matching_tasks) => {
            matching_tasks.iter().map(|t| Entry::new_inner(subject_type, t) ).collect()
          }
          None => vec![]
        }
      }
      /*
      if selector.type_constraint.satisfied_by_type(subject_type):
        # NB a matching subject is always picked first
        return (RuleGraphSubjectIsProduct(subject_type),)
      else:
        return tuple(InternalEntry(subject_type, rule)
                     for rule in self.rule_index.gen_rules(subject_type, selector.product))
      */
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
          .filter(|g| !rule_deps.contains_key(g))
          .filter(|g| !unfulfillable_rules.contains_key(g))
          .filter(|g| !root_rule_dependency_edges.contains_key(g))
          .map(|g| g.clone());
        for unseen_rule in unseen_dep_rules {
          rules_to_traverse.push_back(unseen_rule);
        }
      }
      match entry.entry_type {
        EntryType::Root => {
          let mut edges = root_rule_dependency_edges.entry(entry.clone()).or_insert(RuleEdges::new());
          edges.add_edges_via(selector_path, &dep_rules);
        },
        _ => {
          let mut edges = rule_dependency_edges.entry(entry.clone()).or_insert(RuleEdges::new());
          if edges.has_edges_for(selector_path.clone()) {
            // This is an error that should only happen if there's a bug in the algorithm, but it
            // might make sense to expose it in a more friendly way.
            panic!("Rule {:?} already has dependencies set for selector {:?}", entry, selector_path)
          }
          edges.add_edges_via(selector_path, &dep_rules);
        }
      }
    }

    let mut rules_to_traverse: VecDeque<Entry> = VecDeque::new();
    rules_to_traverse.push_back(beginning_rule);
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
      if rule_dependency_edges.contains_key(&entry) {
        continue
      }
      let mut was_unfulfillable = false;
      for selector in entry.input_selectors() {
        match selector {
          Selector::Select(select) =>{
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
              continue
            }
            add_rules_to_graph(&mut rules_to_traverse,
                               &mut rule_dependency_edges,
                               &mut unfulfillable_rules,
                               &mut root_rule_dependency_edges,
                               &entry,
                               vec![Selector::Select(select)],
                               rules_or_literals_for_selector);
          },
          Selector::SelectLiteral(select) =>{
            add_rules_to_graph(&mut rules_to_traverse,
                               &mut rule_dependency_edges,
                               &mut unfulfillable_rules,
                               &mut root_rule_dependency_edges,
                               &entry,
                               vec![Selector::SelectLiteral(select.clone())],
                               vec![Entry::new_literal(select.subject.clone(),
                                                       select.product.clone())]);


          },
          Selector::SelectDependencies(select) => {
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
              continue
            }
            //let mut rules_for_dependencies = vec![];
            // TODO port the rest of this after adding field types to the selectors

            /*
                  initial_selector = selector.input_product_selector
      initial_rules_or_literals = _find_rhs_for_select(entry.subject_type, initial_selector)
      if not initial_rules_or_literals:
        mark_unfulfillable(entry,
                           entry.subject_type,
                           'no matches for {} when resolving {}'
                           .format(initial_selector, selector))
        was_unfulfillable = True
        continue

      rules_for_dependencies = []
      for field_type in selector.field_types:
        rules_for_field_subjects = _find_rhs_for_select(field_type,
                                                        selector.projected_product_selector)
        rules_for_dependencies.extend(rules_for_field_subjects)

      if not rules_for_dependencies:
        mark_unfulfillable(entry,
                           selector.field_types,
                           'no matches for {} when resolving {}'
                           .format(selector.projected_product_selector, selector))
        was_unfulfillable = True
        continue

      add_rules_to_graph(entry,
                         (selector, selector.input_product_selector),
                         initial_rules_or_literals)
      add_rules_to_graph(entry,
                         (selector, selector.projected_product_selector),
                         tuple(rules_for_dependencies))
                         */

          },
          Selector::SelectProjection(select) =>{
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
            /*
                  # TODO, could validate that input product has fields
      initial_rules_or_literals = _find_rhs_for_select(entry.subject_type,
                                                       selector.input_product_selector)
      if not initial_rules_or_literals:
        mark_unfulfillable(entry,
                           entry.subject_type,
                           'no matches for {} when resolving {}'
                           .format(selector.input_product_selector, selector))
        was_unfulfillable = True
        continue

      projected_rules = _find_rhs_for_select(selector.projected_subject,
                                             selector.projected_product_selector)
      if not projected_rules:
        mark_unfulfillable(entry,
                           selector.projected_subject,
                           'no matches for {} when resolving {}'
                           .format(selector.projected_product_selector, selector))
        was_unfulfillable = True
        continue

      add_rules_to_graph(entry,
                         (selector, selector.input_product_selector),
                         initial_rules_or_literals)
      add_rules_to_graph(entry,
                         (selector, selector.projected_product_selector),
                         projected_rules)
            */

          },
          Selector::Task(select) =>{
            // TODO, not sure what task is in this context exactly
            panic!("Unexpected type of selector: {:?}", select)
            /*raise TypeError('Unexpected type of selector: {}'.format(selector))*/
          }
        }
      }

      // if rule is a snapshot rule
      /*
          # TODO, this is a copy of the SelectDependencies with some changes
    # Need to come up with a better approach here, but this fixes things
    # It's also not tested explicitly.
    snapshot_selector = entry.rule.snapshot_selector
    initial_selector = entry.rule.snapshot_selector.input_product_selector
    initial_rules_or_literals = _find_rhs_for_select(SnapshottedProcessRequest, initial_selector)
    if not initial_rules_or_literals:
      mark_unfulfillable(entry,
                         entry.subject_type,
                         'no matches for {} when resolving {}'
                         .format(initial_selector, snapshot_selector))
      was_unfulfillable = True
    else:

      rules_for_dependencies = []
      for field_type in snapshot_selector.field_types:
        rules_for_field_subjects = _find_rhs_for_select(field_type,
                                                        snapshot_selector.projected_product_selector)
        rules_for_dependencies.extend(rules_for_field_subjects)

      if not rules_for_dependencies:
        mark_unfulfillable(entry,
                           snapshot_selector.field_types,
                           'no matches for {} when resolving {}'
                           .format(snapshot_selector.projected_product_selector, snapshot_selector))
        was_unfulfillable = True
      else:
        add_rules_to_graph(entry,
                           (snapshot_selector, snapshot_selector.input_product_selector),
                           initial_rules_or_literals)
        add_rules_to_graph(entry,
                           (snapshot_selector, snapshot_selector.projected_product_selector),
                           tuple(rules_for_dependencies))
      */
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
                                                rule_graph: RuleGraph) -> RuleGraph {
    // TODO port this portion
    rule_graph
  }

  fn gen_root_entries(&self, product_types: &Vec<TypeConstraint>) -> Entries {
    let mut result: Entries = Vec::new();
    for subj_type in self.root_subject_types.subject_types {
      for pt in product_types {
        if let Some(tasks) = self.tasks.gen_tasks(subj_type, pt) {
          if !tasks.is_empty() {
            result.push(Entry::new_root(
              subj_type.clone(),
              TypeConstraint(pt.0)));
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
  pub fn has_errors(&self) -> bool {
    // self.unfulfillable_rules.iter().any(|kv| kv.0.entry_type != EntryType::Root && !kv.1.is_empty())
    false
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
      // TODO replace clones with lifetimes
      deps_for_selector.push(d.clone());
      self.dependencies.push(d.clone());
    }
  }

  fn has_edges_for(&self, selector_path: Vec<Selector>) -> bool {
    self.selector_to_dependencies.contains_key(&selector_path)
  }
}