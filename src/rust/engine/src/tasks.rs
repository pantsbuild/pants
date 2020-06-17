// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::fmt;

use crate::core::{Function, TypeId};
use crate::intrinsics::Intrinsics;
use crate::selectors::{DependencyKey, Get, Select};

use log::Level;

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum Rule {
  // Intrinsic rules are implemented in rust.
  Intrinsic(Intrinsic),
  // Task rules are implemented in python.
  Task(Task),
}

impl rule_graph::DisplayForGraph for Rule {
  fn fmt_for_graph(&self) -> String {
    let visualization_params = Some(GraphVisualizationParameters {
      select_clause_threshold: 2,
      get_clause_threshold: 1,
    });
    match self {
      Rule::Task(ref task) => {
        let FormattedTaskRuleElements {
          rule_type,
          task_name,
          clause_portion,
          product,
          get_portion,
        } = Self::extract_task_elements(task, visualization_params);

        format!(
          "@{}({}) -> {}{}\n{}",
          rule_type, clause_portion, product, get_portion, task_name,
        )
      }
      Rule::Intrinsic(ref intrinsic) => format!(
        "@rule(<intrinsic>({}) -> {})",
        Self::formatted_select_clause(&intrinsic.inputs, visualization_params),
        intrinsic.product,
      ),
    }
  }
}

impl rule_graph::Rule for Rule {
  type TypeId = TypeId;
  type DependencyKey = DependencyKey;

  fn dependency_keys(&self) -> Vec<DependencyKey> {
    match self {
      &Rule::Task(Task {
        ref clause,
        ref gets,
        ..
      }) => clause
        .iter()
        .map(|t| DependencyKey::JustSelect(Select::new(*t)))
        .chain(gets.iter().map(|g| DependencyKey::JustGet(*g)))
        .collect(),
      &Rule::Intrinsic(Intrinsic { ref inputs, .. }) => inputs
        .iter()
        .map(|t| DependencyKey::JustSelect(Select::new(*t)))
        .collect(),
    }
  }

  fn require_reachable(&self) -> bool {
    match self {
      &Rule::Task(_) => true,
      &Rule::Intrinsic(_) => false,
    }
  }

  fn color(&self) -> Option<rule_graph::Palette> {
    match self {
      Rule::Task(_) => None,
      Rule::Intrinsic(_) => Some(rule_graph::Palette::Gray),
    }
  }
}

///
/// A helper struct to contain stringified versions of various components of the rule.
///
struct FormattedTaskRuleElements {
  rule_type: String,
  task_name: String,
  clause_portion: String,
  product: String,
  get_portion: String,
}

///
/// A struct to contain display options consumed by Rule::extract_task_elements().
///
#[derive(Clone, Copy)]
struct GraphVisualizationParameters {
  ///
  /// The number of params in the rule to keep on the same output line before splitting by line. If
  /// the rule uses more than this many params, each param will be formatted on its own
  /// line. Otherwise, all of the params will be formatted on the same line.
  ///
  select_clause_threshold: usize,
  ///
  /// The number of Get clauses to keep on the same output line before splitting by line.
  ///
  get_clause_threshold: usize,
}

impl Rule {
  fn formatted_select_clause(
    clause: &[TypeId],
    visualization_params: Option<GraphVisualizationParameters>,
  ) -> String {
    let select_clauses = clause
      .iter()
      .map(|type_id| type_id.to_string())
      .collect::<Vec<_>>();
    let select_clause_threshold = visualization_params.map(|p| p.select_clause_threshold);

    match select_clause_threshold {
      None => select_clauses.join(", "),
      Some(select_clause_threshold) if select_clauses.len() <= select_clause_threshold => {
        select_clauses.join(", ")
      }
      Some(_) => format!("\n{},\n", select_clauses.join(",\n")),
    }
  }

  fn extract_task_elements(
    task: &Task,
    visualization_params: Option<GraphVisualizationParameters>,
  ) -> FormattedTaskRuleElements {
    let product = format!("{}", task.product);

    let clause_portion = Self::formatted_select_clause(&task.clause, visualization_params);

    let get_clauses = task
      .gets
      .iter()
      .map(::std::string::ToString::to_string)
      .collect::<Vec<_>>();
    let get_clause_threshold = visualization_params.map(|p| p.get_clause_threshold);

    let get_portion = if get_clauses.is_empty() {
      "".to_string()
    } else {
      match get_clause_threshold {
        None => format!(", gets=[{}]", get_clauses.join(", ")),
        Some(get_clause_threshold) if get_clauses.len() <= get_clause_threshold => {
          format!(",\ngets=[{}]", get_clauses.join(", "))
        }
        Some(_) => format!(",\ngets=[\n{},\n]", get_clauses.join("\n")),
      }
    };

    let rule_type = if task.cacheable {
      "rule".to_string()
    } else {
      "goal_rule".to_string()
    };

    FormattedTaskRuleElements {
      rule_type,
      task_name: task.func.name(),
      clause_portion,
      product,
      get_portion,
    }
  }
}

