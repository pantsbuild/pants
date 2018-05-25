// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{hash_map, BTreeSet, HashMap, HashSet};
use std::io;

use core::{Function, Key, Params, TypeConstraint, TypeId, Value, ANY_TYPE};
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
        params: Default::default(),
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
  fn params(&self) -> &ParamTypes {
    match self {
      &EntryWithDeps::Root(ref re) => &re.params,
      &EntryWithDeps::Inner(ref ie) => &ie.params,
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
      }) => vec![SelectKey::JustSelect(Select::without_variant(*input))],
    }
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

pub type Entries = Vec<Entry>;
type RuleDependencyEdges = HashMap<EntryWithDeps, RuleEdges>;
type RuleDiagnostics = Vec<Diagnostic>;
type UnfulfillableRuleMap = HashMap<EntryWithDeps, RuleDiagnostics>;

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct Diagnostic {
  params: ParamTypes,
  reason: String,
}

// Given the task index and the root subjects, it produces a rule graph that allows dependency nodes
// to be found statically rather than dynamically.
pub struct GraphMaker<'t> {
  tasks: &'t Tasks,
  root_param_types: ParamTypes,
}

impl<'t> GraphMaker<'t> {
  pub fn new(tasks: &'t Tasks, root_subject_types: Vec<TypeId>) -> GraphMaker<'t> {
    let root_param_types = root_subject_types.into_iter().collect();
    GraphMaker {
      tasks,
      root_param_types,
    }
  }

  pub fn sub_graph(&self, subject_type: &TypeId, product_type: &TypeConstraint) -> RuleGraph {
    // TODO: Update to support rendering a subgraph given a set of ParamTypes.
    let param_types = vec![*subject_type].into_iter().collect();

    if let Some(beginning_root) = self.gen_root_entry(&param_types, product_type) {
      self._construct_graph(vec![beginning_root])
    } else {
      RuleGraph::default()
    }
  }

  pub fn full_graph(&self) -> RuleGraph {
    self._construct_graph(self.gen_root_entries(&self.tasks.all_product_types()))
  }

  pub fn _construct_graph(&self, roots: Vec<RootEntry>) -> RuleGraph {
    let mut dependency_edges: RuleDependencyEdges = HashMap::new();
    let mut entry_equivalences = HashMap::new();
    let mut unfulfillable_rules: UnfulfillableRuleMap = HashMap::new();

    for beginning_root in roots {
      self._construct_graph_helper(
        &mut dependency_edges,
        &mut entry_equivalences,
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
  /// Computes whether the given candidate entry is satisfiable, and if it is, returns a copy
  /// of the entry with its parameters pruned to what is actually used. Once computed, the
  /// "equivalence" of the input entry to the output entry is memoized in entry_equivalences.
  ///
  /// When a rule can be fulfilled it will end up stored in both the rule_dependency_edges and
  /// the equivalances. If it can't be fulfilled, it is added to `unfulfillable_rules`.
  ///
  fn _construct_graph_helper(
    &self,
    rule_dependency_edges: &mut RuleDependencyEdges,
    entry_equivalences: &mut HashMap<EntryWithDeps, EntryWithDeps>,
    unfulfillable_rules: &mut UnfulfillableRuleMap,
    entry: EntryWithDeps,
  ) -> Option<EntryWithDeps> {
    if let Some(equivalent) = entry_equivalences.get(&entry) {
      // A simplified equivalent entry has already been computed, return it.
      return Some(equivalent.clone());
    } else if let Some(_) = unfulfillable_rules.get(&entry) {
      // The rule is unfulfillable.
      return None;
    }

    // Otherwise, store a placeholder in the rule_dependency_edges map and then visit its
    // children.
    //
    // This prevents infinite recursion by shortcircuiting when an entry recursively depends on
    // itself. It's totally fine for rules to be recursive: the recursive path just never
    // contributes to whether the rule is satisfiable.
    match rule_dependency_edges.entry(entry.clone()) {
      hash_map::Entry::Vacant(re) => {
        // When a rule has not been visited before, we visit it by storing a placeholder in the
        // rule dependencies map (to prevent infinite recursion).
        re.insert(RuleEdges::default());
      },
      hash_map::Entry::Occupied(o) =>
        // We're currently recursively under this rule, but its simplified equivalence has not yet
        // been computed. This entry will be rewritten with its equivalency when the parent
        // completes.
        return Some(o.key().clone()),
    };

    // For each dependency of the rule, recurse for each potential match and collect RuleEdges.
    let mut edges = RuleEdges::new();
    let mut fulfillable = true;
    let mut used_params = BTreeSet::new();
    for select_key in entry.dependency_keys() {
      let (params, product) = match &select_key {
        &SelectKey::JustSelect(ref s) => (entry.params().clone(), s.product.clone()),
        &SelectKey::JustGet(ref g) => {
          let get_params = {
            let mut p = entry.params().clone();
            p.insert(g.subject.clone());
            p
          };
          (get_params, g.product.clone())
        }
      };

      // Confirm that at least one candidate is fulfillable.
      let fulfillable_candidates = rhs(&self.tasks, &params, &product)
        .into_iter()
        .filter_map(|candidate| match candidate {
          Entry::WithDeps(c) => {
            if let Some(equivalence) = self._construct_graph_helper(
              rule_dependency_edges,
              entry_equivalences,
              unfulfillable_rules,
              c,
            ) {
              used_params.extend(equivalence.params().iter().cloned());
              Some(Entry::WithDeps(equivalence))
            } else {
              None
            }
          }
          Entry::Param(type_id) => {
            used_params.insert(type_id);
            Some(Entry::Param(type_id))
          }
          s @ Entry::Singleton { .. } => Some(s),
        })
        .collect::<Vec<_>>();

      if fulfillable_candidates.is_empty() {
        // If no candidates were fulfillable, this rule is not fulfillable.
        unfulfillable_rules
          .entry(entry.clone())
          .or_insert_with(Vec::new)
          .push(Diagnostic {
            params: params.clone(),
            reason: format!(
              "no rule was available to compute {} with parameter type{} {}",
              type_constraint_str(product.clone()),
              if params.len() > 1 { "s" } else { "" },
              params_str(&params),
            ),
          });
        fulfillable = false;
      } else {
        // Extend the RuleEdges for this SelectKey.
        edges.add_edges_via(select_key, fulfillable_candidates);
      }
    }

    if fulfillable {
      // All dependencies were fulfillable: store the equivalence, and replace the placeholder.
      // TODO: Compute used parameters above and store them here.
      // TODO2: We also need to rewrite all edges with the new equivalence, because in cases where
      // we recursed on ourself, nodes will have dependencies on us.
      entry_equivalences.insert(entry.clone(), entry.clone());
      rule_dependency_edges.insert(entry.clone(), edges);
      Some(entry)
    } else {
      // Was not fulfillable. Remove the placeholder: the unfulfillable entries we stored will
      // prevent us from attempting to expand this node again.
      rule_dependency_edges.remove(&entry);
      None
    }
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
        clause: vec![Select {
          product: *product_type,
          variant_key: None,
        }],
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
  params
    .iter()
    .map(|type_id| type_str(type_id.clone()))
    .collect::<Vec<_>>()
    .join("+")
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
    type_str(get.subject)
  )
}

fn entry_str(entry: &Entry) -> String {
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
    }) => format!("{} of {}", task_display(task_rule), params_str(params)),
    &EntryWithDeps::Inner(InnerEntry {
      rule: Rule::Intrinsic(ref intrinsic),
      ref params,
    }) => format!(
      "({}, ({},), {:?}) for {}",
      type_constraint_str(intrinsic.product),
      type_constraint_str(intrinsic.input),
      intrinsic.kind,
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
  pub fn new(tasks: &Tasks, root_subject_types: Vec<TypeId>) -> RuleGraph {
    GraphMaker::new(tasks, root_subject_types).full_graph()
  }

  pub fn find_root_edges(&self, subject_type: TypeId, select: Select) -> Option<RuleEdges> {
    // TODO: Support more than one root parameter... needs some API work.
    let root = RootEntry {
      params: vec![subject_type].into_iter().collect(),
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
      self.rule_dependency_edges.get(e).cloned()
    } else {
      panic!("not an inner entry! {:?}", entry)
    }
  }

  pub fn validate(&self) -> Result<(), String> {
    let mut collated_errors: HashMap<Task, Vec<String>> = HashMap::new();

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
        collated_errors
          .entry(task_rule.clone())
          .or_insert_with(Vec::new)
          .push(d.reason.clone());
      }
    }

    if collated_errors.is_empty() {
      return Ok(());
    }

    let mut msgs: Vec<String> = collated_errors
      .into_iter()
      .map(|(rule, mut errors)| {
        errors.sort();
        format!("{}:\n    {}", task_display(&rule), errors.join("\n    "))
      })
      .collect();
    msgs.sort();

    Err(format!("Rules with errors: {}\n  {}", msgs.len(), msgs.join("\n  ")).to_string())
  }

  pub fn visualize(&self, f: &mut io::Write) -> io::Result<()> {
    if self.rule_dependency_edges.is_empty() {
      writeln!(f, "digraph {{")?;
      writeln!(f, "  // empty graph")?;
      writeln!(f, "}}")?;
    }

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
    writeln!(f, "{}", root_rule_strs.join("\n"))?;

    writeln!(f, "  // internal entries")?;
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
    writeln!(f, "{}", internal_rule_strs.join("\n"))?;
    writeln!(f, "}}")
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

  pub fn entries_for(&self, select_key: &SelectKey, param_values: &Params) -> Entries {
    self
      .dependencies_by_select_key
      .get(select_key)
      .map(|entries| {
        entries
          .into_iter()
          .filter(|&entry| match entry {
            &Entry::WithDeps(EntryWithDeps::Root(RootEntry { ref params, .. }))
            | &Entry::WithDeps(EntryWithDeps::Inner(InnerEntry { ref params, .. })) => params
              .iter()
              .all(|type_id| param_values.find(*type_id).is_some()),
            &Entry::Param(type_id) => param_values.find(type_id).is_some(),
            &Entry::Singleton { .. } => true,
          })
          .cloned()
          .collect()
      })
      .unwrap_or_else(Vec::new)
  }

  pub fn is_empty(&self) -> bool {
    self.dependencies.is_empty()
  }

  fn add_edges_via(&mut self, select_key: SelectKey, new_dependencies: Entries) {
    let deps_for_selector = self
      .dependencies_by_select_key
      .entry(select_key)
      .or_insert_with(Vec::new);
    for d in new_dependencies {
      if !deps_for_selector.contains(&d) {
        deps_for_selector.push(d.clone());
      }
      if !self.dependencies.contains(&d) {
        self.dependencies.push(d);
      }
    }
  }
}

fn rhs(tasks: &Tasks, params: &ParamTypes, product_type: &TypeConstraint) -> Entries {
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
