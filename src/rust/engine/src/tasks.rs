// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;

use crate::intrinsics::Intrinsics;
use crate::python::{Function, TypeId};

use deepsize::DeepSizeOf;
use indexmap::IndexSet;
use internment::Intern;
use log::Level;
use rule_graph::{DependencyKey, DisplayForGraph, DisplayForGraphArgs, Query};

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

                let clause_portion = Self::formatted_positional_arguments(&task.args, display_args);

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
                Self::formatted_positional_arguments(&intrinsic.inputs, display_args),
                intrinsic.product,
            ),
        }
    }
}

impl rule_graph::Rule for Rule {
    type TypeId = TypeId;

    fn product(&self) -> TypeId {
        match self {
            Rule::Task(t) => t.product,
            Rule::Intrinsic(i) => i.product,
        }
    }

    fn dependency_keys(&self) -> Vec<&DependencyKey<Self::TypeId>> {
        match self {
            Rule::Task(task) => task.args.iter().chain(task.gets.iter()).collect(),
            Rule::Intrinsic(intrinsic) => intrinsic.inputs.iter().collect(),
        }
    }

    fn masked_params(&self) -> Vec<Self::TypeId> {
        match self {
            Rule::Task(task) => task.masked_types.clone(),
            Rule::Intrinsic(_) => vec![],
        }
    }

    fn require_reachable(&self) -> bool {
        match self {
            Rule::Task(_) => true,
            Rule::Intrinsic(_) => false,
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
    fn formatted_positional_arguments(
        clause: &[DependencyKey<TypeId>],
        display_args: DisplayForGraphArgs,
    ) -> String {
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
    pub args: Vec<DependencyKey<TypeId>>,
    pub gets: Vec<DependencyKey<TypeId>>,
    pub masked_types: Vec<TypeId>,
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
    pub inputs: Vec<DependencyKey<TypeId>>,
}

impl Intrinsic {
    pub fn new(product: TypeId, input: TypeId) -> Self {
        Self {
            product,
            inputs: vec![DependencyKey::new(input)],
        }
    }
}

///
/// Registry of native (rust) Intrinsic tasks and user (python) Tasks.
///
#[derive(Clone, Debug)]
pub struct Tasks {
    rules: IndexSet<Rule>,
    queries: IndexSet<Query<TypeId>>,
    // Used during the construction of a rule.
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
            rules: IndexSet::default(),
            preparing: None,
            queries: IndexSet::default(),
        }
    }

    pub fn rules(&self) -> &IndexSet<Rule> {
        &self.rules
    }

    pub fn queries(&self) -> &IndexSet<Query<TypeId>> {
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
        arg_types: Vec<TypeId>,
        masked_types: Vec<TypeId>,
        cacheable: bool,
        name: String,
        desc: Option<String>,
        level: Level,
    ) {
        assert!(
            self.preparing.is_none(),
            "Must `end()` the previous task creation before beginning a new one!"
        );
        let args = arg_types.into_iter().map(DependencyKey::new).collect();

        self.preparing = Some(Task {
            cacheable,
            product: return_type,
            side_effecting,
            engine_aware_return_type,
            args,
            gets: Vec::new(),
            masked_types,
            func,
            display_info: DisplayInfo { name, desc, level },
        });
    }

    pub fn add_get(&mut self, output: TypeId, inputs: Vec<TypeId>) {
        self.preparing
            .as_mut()
            .expect("Must `begin()` a task creation before adding gets!")
            .gets
            .push(DependencyKey::new(output).provided_params(inputs));
    }

    pub fn add_get_union(&mut self, output: TypeId, inputs: Vec<TypeId>, in_scope: Vec<TypeId>) {
        self.preparing
            .as_mut()
            .expect("Must `begin()` a task creation before adding a union get!")
            .gets
            .push(
                DependencyKey::new(output)
                    .provided_params(inputs)
                    .in_scope_params(in_scope),
            );
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
