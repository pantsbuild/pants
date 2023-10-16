// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;

use crate::intrinsics::Intrinsics;
use crate::python::{Function, TypeId};
use crate::selectors::{DependencyKey, Get, Select};

use deepsize::DeepSizeOf;
use indexmap::IndexSet;
use internment::Intern;
use log::Level;
use rule_graph::{DisplayForGraph, DisplayForGraphArgs, Query};

#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug)]
pub enum Rule {
    // Intrinsic rules are implemented in rust.
    Intrinsic(Intern<Intrinsic>),
    // Task rules are implemented in python.
    Task(Intern<Task>),
}

impl DisplayForGraph for Rule {
    fn fmt_for_graph(&self, display_args: DisplayForGraphArgs) -> String {
        match self {
            Rule::Task(ref task) => {
                let task_name = task.func.full_name();
                let product = format!("{}", task.product);

                let clause_portion = Self::formatted_select_clause(&task.clause, display_args);

                let get_clauses = task
                    .gets
                    .iter()
                    .map(::std::string::ToString::to_string)
                    .collect::<Vec<_>>();

                let get_portion = if get_clauses.is_empty() {
                    "".to_string()
                } else if get_clauses.len() > 1 {
                    format!(
                        ",{}gets=[{}{}{}]",
                        display_args.line_separator(),
                        display_args.optional_line_separator(),
                        get_clauses.join(&format!(",{}", display_args.line_separator())),
                        display_args.optional_line_separator(),
                    )
                } else {
                    format!(", gets=[{}]", get_clauses.join(", "))
                };

                let rule_type = if task.cacheable {
                    "rule".to_string()
                } else {
                    "goal_rule".to_string()
                };

                format!(
                    "@{}({}({}) -> {}{})",
                    rule_type, task_name, clause_portion, product, get_portion,
                )
            }
            Rule::Intrinsic(ref intrinsic) => format!(
                "@rule(<intrinsic>({}) -> {})",
                Self::formatted_select_clause(&intrinsic.inputs, display_args),
                intrinsic.product,
            ),
        }
    }
}

impl rule_graph::Rule for Rule {
    type TypeId = TypeId;
    type DependencyKey = DependencyKey;

    fn product(&self) -> TypeId {
        match self {
            Rule::Task(t) => t.product,
            Rule::Intrinsic(i) => i.product,
        }
    }

    fn dependency_keys(&self) -> Vec<DependencyKey> {
        match self {
            &Rule::Task(task) => task
                .clause
                .iter()
                .map(|t| DependencyKey::JustSelect(Select::new(*t)))
                .chain(task.gets.iter().map(|g| DependencyKey::JustGet(*g)))
                .collect(),
            &Rule::Intrinsic(intrinsic) => intrinsic
                .inputs
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

impl Rule {
    fn formatted_select_clause(clause: &[TypeId], display_args: DisplayForGraphArgs) -> String {
        let select_clauses = clause
            .iter()
            .map(|type_id| type_id.to_string())
            .collect::<Vec<_>>();

        if select_clauses.len() > 1 {
            format!(
                "{}{}{}",
                display_args.optional_line_separator(),
                select_clauses.join(&format!(",{}", display_args.line_separator())),
                display_args.optional_line_separator(),
            )
        } else {
            select_clauses.join(", ")
        }
    }
}

impl fmt::Display for Rule {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        write!(
            f,
            "{}",
            self.fmt_for_graph(DisplayForGraphArgs { multiline: false })
        )
    }
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Task {
    pub product: TypeId,
    pub side_effecting: bool,
    pub engine_aware_return_type: bool,
    pub clause: Vec<TypeId>,
    pub gets: Vec<Get>,
    // TODO: This is a preliminary implementation of #12934: we should overhaul naming to
    // align Query and @union/Protocol as described there.
    pub unions: Vec<Query<Rule>>,
    pub func: Function,
    pub cacheable: bool,
    pub display_info: DisplayInfo,
}

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct DisplayInfo {
    pub name: String,
    pub desc: Option<String>,
    pub level: Level,
}

#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug)]
pub struct Intrinsic {
    pub product: TypeId,
    pub inputs: Vec<TypeId>,
}

///
/// Registry of native (rust) Intrinsic tasks and user (python) Tasks.
///
#[derive(Clone, Debug)]
pub struct Tasks {
    rules: IndexSet<Rule>,
    // Used during the construction of a rule.
    preparing: Option<Task>,
    queries: IndexSet<Query<Rule>>,
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
            rules: IndexSet::default(),
            preparing: None,
            queries: IndexSet::default(),
        }
    }

    pub fn rules(&self) -> &IndexSet<Rule> {
        &self.rules
    }

    pub fn queries(&self) -> &IndexSet<Query<Rule>> {
        &self.queries
    }

    pub fn intrinsics_set(&mut self, intrinsics: &Intrinsics) {
        for intrinsic in intrinsics.keys() {
            self.rules
                .insert(Rule::Intrinsic(Intern::new(intrinsic.clone())));
        }
    }

    ///
    /// The following methods define the Task registration lifecycle.
    ///
    pub fn task_begin(
        &mut self,
        func: Function,
        return_type: TypeId,
        side_effecting: bool,
        engine_aware_return_type: bool,
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
            product: return_type,
            side_effecting,
            engine_aware_return_type,
            clause: Vec::new(),
            gets: Vec::new(),
            unions: Vec::new(),
            func,
            display_info: DisplayInfo { name, desc, level },
        });
    }

    pub fn add_get(&mut self, output: TypeId, input: TypeId) {
        self.preparing
            .as_mut()
            .expect("Must `begin()` a task creation before adding gets!")
            .gets
            .push(Get { output, input });
    }

    pub fn add_union(&mut self, product: TypeId, params: Vec<TypeId>) {
        let query = Query::new(product, params);
        self.queries.insert(query.clone());
        self.preparing
            .as_mut()
            .expect("Must `begin()` a task creation before adding unions!")
            .unions
            .push(query);
    }

    pub fn add_select(&mut self, selector: TypeId) {
        self.preparing
            .as_mut()
            .expect("Must `begin()` a task creation before adding clauses!")
            .clause
            .push(selector);
    }

    pub fn task_end(&mut self) {
        // Move the task from `preparing` to the Rules map
        let task = self
            .preparing
            .take()
            .expect("Must `begin()` a task creation before ending it!");
        self.rules.insert(Rule::Task(Intern::new(task)));
    }

    pub fn query_add(&mut self, product: TypeId, params: Vec<TypeId>) {
        self.queries.insert(Query::new(product, params));
    }
}
