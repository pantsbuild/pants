// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use core::TypeId;
use core::Value;
use core::TypeConstraint;
use nodes::Node;

use selectors::{Selector, Task};
use std::collections::HashMap;
use std::collections::HashSet;
use std::collections::VecDeque;
use std::fmt::Debug;
use tasks::Tasks;

// options.
// 1. carefully box everything
// 2. have a struct with optional fields

// arg! I want to have a vec of RootEntry u InternalEntry
// might be able to do it with boxing
// ah, yep that's it
// So, I need a trait
// enum doesn't do it because all of the variants of an enum are typed with the enum

// a rule graph entry is
// the below would allow preventing all of the awkward boxing
#[derive(Eq, Hash, PartialEq, Clone, Debug)]
enum EntryType {
  SubjectIsProduct,
  Root,
  InnerEntry,
  Literal,
  // NB unreachable is an error type, it might be better to name it error
  Unreachable
}
#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct Entry {
  entry_type: EntryType,

  // SubjectIsProduct
  // can be
  // - dependency
  subject_type: Option<TypeId>,

  // Literal
  // can be
  // - dependency
 // value: Option<Value>, // probably

  // Inner
  // can
  // - be dependency
  // - have dependencies
  //subject_type: TypeId,
  rule: Option<Task>,

  // Root
  // can
  // - have dependencies
  //subject_type: TypeId,
  selector: Option<TypeConstraint>,

  // Unreachable
  reason: Option<Diagnostic>
}

impl Entry {
  fn new_root(subject_type: TypeId, selector: TypeConstraint) -> Entry {
    Entry {
      entry_type: EntryType::Root,
      subject_type: Some(subject_type),
      //value: None,
      rule: None,
      selector: Some(selector),
      reason: None,
    }
  }

  fn new_inner(subject_type: TypeId, rule: &Task) -> Entry {
    Entry {
      entry_type: EntryType::InnerEntry,
      subject_type: Some(subject_type),
      //value: None,
      rule: Some(rule.clone()), // TODO clone, really?
      selector: None,
      reason: None,
    }
  }

  fn new_subject_is_product(subject_type: TypeId) -> Entry {
    Entry {
      entry_type: EntryType::SubjectIsProduct,
      subject_type: Some(subject_type),
      //value: None,
      rule: None,
      selector: None,
      reason: None,
    }
  }

