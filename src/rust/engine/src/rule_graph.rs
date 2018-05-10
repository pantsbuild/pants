// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{hash_map, HashMap, HashSet, VecDeque};
use std::fmt;
use std::hash::Hash;
use std::io;

use core::{Function, Key, TypeConstraint, TypeId, Value, ANY_TYPE};
use externs;
use selectors::{Get, Select};
use tasks::{Intrinsic, Task, Tasks};

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum Entry {
  SubjectIsProduct {
    subject_type: TypeId,
  },

  Root(RootEntry),

  InnerEntry(InnerEntry),

  Singleton {
    value: Key,
    product: TypeConstraint,
  },

  Unreachable {
    // NB: unreachable is an error type, it might be better to name it error, but currently
    //     unreachable is the only error entry type.
    task_rule: Task,
    reason: Diagnostic,
  },
}

impl Entry {
  pub fn matches_subject_type(&self, actual_subject_type: TypeId) -> bool {
    match *self {
      Entry::SubjectIsProduct { subject_type }
      | Entry::Root(RootEntry { subject_type, .. })
      | Entry::InnerEntry(InnerEntry { subject_type, .. }) => subject_type == actual_subject_type,
      Entry::Singleton { .. } => true,
      Entry::Unreachable { .. } => panic!("Shouldn't compare to an unreachable entry!"),
    }
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct RootEntry {
  subject_type: TypeId,
  // TODO: A RootEntry can only have one declared `Select`, and no declared `Get`s, but these
  // are shaped as Vecs to temporarily minimize the re-shuffling in `_construct_graph`. Remove in
  // a future commit.
  clause: Vec<Select>,
  gets: Vec<Get>,
}

impl From<RootEntry> for Entry {
  fn from(entry: RootEntry) -> Entry {
    Entry::Root(entry)
  }
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
  subject_type: TypeId,
  rule: Rule,
}

impl From<InnerEntry> for Entry {
  fn from(entry: InnerEntry) -> Entry {
    Entry::InnerEntry(entry)
  }
}

impl Entry {
  fn new_subject_is_product(subject_type: TypeId) -> Entry {
    Entry::SubjectIsProduct {
      subject_type: subject_type,
    }
  }

  fn new_unreachable(task_rule: &Task) -> Entry {
    Entry::Unreachable {
      task_rule: task_rule.clone(),
      reason: Diagnostic {
        subject_type: ANY_TYPE,
        reason: "".to_string(),
      },
    }
  }

  fn new_singleton(value: Key, product: TypeConstraint) -> Entry {
    Entry::Singleton {
      value: value,
      product: product,
    }
  }

  fn can_have_dependencies(&self) -> bool {
    match self {
      &Entry::SubjectIsProduct { .. } => false,
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

  fn task_rule(&self) -> Option<&Task> {
    match self {
      &Entry::InnerEntry(InnerEntry {
        rule: Rule::Task(ref task_rule),
        ..
      }) => Some(task_rule),
      &Entry::Unreachable { ref task_rule, .. } => Some(task_rule),
      _ => None,
    }
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
  // No selector. Used for tasks with no dependencies.
  Nothing,
}

pub type Entries = Vec<Entry>;
type RootRuleDependencyEdges = HashMap<RootEntry, RuleEdges>;
type RuleDependencyEdges = HashMap<InnerEntry, RuleEdges>;
type RuleDiagnostics = Vec<Diagnostic>;
type UnfulfillableRuleMap = HashMap<Entry, RuleDiagnostics>;

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct Diagnostic {
  subject_type: TypeId,
  reason: String,
}

// Given the task index and the root subjects, it produces a rule graph that allows dependency nodes
// to be found statically rather than dynamically.
pub struct GraphMaker<'t> {
  tasks: &'t Tasks,
  root_subject_types: Vec<TypeId>,
}

impl<'t> GraphMaker<'t> {
  pub fn new(tasks: &'t Tasks, root_subject_types: Vec<TypeId>) -> GraphMaker<'t> {
    GraphMaker {
      tasks: tasks,
      root_subject_types: root_subject_types,
    }
  }

  pub fn sub_graph(&self, subject_type: &TypeId, product_type: &TypeConstraint) -> RuleGraph {
    let mut full_root_rule_dependency_edges: RootRuleDependencyEdges = HashMap::new();
    let mut full_dependency_edges: RuleDependencyEdges = HashMap::new();
    let mut full_unfulfillable_rules: UnfulfillableRuleMap = HashMap::new();

    let beginning_root =
      if let Some(beginning_root) = self.gen_root_entry(subject_type, product_type) {
        beginning_root
      } else {
        return RuleGraph {
          root_subject_types: vec![],
          root_dependencies: full_root_rule_dependency_edges,
          rule_dependency_edges: full_dependency_edges,
          unfulfillable_rules: full_unfulfillable_rules,
        };
      };

    let constructed_graph = self._construct_graph(
      beginning_root,
      full_root_rule_dependency_edges,
      full_dependency_edges,
      full_unfulfillable_rules,
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
      unfulfillable_rules: full_unfulfillable_rules,
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
        full_unfulfillable_rules,
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
      unfulfillable_rules: full_unfulfillable_rules,
    };

    self._remove_unfulfillable_rules_and_dependents(&mut in_progress_graph);
    in_progress_graph
  }

  fn add_unreachable_rule_diagnostics(
    &self,
    full_dependency_edges: &RuleDependencyEdges,
    full_unfulfillable_rules: &mut UnfulfillableRuleMap,
  ) {
    let rules_in_graph: HashSet<_> = full_dependency_edges
      .keys()
      .filter_map(|entry| match entry {
        &InnerEntry {
          rule: Rule::Task(ref task_rule),
          ..
        } => Some(task_rule.clone()),
        _ => None,
      })
      .collect();
    let unfulfillable_discovered_during_construction: HashSet<_> = full_unfulfillable_rules
      .keys()
      .filter_map(|f| f.task_rule())
      .cloned()
      .collect();
    let unreachable_rules: HashSet<_> = self
      .tasks
      .all_tasks()
      .iter()
      .filter(|r| !rules_in_graph.contains(r))
      .filter(|r| !unfulfillable_discovered_during_construction.contains(r))
      .map(|&r| r)
      .collect();

    for rule in unreachable_rules {
      let diagnostics = full_unfulfillable_rules
        .entry(Entry::new_unreachable(rule))
        .or_insert(vec![]);
      diagnostics.push(Diagnostic {
        subject_type: ANY_TYPE,
        reason: "Unreachable".to_string(),
      });
    }
  }

  fn _construct_graph(
    &self,
    beginning_rule: RootEntry,
    mut root_rule_dependency_edges: RootRuleDependencyEdges,
    mut rule_dependency_edges: RuleDependencyEdges,
    mut unfulfillable_rules: UnfulfillableRuleMap,
  ) -> RuleGraph {
    let mut rules_to_traverse: VecDeque<Entry> = VecDeque::new();
    rules_to_traverse.push_back(Entry::from(beginning_rule));
    while let Some(entry) = rules_to_traverse.pop_front() {
      // TODO: Drop both of these methods, and just noop for irrelevant entries in the match.
      if entry.can_be_dependency() && !entry.can_have_dependencies() {
        continue;
      }
      if !entry.can_have_dependencies() {
        panic!(
          "Cannot determine deps of entry that can be neither a dependency or dependent: {:?}",
          entry
        )
      }
      if unfulfillable_rules.contains_key(&entry) {
        continue;
      }
      if let Entry::InnerEntry(ref inner_entry) = entry {
        if rule_dependency_edges.contains_key(inner_entry) {
          continue;
        }
      }
      let mut was_unfulfillable = false;
      match entry {
        Entry::InnerEntry(InnerEntry {
          rule:
            Rule::Task(Task {
              ref clause,
              ref gets,
              ..
            }),
          ..
        })
        | Entry::Root(RootEntry {
          ref clause,
          ref gets,
          ..
        }) => {
          for select in clause {
            // TODO, handle the Addresses / Variants case
            let rules_or_literals_for_selector =
              rhs_for_select(&self.tasks, entry.subject_type(), &select);
            if rules_or_literals_for_selector.is_empty() {
              mark_unfulfillable(
                &mut unfulfillable_rules,
                &entry,
                entry.subject_type(),
                format!("no matches for {}", select_str(select)),
              );
              was_unfulfillable = true;
              continue;
            }
            add_rules_to_graph(
              &mut rules_to_traverse,
              &mut rule_dependency_edges,
              &mut unfulfillable_rules,
              &mut root_rule_dependency_edges,
              &entry,
              SelectKey::JustSelect(select.clone()),
              rules_or_literals_for_selector,
            );
          }
          for get in gets {
            match get {
              &Get {
                ref subject,
                ref product,
              } => {
                let rules_or_literals_for_selector = rhs(&self.tasks, subject.clone(), product);
                if rules_or_literals_for_selector.is_empty() {
                  mark_unfulfillable(
                    &mut unfulfillable_rules,
                    &entry,
                    subject.clone(),
                    format!(
                      "no rule was available to compute {} for {}",
                      type_constraint_str(product.clone()),
                      type_str(subject.clone())
                    ),
                  );
                  was_unfulfillable = true;
                  continue;
                }
                add_rules_to_graph(
                  &mut rules_to_traverse,
                  &mut rule_dependency_edges,
                  &mut unfulfillable_rules,
                  &mut root_rule_dependency_edges,
                  &entry,
                  SelectKey::JustGet(get.clone()),
                  rules_or_literals_for_selector,
                );
              }
            }
          }
        }
        Entry::InnerEntry(InnerEntry {
          rule: Rule::Intrinsic(Intrinsic { ref input, .. }),
          ref subject_type,
        }) => {
          let rules_or_literals_for_selector = rhs(&self.tasks, subject_type.clone(), input);
          if rules_or_literals_for_selector.is_empty() {
            mark_unfulfillable(
              &mut unfulfillable_rules,
              &entry,
              subject_type.clone(),
              format!(
                "no rule was available to compute {} for {}",
                type_constraint_str(input.clone()),
                type_str(subject_type.clone())
              ),
            );
            was_unfulfillable = true;
          } else {
            add_rules_to_graph(
              &mut rules_to_traverse,
              &mut rule_dependency_edges,
              &mut unfulfillable_rules,
              &mut root_rule_dependency_edges,
              &entry,
              SelectKey::JustSelect(Select::without_variant(*input)),
              rules_or_literals_for_selector,
            );
          }
        }
        _ => panic!(
          "Entry type that cannot have dependencies was not filtered out {:?}",
          entry
        ),
      }
      // TODO handle snapshot rules
      if !was_unfulfillable {
        // NB: In this case there were no selectors
        add_rules_to_graph(
          &mut rules_to_traverse,
          &mut rule_dependency_edges,
          &mut unfulfillable_rules,
          &mut root_rule_dependency_edges,
          &entry,
          SelectKey::Nothing,
          vec![],
        );
      }
    }
    RuleGraph {
      root_subject_types: self.root_subject_types.clone(),
      root_dependencies: root_rule_dependency_edges,
      rule_dependency_edges: rule_dependency_edges,
      unfulfillable_rules: unfulfillable_rules,
    }
  }

  fn _remove_unfulfillable_rules_and_dependents(&self, rule_graph: &mut RuleGraph) {
    // Removes all unfulfillable rules transitively from the roots and the dependency edges.
    //
    // Takes the current root rule set and dependency table and removes all rules that are not
    // transitively fulfillable.
    //
    // Deforestation. Leaping from tree to tree.

    let mut removal_traversal: VecDeque<_> =
      rule_graph.unfulfillable_rules.keys().cloned().collect();
    // could experiment with doing this for each rule added and deduping the traversal list
    while let Some(unfulfillable_entry) = removal_traversal.pop_front() {
      update_edges_based_on_unfulfillable_entry(
        &mut rule_graph.rule_dependency_edges,
        &mut rule_graph.unfulfillable_rules,
        &mut removal_traversal,
        &unfulfillable_entry,
      );
      update_edges_based_on_unfulfillable_entry(
        &mut rule_graph.root_dependencies,
        &mut rule_graph.unfulfillable_rules,
        &mut removal_traversal,
        &unfulfillable_entry,
      );
    }

    // blow up if there's something off.
    // TODO do this with types on add rather than blowing up after.
    // I think I could make it impossible rather than fixing up after the fact.
    for (ref root_rule, ref deps) in &rule_graph.root_dependencies {
      for d in &deps.dependencies {
        match d {
          &Entry::InnerEntry(ref inner) => {
            if !rule_graph.rule_dependency_edges.contains_key(inner) {
              panic!(
                "All referenced dependencies should have entries in the graph, but {:?} had {:?}, \
                 which is missing!",
                root_rule, d
              )
            }
          }
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

  fn gen_root_entry(
    &self,
    subject_type: &TypeId,
    product_type: &TypeConstraint,
  ) -> Option<RootEntry> {
    let candidates = rhs(&self.tasks, subject_type.clone(), product_type);
    if candidates.is_empty() {
      None
    } else {
      Some(RootEntry {
        subject_type: subject_type.clone(),
        clause: vec![
          Select {
            product: product_type.clone(),
            variant_key: None,
          },
        ],
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
/// `root_subject_types` the root subject types this graph was generated with.
/// `root_dependencies` A map from root rules, ie rules representing the expected selector / subject
///   types for requests, to the rules that can fulfill them.
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

fn val_name(val: &Value) -> String {
  externs::project_str(val, "__name__")
}

pub fn select_str(select: &Select) -> String {
  format!("Select({})", type_constraint_str(select.product)).to_string() // TODO variant key
}

fn get_str(get: &Get) -> String {
  format!(
    "Get({}, {})",
    type_constraint_str(get.product),
    type_str(get.subject.clone())
  )
}

fn entry_str(entry: &Entry) -> String {
  match entry {
    &Entry::InnerEntry(InnerEntry {
      rule: Rule::Task(ref task_rule),
      subject_type,
    }) => format!("{} of {}", task_display(task_rule), type_str(subject_type)),
    &Entry::InnerEntry(InnerEntry {
      rule: Rule::Intrinsic(ref intrinsic),
      subject_type,
    }) => format!(
      "({}, ({},), {:?}) for {}",
      type_constraint_str(intrinsic.product),
      type_constraint_str(intrinsic.input),
      intrinsic.kind,
      type_str(subject_type)
    ),
    &Entry::Root(ref root) => format!(
      "{} for {}",
      root
        .clause
        .iter()
        .map(|s| select_str(s))
        .collect::<Vec<_>>()
        .join(", "),
      type_str(root.subject_type)
    ),
    &Entry::SubjectIsProduct { subject_type } => {
      format!("SubjectIsProduct({})", type_str(subject_type))
    }
    &Entry::Singleton { ref value, product } => format!(
      "Singleton({}, {})",
      externs::key_to_str(value),
      type_constraint_str(product)
    ),
    &Entry::Unreachable {
      ref task_rule,
      ref reason,
    } => format!("Unreachable({}, {:?})", task_display(task_rule), reason),
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
  clause_portion = if task.clause.len() <= 1 {
    format!("({},)", clause_portion)
  } else {
    format!("({})", clause_portion)
  };
  let mut get_portion = task
    .gets
    .iter()
    .map(|g| get_str(g))
    .collect::<Vec<_>>()
    .join(", ");
  get_portion = if task.gets.len() > 0 {
    format!("[{}], ", get_portion)
  } else {
    "".to_string()
  };
  let function_name = function_str(&&task.func);
  format!(
    "({}, {}, {}{})",
    product, clause_portion, get_portion, function_name
  ).to_string()
}

impl RuleGraph {
  pub fn new(tasks: &Tasks, root_subject_types: Vec<TypeId>) -> RuleGraph {
    GraphMaker::new(tasks, root_subject_types).full_graph()
  }

  pub fn find_root_edges(&self, subject_type: TypeId, select: Select) -> Option<RuleEdges> {
    // TODO return Result instead
    let root = RootEntry {
      subject_type: subject_type,
      clause: vec![select],
      gets: vec![],
    };
    self.root_dependencies.get(&root).map(|e| e.clone())
  }

  pub fn rule_for_inner<'a>(&self, entry: &'a Entry) -> &'a Rule {
    if let &Entry::InnerEntry(ref inner) = entry {
      &inner.rule
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
    self
      .rule_dependency_edges
      .get(inner_entry)
      .map(|e| e.clone())
  }

  pub fn validate(&self) -> Result<(), String> {
    // TODO the rule display is really unfriendly right now. Next up should be to improve it.
    let mut collated_errors: HashMap<Task, HashMap<String, HashSet<TypeId>>> = HashMap::new();

    let used_rules: HashSet<_> = self
      .rule_dependency_edges
      .keys()
      .filter_map(|entry| match entry {
        &InnerEntry {
          rule: Rule::Task(ref task_rule),
          ..
        } => Some(task_rule),
        _ => None,
      })
      .collect();

    for (rule_entry, diagnostics) in &self.unfulfillable_rules {
      match rule_entry {
        &Entry::InnerEntry(InnerEntry {
          rule: Rule::Task(ref task_rule),
          ..
        })
        | &Entry::Unreachable { ref task_rule, .. } => {
          if used_rules.contains(&task_rule) {
            continue;
          }
          for d in diagnostics {
            let msg_to_type = collated_errors
              .entry(task_rule.clone())
              .or_insert(HashMap::new());
            let subject_set = msg_to_type
              .entry(d.reason.clone())
              .or_insert(HashSet::new());
            subject_set.insert(d.subject_type.clone());
          }
        }
        _ => {} // We're only checking rule usage not entry usage generally.
                // So we ignore entries that do not have rules.
      }
    }

    if collated_errors.is_empty() {
      return Ok(());
    }

    let mut msgs: Vec<String> = collated_errors
      .into_iter()
      .map(|(ref rule, ref subject_types_by_reasons)| format_msgs(rule, subject_types_by_reasons))
      .collect();
    msgs.sort();

    Err(format!("Rules with errors: {}\n  {}", msgs.len(), msgs.join("\n  ")).to_string())
  }

  pub fn visualize(&self, f: &mut io::Write) -> io::Result<()> {
    if self.root_dependencies.is_empty() && self.rule_dependency_edges.is_empty() {
      write!(f, "digraph {{\n")?;
      write!(f, "  // empty graph\n")?;
      return write!(f, "}}");
    }

    let mut root_subject_type_strs = self
      .root_subject_types
      .iter()
      .map(|&t| type_str(t))
      .collect::<Vec<String>>();
    root_subject_type_strs.sort();
    write!(f, "digraph {{\n")?;
    write!(
      f,
      "  // root subject types: {}\n",
      root_subject_type_strs.join(", ")
    )?;
    write!(f, "  // root entries\n")?;
    let mut root_rule_strs = self
      .root_dependencies
      .iter()
      .map(|(k, deps)| {
        let root_str = entry_str(&Entry::from(k.clone()));
        format!(
          "    \"{}\" [color=blue]\n    \"{}\" -> {{{}}}",
          root_str,
          root_str,
          deps
            .dependencies
            .iter()
            .map(|d| format!("\"{}\"", entry_str(d)))
            .collect::<Vec<String>>()
            .join(" ")
        )
      })
      .collect::<Vec<String>>();
    root_rule_strs.sort();
    write!(f, "{}\n", root_rule_strs.join("\n"))?;

    write!(f, "  // internal entries\n")?;
    let mut internal_rule_strs = self
      .rule_dependency_edges
      .iter()
      .map(|(k, deps)| {
        format!(
          "    \"{}\" -> {{{}}}",
          entry_str(&Entry::from(k.clone())),
          deps
            .dependencies
            .iter()
            .map(|d| format!("\"{}\"", entry_str(d)))
            .collect::<Vec<String>>()
            .join(" ")
        )
      })
      .collect::<Vec<String>>();
    internal_rule_strs.sort();
    write!(f, "{}\n", internal_rule_strs.join("\n"))?;
    write!(f, "}}")
  }
}

#[derive(Eq, PartialEq, Clone, Debug)]
pub struct RuleEdges {
  dependencies: Entries,
  dependencies_by_select_key: HashMap<SelectKey, Entries>,
}

impl RuleEdges {
  pub fn new() -> RuleEdges {
    RuleEdges {
      dependencies: vec![],
      dependencies_by_select_key: HashMap::new(),
    }
  }

  pub fn entries_for(&self, select_key: &SelectKey) -> Entries {
    self
      .dependencies_by_select_key
      .get(select_key)
      .cloned()
      .unwrap_or_else(|| Vec::new())
  }

  pub fn is_empty(&self) -> bool {
    self.dependencies.is_empty()
  }

  fn add_edges_via(&mut self, select_key: SelectKey, new_dependencies: &Entries) {
    if SelectKey::Nothing == select_key && !new_dependencies.is_empty() {
      panic!("Cannot specify a None selector with non-empty dependencies!")
    }
    let deps_for_selector = self
      .dependencies_by_select_key
      .entry(select_key)
      .or_insert(vec![]);
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
    } else if self
      .dependencies_by_select_key
      .values()
      .any(|deps| deps.len() == 1 && &deps[0] == dep_to_eliminate)
    {
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

fn update_edges_based_on_unfulfillable_entry<K>(
  edge_container: &mut HashMap<K, RuleEdges>,
  new_unfulfillable_rules: &mut UnfulfillableRuleMap,
  removal_traversal: &mut VecDeque<Entry>,
  unfulfillable_entry: &Entry,
) where
  Entry: From<K>,
  K: Eq + Hash + Clone + fmt::Debug,
{
  let keys: Vec<_> = edge_container.keys().cloned().collect();

  for current_entry in keys {
    if let hash_map::Entry::Occupied(mut o) = edge_container.entry(current_entry) {
      if new_unfulfillable_rules.contains_key(&Entry::from(o.key().clone())) {
        o.remove();
      } else if o.get().makes_unfulfillable(&unfulfillable_entry) {
        let key_entry = Entry::from(o.key().clone());

        let entry_subject = key_entry.subject_type();
        let diagnostics = new_unfulfillable_rules
          .entry(key_entry.clone())
          .or_insert(vec![]);
        diagnostics.push(Diagnostic {
          subject_type: entry_subject,
          reason: format!(
            "depends on unfulfillable {}",
            entry_str(unfulfillable_entry)
          ),
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
  rhs(tasks, subject_type, &select.product)
}

fn rhs(tasks: &Tasks, subject_type: TypeId, product_type: &TypeConstraint) -> Entries {
  if externs::satisfied_by_type(product_type, &subject_type) {
    // NB a matching subject is always picked first
    vec![Entry::new_subject_is_product(subject_type)]
  } else if let Some(&(ref key, _)) = tasks.gen_singleton(product_type) {
    vec![Entry::new_singleton(key.clone(), product_type.clone())]
  } else {
    let mut entries = Vec::new();
    if let Some(matching_intrinsic) = tasks.gen_intrinsic(product_type) {
      entries.push(Entry::InnerEntry(InnerEntry {
        subject_type: subject_type,
        rule: Rule::Intrinsic(matching_intrinsic.clone()),
      }));
    }
    if let Some(matching_tasks) = tasks.gen_tasks(product_type) {
      entries.extend(matching_tasks.iter().map(|task_rule| {
        Entry::InnerEntry(InnerEntry {
          subject_type: subject_type,
          rule: Rule::Task(task_rule.clone()),
        })
      }));
    }
    entries
  }
}

fn mark_unfulfillable(
  unfulfillable_rules: &mut UnfulfillableRuleMap,
  entry: &Entry,
  subject_type: TypeId,
  reason: String,
) {
  // instead of being modifiable, this could return a UnfulfillableRuleMap that then gets merged.
  let ref mut diagnostics_for_entry = *unfulfillable_rules.entry(entry.clone()).or_insert(vec![]);
  diagnostics_for_entry.push(Diagnostic {
    subject_type: subject_type,
    reason: reason,
  });
}

fn add_rules_to_graph(
  rules_to_traverse: &mut VecDeque<Entry>,
  rule_dependency_edges: &mut RuleDependencyEdges,
  unfulfillable_rules: &mut UnfulfillableRuleMap,
  root_rule_dependency_edges: &mut RootRuleDependencyEdges,
  entry: &Entry,
  select_key: SelectKey,
  dep_rules: Entries,
) {
  {
    let rule_deps: &RuleDependencyEdges = rule_dependency_edges;
    let unseen_dep_rules = dep_rules
      .iter()
      .filter(|g| !unfulfillable_rules.contains_key(g))
      .filter(|g| match *g {
        &Entry::InnerEntry(ref r) => !rule_deps.contains_key(&r),
        &Entry::Root(ref r) => !root_rule_dependency_edges.contains_key(&r),
        _ => true,
      })
      .cloned();
    rules_to_traverse.extend(unseen_dep_rules);
  }
  match entry {
    &Entry::Root(ref root_entry) => {
      let edges = root_rule_dependency_edges
        .entry(root_entry.clone())
        .or_insert(RuleEdges::new());
      edges.add_edges_via(select_key, &dep_rules);
    }
    &Entry::InnerEntry(ref inner_entry) => {
      let edges = rule_dependency_edges
        .entry(inner_entry.clone())
        .or_insert(RuleEdges::new());
      if edges.has_edges_for(&select_key) {
        // This is an error that should only happen if there's a bug in the algorithm, but it
        // might make sense to expose it in a more friendly way.
        panic!(
          "Rule {:?} already has dependencies set for selector {:?}",
          entry, select_key
        )
      }
      edges.add_edges_via(select_key, &dep_rules);
    }
    _ => {
      // these should have already been filtered out before this was called.
      // TODO enforce ^^ more clearly
      panic!(
        "expected this entry type to have already been filtered out {:?}",
        entry
      )
    }
  }
}

fn format_msgs(rule: &Task, subject_types_by_reasons: &HashMap<String, HashSet<TypeId>>) -> String {
  let mut errors: Vec<_> = subject_types_by_reasons
    .iter()
    .map(|(reason, subject_types)| {
      format!(
        "{} with subject types: {}",
        reason,
        subject_types
          .iter()
          .map(|&t| type_str(t))
          .collect::<Vec<String>>()
          .join(", ")
      )
    })
    .collect();
  errors.sort();
  format!("{}:\n    {}", task_display(rule), errors.join("\n    "))
}
