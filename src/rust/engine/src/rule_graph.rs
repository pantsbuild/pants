// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{hash_map, HashMap, HashSet};
use std::io;

use core::{Function, Key, TypeConstraint, TypeId, Value, ANY_TYPE};
use externs;
use selectors::{Get, Select};
use tasks::{Intrinsic, Task, Tasks};

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
        subject_type: ANY_TYPE,
        reason: "Unreachable".to_string(),
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
  fn subject_type(&self) -> TypeId {
    match self {
      &EntryWithDeps::Root(ref re) => re.subject_type,
      &EntryWithDeps::Inner(ref ie) => ie.subject_type,
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
        .chain(gets.iter().map(|g| SelectKey::JustGet(g.clone())))
        .collect(),
      &EntryWithDeps::Inner(InnerEntry {
        rule: Rule::Intrinsic(Intrinsic { ref input, .. }),
        ..
      }) => vec![
        SelectKey::JustSelect(Select::without_variant(input.clone())),
      ],
    }
  }
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum Entry {
  SubjectIsProduct { subject_type: TypeId },

  WithDeps(EntryWithDeps),

  Singleton { value: Key, product: TypeConstraint },
}

impl Entry {
  pub fn matches_subject_type(&self, actual_subject_type: TypeId) -> bool {
    match self {
      &Entry::SubjectIsProduct { ref subject_type } => *subject_type == actual_subject_type,
      &Entry::WithDeps(ref r) => r.subject_type() == actual_subject_type,
      &Entry::Singleton { .. } => true,
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

impl InnerEntry {
  pub fn rule(&self) -> &Rule {
    &self.rule
  }
}

impl Entry {
  fn new_subject_is_product(subject_type: TypeId) -> Entry {
    Entry::SubjectIsProduct {
      subject_type: subject_type,
    }
  }

  fn new_singleton(value: Key, product: TypeConstraint) -> Entry {
    Entry::Singleton {
      value: value,
      product: product,
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
}

pub type Entries = Vec<Entry>;
type RuleDependencyEdges = HashMap<EntryWithDeps, RuleEdges>;
type RuleDiagnostics = Vec<Diagnostic>;
type UnfulfillableRuleMap = HashMap<EntryWithDeps, RuleDiagnostics>;

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
    if let Some(beginning_root) = self.gen_root_entry(subject_type, product_type) {
      self._construct_graph(vec![beginning_root])
    } else {
      Default::default()
    }
  }

  pub fn full_graph(&self) -> RuleGraph {
    self._construct_graph(self.gen_root_entries(&self.tasks.all_product_types()))
  }

  pub fn _construct_graph(&self, roots: Vec<RootEntry>) -> RuleGraph {
    let mut dependency_edges: RuleDependencyEdges = HashMap::new();
    let mut unfulfillable_rules: UnfulfillableRuleMap = HashMap::new();

    for beginning_root in roots.into_iter() {
      self._construct_graph_helper(
        &mut dependency_edges,
        &mut unfulfillable_rules,
        EntryWithDeps::Root(beginning_root),
      );
    }

    let unreachable_rules = self.unreachable_rules(&dependency_edges, &unfulfillable_rules);

    RuleGraph {
      root_subject_types: self.root_subject_types.clone(),
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
      })
      .collect();
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
  /// Computes (and memoizes) whether any rules can compute the given `product_type` for the given
  /// `subject_type`.
  ///
  /// When a rule cannot be fulfilled, it is added to `unfulfillable_rules` rather than to
  /// `rule_dependency_edges`.
  ///
  fn _construct_graph_helper(
    &self,
    rule_dependency_edges: &mut RuleDependencyEdges,
    unfulfillable_rules: &mut UnfulfillableRuleMap,
    entry: EntryWithDeps,
  ) -> bool {
    // If the entry has not been visited before, store a placeholder in the unfulfillable rules map
    // and then visit its children. Otherwise, we're done.
    //
    // This prevents infinite recursion by shortcircuiting when an entry recursively depends on
    // itself. It's totally fine for rules to be recursive: the recursive path just never
    // contributes to whether the rule is satisfiable.
    match (unfulfillable_rules.entry(entry.clone()), rule_dependency_edges.entry(entry.clone())) {
      (hash_map::Entry::Vacant(_), hash_map::Entry::Vacant(re)) => {
        // When a rule has not been visited before, we visit it by storing a placeholder in the
        // rule dependencies map (to prevent infinite recursion).
        re.insert(Default::default());
      },
      (hash_map::Entry::Vacant(_), hash_map::Entry::Occupied(_)) =>
        // Rule has been visited before and been found to be valid, or is currently being
        // recursively visited and has a placeholder.
        return true,
      (hash_map::Entry::Occupied(_), _) =>
        // Rule has either been visited before and found unfulfillable.
        return false,
    };

    // For each dependency of the rule, recurse for each potential match and collect RuleEdges.
    let mut edges = RuleEdges::new();
    let mut fulfillable = true;
    for select_key in entry.dependency_keys().into_iter() {
      let (subject, product) = match &select_key {
        &SelectKey::JustSelect(ref s) => (entry.subject_type(), s.product.clone()),
        &SelectKey::JustGet(ref g) => (g.subject.clone(), g.product.clone()),
      };

      // Confirm that at least one candidate is fulfillable.
      let fulfillable_candidates = rhs(&self.tasks, subject, &product)
        .into_iter()
        .filter(|candidate| match candidate {
          &Entry::WithDeps(ref c) => {
            self._construct_graph_helper(rule_dependency_edges, unfulfillable_rules, c.clone())
          }
          &Entry::SubjectIsProduct { .. } => true,
          &Entry::Singleton { .. } => true,
        })
        .collect::<Vec<_>>();

      if fulfillable_candidates.is_empty() {
        // If no candidates were fulfillable, this rule is not fulfillable.
        unfulfillable_rules
          .entry(entry.clone())
          .or_insert(vec![])
          .push(Diagnostic {
            subject_type: subject.clone(),
            reason: format!(
              "no rule was available to compute {} for {}",
              type_constraint_str(product.clone()),
              type_str(subject.clone())
            ),
          });
        fulfillable = false;
      } else {
        // Extend the RuleEdges for this SelectKey.
        edges.add_edges_via(select_key, fulfillable_candidates);
      }
    }

    if fulfillable {
      // All depedendencies were fulfillable: replace the placeholder with the computed RuleEdges.
      rule_dependency_edges.insert(entry, edges);
      true
    } else {
      // Was not fulfillable. Remove the placeholder: the unfulfillable entries we stored will
      // prevent us from attempting to expand this node again.
      rule_dependency_edges.remove(&entry);
      false
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
#[derive(Debug, Default)]
pub struct RuleGraph {
  root_subject_types: Vec<TypeId>,
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
    &Entry::WithDeps(ref e) => entry_with_deps_str(e),
    &Entry::SubjectIsProduct { subject_type } => {
      format!("SubjectIsProduct({})", type_str(subject_type))
    }
    &Entry::Singleton { ref value, product } => format!(
      "Singleton({}, {})",
      externs::key_to_str(value),
      type_constraint_str(product)
    ),
  }
}

fn entry_with_deps_str(entry: &EntryWithDeps) -> String {
  match entry {
    &EntryWithDeps::Inner(InnerEntry {
      rule: Rule::Task(ref task_rule),
      subject_type,
    }) => format!("{} of {}", task_display(task_rule), type_str(subject_type)),
    &EntryWithDeps::Inner(InnerEntry {
      rule: Rule::Intrinsic(ref intrinsic),
      subject_type,
    }) => format!(
      "({}, ({},), {:?}) for {}",
      type_constraint_str(intrinsic.product),
      type_constraint_str(intrinsic.input),
      intrinsic.kind,
      type_str(subject_type)
    ),
    &EntryWithDeps::Root(ref root) => format!(
      "{} for {}",
      root
        .clause
        .iter()
        .map(|s| select_str(s))
        .collect::<Vec<_>>()
        .join(", "),
      type_str(root.subject_type)
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
    self
      .rule_dependency_edges
      .get(&EntryWithDeps::Root(root))
      .map(|e| e.clone())
  }

  ///
  /// TODO: It's not clear what is preventing `Node` implementations from ending up with non-Inner
  /// entries, but it would be good to make it typesafe instead.
  ///
  pub fn rule_for_inner<'a>(&self, entry: &'a Entry) -> &'a Rule {
    if let &Entry::WithDeps(EntryWithDeps::Inner(ref inner)) = entry {
      &inner.rule
    } else {
      panic!("not an inner entry! {:?}", entry)
    }
  }

  ///
  /// TODO: See rule_for_inner.
  ///
  pub fn edges_for_inner(&self, entry: &Entry) -> Option<RuleEdges> {
    if let &Entry::WithDeps(ref e) = entry {
      self.rule_dependency_edges.get(e).map(|e| e.clone())
    } else {
      panic!("not an inner entry! {:?}", entry)
    }
  }

  pub fn validate(&self) -> Result<(), String> {
    // TODO the rule display is really unfriendly right now. Next up should be to improve it.
    let mut collated_errors: HashMap<Task, HashMap<String, HashSet<TypeId>>> = HashMap::new();

    let used_rules: HashSet<_> = self
      .rule_dependency_edges
      .keys()
      .filter_map(|entry| match entry {
        &EntryWithDeps::Inner(InnerEntry {
          rule: Rule::Task(ref task_rule),
          ..
        }) => Some(task_rule),
        _ => None,
      })
      .collect();

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
      })
      .chain(
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
        let msg_to_type = collated_errors
          .entry(task_rule.clone())
          .or_insert(HashMap::new());
        let subject_set = msg_to_type
          .entry(d.reason.clone())
          .or_insert(HashSet::new());
        subject_set.insert(d.subject_type.clone());
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
    if self.rule_dependency_edges.is_empty() {
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
              .dependencies
              .iter()
              .map(|d| format!("\"{}\"", entry_str(d)))
              .collect::<Vec<String>>()
              .join(" ")
          ))
        }
        _ => None,
      })
      .collect::<Vec<String>>();
    root_rule_strs.sort();
    write!(f, "{}\n", root_rule_strs.join("\n"))?;