  fn new_unreachable(rule: &Task) -> Entry {
    Entry {
      entry_type: EntryType::SubjectIsProduct,
      subject_type: None,
      //value: None,
      rule: Some(rule.clone()), // TODO clone vs lifetimes
      selector: None,
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
    match self.rule {
      Some(ref task) => task.clause.clone(),
      None => vec![] // or panic?
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


trait RuleGraphEntry: Debug + Sized {
  fn rule(&self) -> &Task;
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct RootEntry {
  pub rule: Task,
  pub subject_type: TypeId,
  pub product_constraint: TypeConstraint
}

impl RuleGraphEntry for RootEntry {
  fn rule(&self) -> &Task {
    &self.rule
  }
}


#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct InternalEntry {
  pub rule: Task
}

impl RuleGraphEntry for InternalEntry {
  fn rule(&self) -> &Task {
    &self.rule
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct RuleGraphSubjectIsProduct {
  subject_type: TypeId
}

impl RuleGraphEntry for RuleGraphSubjectIsProduct {
  // has no rule, but is a RuleGraphEntry
  fn rule(&self) -> &Task {
    unimplemented!()
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

  fn new_graph_from_existing(&self, root_subject_type: TypeId/*I think*/,
                             root_selector: Selector,
                             existing_graph: RuleGraph) -> RuleGraph {
    RuleGraph::new()
  }
  fn generate_subgraph(&self,
                       root_subject: Value,
                       requested_product: TypeId/*might be type constraint instead*/) -> RuleGraph {
    RuleGraph::new()
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
      // can't do this because can't have a heterogeneous collection w/o wrapping w/ boxen
      //full_unfulfillable_rules.insert(UnreachableRule {rule: rule }, vec![Diagnostic{msg: "Unreachable"}]);
      println!("an unreachable rule!");
    }

    RuleGraph::new()
  }

  fn _construct_graph(&self,
                      beginning_rule: Entry, // Root Entry
                      root_rule_dependency_edges: RootRuleDependencyEdges,
                      rule_dependency_edges: RuleDependencyEdges,
                      unfulfillable_rules: UnfulfillableRuleMap) -> RuleGraph {

    fn rhs_for_select(tasks: &Tasks, subject_type: TypeId, selector: Selector) -> Entries {
      // technically, selector here is always a Select. I could adapt ^^ to ensure that

      //let subject_type = TypeConstraint(subject_type.0);

      if tasks.externs.satisfied_by(&selector.product(), &subject_type) {
        vec![ Entry::new_subject_is_product(subject_type)]
      } else {
        match tasks.gen_tasks(&subject_type, &selector.product()) {
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

    fn mark_unfulfillable(mut unfulfillable_rules: UnfulfillableRuleMap, entry: Entry, subject_type: TypeId, reason: &str) {
      // instead of being modifiable, this could return a UnfulfillableRuleMap that then gets merged.
      let mut diagnostics_for_entry = unfulfillable_rules.entry(entry).or_insert(vec![]);
      diagnostics_for_entry.push(Diagnostic { subject_type: subject_type, reason: reason.to_string() });
    }


    fn add_rules_to_graph(mut rules_to_traverse: VecDeque<Entry>,
                          rule_dependency_edges: &mut RuleDependencyEdges,
                          unfulfillable_rules: &UnfulfillableRuleMap,
                          root_rule_dependency_edges: &mut RootRuleDependencyEdges,
                          entry: Entry,
                          selector_path: Vec<Selector>,
                          dep_rules: Entries) {
      /*
  unseen_dep_rules = [g for g in dep_rules
                      if g not in rule_dependency_edges and
                      g not in unfulfillable_rules and
                      g not in root_rule_dependency_edges]
  rules_to_traverse.extend(unseen_dep_rules)
  if type(rule) is RootEntry:
*/
      {
        // immutable lookup ref
        let root_rule_deps: &RootRuleDependencyEdges = root_rule_dependency_edges;
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
          /*
                    if rule in root_rule_dependency_edges:
            root_rule_dependency_edges[rule].add_edges_via(selector_path, dep_rules)
          else:
            new_edges = RuleEdges()
            new_edges.add_edges_via(selector_path, dep_rules)
            root_rule_dependency_edges[rule] = new_edges

*/
          let mut edges = root_rule_dependency_edges.entry(entry).or_insert(RuleEdges::new());
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
/*
        elif rule not in rule_dependency_edges:
          new_edges = RuleEdges()
          new_edges.add_edges_via(selector_path, dep_rules)
          rule_dependency_edges[rule] = new_edges
        else:
          existing_deps = rule_dependency_edges[rule]
          if existing_deps.has_edges_for(selector_path):
            raise ValueError("rule {} already has dependencies set for selector {}"
                             .format(rule, selector_path))

          existing_deps.add_edges_via(selector_path, dep_rules)
*/
        }
      }
    }
/*
    rules_to_traverse = deque([beginning_rule])
    root_rule_dependency_edges = dict() if root_rule_dependency_edges is None else root_rule_dependency_edges
    rule_dependency_edges = dict() if rule_dependency_edges is None else rule_dependency_edges
    unfulfillable_rules = dict() if unfulfillable_rules is None else unfulfillable_rules
    */
    let mut traversal_ct = 0;
    let mut rules_to_traverse: VecDeque<Entry> = VecDeque::new();
    rules_to_traverse.push_back(beginning_rule);
    while let Some(entry) = rules_to_traverse.pop_front() {
      traversal_ct += 1;
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
        let rules_or_literals_for_selector = rhs_for_select(&self.tasks, entry.subject_type(), selector);
      }

    }
    /*
while rules_to_traverse:
  entry = rules_to_traverse.popleft()
  if isinstance(entry, CanBeDependency) and not isinstance(entry, CanHaveDependencies):
    continue
  if not isinstance(entry, CanHaveDependencies):
    raise TypeError("Cannot determine dependencies of entry not of type CanHaveDependencies: {}"
                    .format(entry))
  if entry in unfulfillable_rules:
    continue

  if entry in rule_dependency_edges:
    continue

  was_unfulfillable = False

  for selector in entry.input_selectors:
    if type(selector) in (Select, SelectVariant):
      # TODO, handle the Addresses / Variants case
      rules_or_literals_for_selector = _find_rhs_for_select(entry.subject_type, selector)
      if not rules_or_literals_for_selector:
        mark_unfulfillable(entry, entry.subject_type, 'no matches for {}'.format(selector))
        was_unfulfillable = True
        continue
      add_rules_to_graph(entry, selector, rules_or_literals_for_selector)
    elif type(selector) is SelectLiteral:
      add_rules_to_graph(entry,
                         selector,
                         (RuleGraphLiteral(selector.subject, selector.product),))
    elif type(selector) is SelectDependencies:
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
    elif type(selector) is SelectProjection:
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
    else:
      raise TypeError('Unexpected type of selector: {}'.format(selector))

  if type(entry.rule) is SnapshottedProcess:
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


  if not was_unfulfillable:
    # NB: In this case, there are no selectors.
    add_rules_to_graph(entry, None, tuple())

return root_rule_dependency_edges, rule_dependency_edges, unfulfillable_rules
*/

    RuleGraph::new()
  }

  fn _remove_unfulfillable_rules_and_dependents(&self,
                                                root_rule_dependency_edges: RootRuleDependencyEdges,
                                                rule_dependency_edges: RuleDependencyEdges,
                                                unfulfillable_rules: UnfulfillableRuleMap) -> RuleGraph {
    RuleGraph::new()
  }

  fn gen_root_entries(&self, product_types: &Vec<TypeConstraint>) -> Entries {
    let mut result: Entries = Vec::new();
    for subj_type in self.root_subject_types.subject_types {
      for pt in product_types {
        if let Some(tasks) = self.tasks.gen_tasks(subj_type, pt) {
          let mapped_tasks: Entries = tasks.iter().map(|t|
            Entry::new_root(
              subj_type.clone(),
              TypeConstraint(pt.0)
          )).collect();
          result.extend(mapped_tasks);
        }
      }
    }
    result
  }
}

// entry types
// lhs--CanHaveDependencies, rhs--CanBeDependencies
// - subject is product - rhs only
// - literal - rhs only
// - task - lhs and rhs
// - root - lhs only

// unreachable rule {rule}

#[derive(Debug)]
pub struct RuleGraph {
  // graph_maker
  // root_subject_types
  // rule_dependencies: Map<Entrys -> Edges> edges by entries
  // unfulfillable_rules: Map<entries -> list<UnfulfillableReason>>
  root_dependencies: RootRuleDependencyEdges,
  rule_dependency_edges: RuleDependencyEdges,
  unfulfillable_rules: UnfulfillableRuleMap,
}

impl RuleGraph {
  pub fn new() -> RuleGraph {
    RuleGraph {
      root_dependencies: HashMap::new(),
      rule_dependency_edges: HashMap::new(),
      unfulfillable_rules: HashMap::new()
    }
  }

  pub fn has_errors(&self) -> bool {
    false
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct RuleEdges {
  /*current_node: Node,

  current_node_is_rule_holder: bool,
  // the only node type in the branch w/o a rule is the RootNode RN, so
  // this may not be necessary
  will_noop: bool,
  noop_reason: String,

  //edges -> dependencies defined by rule graph
  // points to list of rules by selector-key
  // selector key is a 1 or 2 element sequence of the form (selector, ....)
  //   one element selectors are bare selectors without a projection
  //   two element selectors are projected selectors that change the subject
  //   could come up with a different scheme tho
  */
  dependencies: Entries,
  //selector_to_dependencies: HashMap<Vec<Selector>, Entries> // TODO fix typecheck here
}

impl RuleEdges {

  fn new() -> RuleEdges {
    RuleEdges {
      dependencies: vec![],
    //  selector_to_dependencies: HashMap::new()
    }
  }
  pub fn add_edges_via(&mut self, selector: Vec<Selector>, new_dependencies: &Entries) {}
  pub fn has_edges_for(&self, selector: Vec<Selector>) -> bool {
    false
  }
  pub fn initial_state_for_selector() {}

  //  pub fn get_state_for_selector(selector: Selector, subject: Blah, variants: Blah, get_state: Blah) {
  //
  //}
}