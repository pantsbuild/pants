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

// arg! I want to have a vec of RootEntry u InternalEntry
// might be able to do it with boxing
// ah, yep that's it
// So, I need a trait
// enum doesn't do it because all of the variants of an enum are typed with the enum

trait RuleGraphEntry: Debug {
  fn rule(&self) -> &Task;
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct RootEntry {
  pub rule: Task,
  pub subject_type: TypeId,
  pub product_constraint: TypeConstraint
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
struct InternalEntry {
  pub rule: Task,
  pub is_root: bool
}

impl RuleGraphEntry for RootEntry {
  fn rule(&self) -> &Task {
    &self.rule
  }
}

impl RuleGraphEntry for InternalEntry {
  fn rule(&self) -> &Task {
    &self.rule
  }
}

type RootRuleDependencyEdges = HashMap<InternalEntry, Vec<RootEntry>>;
type Rule = Task;
type RuleDependencyEdges = HashMap<InternalEntry, Vec<InternalEntry>>;
type UnfillableRules = Vec<InternalEntry>;
type UnfillableRuleMap = HashMap<InternalEntry, UnfillableRules>;

#[derive(Debug)]
pub struct RootSubjectTypes<'a> {
  pub subject_types: &'a Vec<TypeId>
}


#[derive(Debug)]
pub struct UnreachableRule {
  rule: Rule
}

#[derive(Debug)]
pub struct Diagnostic<'a> {
    msg: &'a str
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
    let mut full_unfulfillable_rules: UnfillableRuleMap = HashMap::new();
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
    let rules_in_graph: HashSet<_> = full_dependency_edges.keys().map(|f| f.rule.clone()).collect();
    let unfulfillable_discovered_during_construction: HashSet<_> = full_unfulfillable_rules.keys().map(|f| f.rule.clone()).collect();
    let declared_rules = self.tasks.all_rules();
    let unreachable_rules = declared_rules;//.iter()
    // unreachable rules = declared_rules \
    // - rules_in_graph
    //.filter(|r| )
    //                                    - unfulfillable_discovered_during_construction
    //.filter(|r| )
    //                                    - singletons
    //.filter(|r| )
    //                                    - intrinsics
    //.filter(|r| )
    //.collect();
    for rule in unreachable_rules {
      // can't do this because can't have a heterogeneous collection w/o wrapping w/ boxen
      //full_unfulfillable_rules.insert(UnreachableRule {rule: rule }, vec![Diagnostic{msg: "Unreachable"}]);
      println!("an unreachable rule!");
    }

    RuleGraph::new()
  }

  fn _construct_graph(&self,
                      beginning_rule: RootEntry,
                      root_rule_dependency_edges: RootRuleDependencyEdges,
                      rule_dependency_edges: RuleDependencyEdges,
                      unfulfillable_rules: UnfillableRuleMap) -> RuleGraph {
    /*
    rules_to_traverse = deque([beginning_rule])
    root_rule_dependency_edges = dict() if root_rule_dependency_edges is None else root_rule_dependency_edges
    rule_dependency_edges = dict() if rule_dependency_edges is None else rule_dependency_edges
    unfulfillable_rules = dict() if unfulfillable_rules is None else unfulfillable_rules
*/
    fn rhs_for_select(subject_type: TypeId, selector: Selector) -> Vec<InternalEntry> {
      /*
      if selector.type_constraint.satisfied_by_type(subject_type):
        # NB a matching subject is always picked first
        return (RuleGraphSubjectIsProduct(subject_type),)
      else:
        return tuple(InternalEntry(subject_type, rule)
                     for rule in self.rule_index.gen_rules(subject_type, selector.product))
      */
      vec![]
    }

    fn mark_unfulfillable(rule: Task, subject_type: TypeId, reason: &str) {
      /*
      if rule not in unfulfillable_rules:
        unfulfillable_rules[rule] = []
      unfulfillable_rules[rule].append(Diagnostic(subject_type, reason))
      */
    }


    fn add_rules_to_graph(rule: Task, selector_path: Vec<Selector>, dep_rules: Vec<InternalEntry>) {
      /*
        unseen_dep_rules = [g for g in dep_rules
                            if g not in rule_dependency_edges and
                            g not in unfulfillable_rules and
                            g not in root_rule_dependency_edges]
        rules_to_traverse.extend(unseen_dep_rules)
        if type(rule) is RootEntry:
          if rule in root_rule_dependency_edges:
            root_rule_dependency_edges[rule].add_edges_via(selector_path, dep_rules)
          else:
            new_edges = RuleEdges()
            new_edges.add_edges_via(selector_path, dep_rules)
            root_rule_dependency_edges[rule] = new_edges
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

    let mut traversal_ct = 0;
    let mut rules_to_traverse: VecDeque<Box<RuleGraphEntry>> = VecDeque::new();
    rules_to_traverse.push_back(Box::new(beginning_rule));
    while let Some(entry) = rules_to_traverse.pop_front() {
      traversal_ct += 1;
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
                                                unfulfillable_rules: UnfillableRuleMap) -> RuleGraph {
    RuleGraph::new()
  }

  fn gen_root_entries(&self, product_types: &Vec<TypeConstraint>) -> Vec<RootEntry> {
    let mut result: Vec<RootEntry> = Vec::new();
    for subj_type in self.root_subject_types.subject_types {
      for pt in product_types {
        if let Some(tasks) = self.tasks.gen_tasks(subj_type, pt) {
          let mapped_tasks: Vec<RootEntry> = tasks.iter().map(|t|
            RootEntry {
              rule: t.clone(),
              subject_type: subj_type.clone(),
              product_constraint: TypeConstraint(pt.0)
            }).collect();
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
  unfulfillable_rules: UnfillableRuleMap,
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

pub struct RuleEdges {
  current_node: Node,

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
}

impl RuleEdges {
  pub fn initial_state_for_selector() {}

  //  pub fn get_state_for_selector(selector: Selector, subject: Blah, variants: Blah, get_state: Blah) {
  //
  //}
}