    write!(f, "  // internal entries\n")?;
    let mut internal_rule_strs = self
      .rule_dependency_edges
      .iter()
      .filter_map(|(k, deps)| match k {
        &EntryWithDeps::Inner(_) => Some(format!(
          "    \"{}\" -> {{{}}}",
          entry_with_deps_str(k),
          deps
            .dependencies
            .iter()
            .map(|d| format!("\"{}\"", entry_str(d)))
            .collect::<Vec<String>>()
            .join(" ")
        )),
        _ => None,
      })
      .collect::<Vec<String>>();
    internal_rule_strs.sort();
    write!(f, "{}\n", internal_rule_strs.join("\n"))?;
    write!(f, "}}")
  }
}

#[derive(Eq, PartialEq, Clone, Debug, Default)]
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

  fn add_edges_via(&mut self, select_key: SelectKey, new_dependencies: Entries) {
    let deps_for_selector = self
      .dependencies_by_select_key
      .entry(select_key)
      .or_insert(vec![]);
    for d in new_dependencies.into_iter() {
      if !deps_for_selector.contains(&d) {
        deps_for_selector.push(d.clone());
      }
      if !self.dependencies.contains(&d) {
        self.dependencies.push(d);
      }
    }
  }
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
      entries.push(Entry::WithDeps(EntryWithDeps::Inner(InnerEntry {
        subject_type: subject_type,
        rule: Rule::Intrinsic(matching_intrinsic.clone()),
      })));
    }
    if let Some(matching_tasks) = tasks.gen_tasks(product_type) {
      entries.extend(matching_tasks.iter().map(|task_rule| {
        Entry::WithDeps(EntryWithDeps::Inner(InnerEntry {
          subject_type: subject_type,
          rule: Rule::Task(task_rule.clone()),
        }))
      }));
    }
    entries
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