impl fmt::Display for Rule {
  fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
    match self {
      &Rule::Task(ref task) => {
        let FormattedTaskRuleElements {
          rule_type,
          task_name,
          clause_portion,
          product,
          get_portion,
        } = Self::extract_task_elements(task, None);
        write!(
          f,
          "@{}({}({}) -> {}{})",
          rule_type, task_name, clause_portion, product, get_portion,
        )
      }
      &Rule::Intrinsic(ref intrinsic) => write!(
        f,
        "@rule(<intrinsic>({}) -> {})",
        Self::formatted_select_clause(&intrinsic.inputs, None),
        intrinsic.product,
      ),
    }
  }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Task {
  pub product: TypeId,
  pub can_modify_workunit: bool,
  pub clause: Vec<TypeId>,
  pub gets: Vec<Get>,
  pub func: Function,
  pub cacheable: bool,
  pub display_info: DisplayInfo,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct DisplayInfo {
  pub name: String,
  pub desc: Option<String>,
  pub level: Level,
}

#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub struct Intrinsic {
  pub product: TypeId,
  pub inputs: Vec<TypeId>,
}

///
/// Registry of native (rust) Intrinsic tasks and user (python) Tasks.
///
#[derive(Clone, Debug)]
pub struct Tasks {
  // output product type -> list of rules providing it
  rules: HashMap<TypeId, Vec<Rule>>,
  // Used during the construction of the tasks map.
  preparing: Option<Task>,
}

///
/// A collection of Rules (TODO: rename to Rules).
///
/// Defines a stateful lifecycle for defining tasks via the C api. Call in order:
///   1. task_begin() - once per task
///   2. add_*() - zero or more times per task to add input clauses
///   3. task_end() - once per task
///
/// (This protocol was original defined in a Builder, but that complicated the C lifecycle.)
///
impl Tasks {
  pub fn new() -> Tasks {
    Tasks {
      rules: HashMap::default(),
      preparing: None,
    }
  }

  pub fn as_map(&self) -> &HashMap<TypeId, Vec<Rule>> {
    &self.rules
  }

  pub fn intrinsics_set(&mut self, intrinsics: &Intrinsics) {
    for intrinsic in intrinsics.keys() {
      self.insert_rule(intrinsic.product, Rule::Intrinsic(intrinsic.clone()))
    }
  }

  ///
  /// The following methods define the Task registration lifecycle.
  ///
  pub fn task_begin(
    &mut self,
    func: Function,
    product: TypeId,
    can_modify_workunit: bool,
    cacheable: bool,
    name: String,
    desc: Option<String>,
    level: Level,
  ) {
    assert!(
      self.preparing.is_none(),
      "Must `end()` the previous task creation before beginning a new one!"
    );

    self.preparing = Some(Task {
      cacheable,
      product,
      can_modify_workunit,
      clause: Vec::new(),
      gets: Vec::new(),
      func,
      display_info: DisplayInfo { name, desc, level },
    });
  }

  pub fn add_get(&mut self, product: TypeId, subject: TypeId) {
    self
      .preparing
      .as_mut()
      .expect("Must `begin()` a task creation before adding gets!")
      .gets
      .push(Get { product, subject });
  }

  pub fn add_select(&mut self, product: TypeId) {
    self
      .preparing
      .as_mut()
      .expect("Must `begin()` a task creation before adding clauses!")
      .clause
      .push(product);
  }

  pub fn task_end(&mut self) {
    // Move the task from `preparing` to the Rules map
    let task = self
      .preparing
      .take()
      .expect("Must `begin()` a task creation before ending it!");
    self.insert_rule(task.product, Rule::Task(task))
  }

  fn insert_rule(&mut self, product: TypeId, rule: Rule) {
    let rules = self.rules.entry(product).or_insert_with(Vec::new);
    assert!(
      !rules.contains(&rule),
      "{:?} was double-registered for {:?}: {:?}",
      rule,
      product,
      rules,
    );
    rules.push(rule);
  }
}
