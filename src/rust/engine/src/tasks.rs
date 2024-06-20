// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;

use crate::python::{Function, TypeId};

use deepsize::DeepSizeOf;
use indexmap::IndexSet;
use internment::Intern;
use log::Level;
use rule_graph::{DependencyKey, DisplayForGraph, DisplayForGraphArgs, Query, RuleId};

#[derive(DeepSizeOf, Eq, Hash, PartialEq, Clone, Debug)]
pub struct Rule(pub Intern<Task>);

impl DisplayForGraph for Rule {
    fn fmt_for_graph(&self, display_args: DisplayForGraphArgs) -> String {
        let task = &self.0;

        let task_name = task.func.full_name();
        let product = format!("{}", task.product);

        let clause_portion = Self::formatted_positional_arguments(
            task.args.iter().map(|(_name, dk)| dk),
            display_args,
        );

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

        format!("@{rule_type}({task_name}({clause_portion}) -> {product}{get_portion})",)
    }
}

impl rule_graph::Rule for Rule {
    type TypeId = TypeId;

    fn id(&self) -> &RuleId {
        &self.0.id
    }

    fn product(&self) -> TypeId {
        self.0.product
    }

    fn dependency_keys(&self, explicit_args_arity: u16) -> Vec<&DependencyKey<Self::TypeId>> {
        self.0
            .args
            .iter()
            .skip(explicit_args_arity.into())
            .map(|(_name, dk)| dk)
            .chain(self.0.gets.iter())
            .collect()
    }

    fn masked_params(&self) -> Vec<Self::TypeId> {
        self.0.masked_types.clone()
    }

    fn require_reachable(&self) -> bool {
        true
    }

    fn color(&self) -> Option<rule_graph::Palette> {
        None
    }
}

impl Rule {
    fn formatted_positional_arguments<'a, I: IntoIterator<Item = &'a DependencyKey<TypeId>>>(
        clause: I,
        display_args: DisplayForGraphArgs,
    ) -> String {
        let select_clauses = clause
            .into_iter()
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
    pub id: RuleId,
    pub product: TypeId,
    pub side_effecting: bool,
    pub engine_aware_return_type: bool,
    pub args: Vec<(String, DependencyKey<TypeId>)>,
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

///
/// Registry of user Tasks.
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
/// (This protocol was originally defined in a Builder, but that complicated the C lifecycle.)
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

    ///
    /// The following methods define the Task registration lifecycle.
    ///
    pub fn task_begin(
        &mut self,
        func: Function,
        return_type: TypeId,
        side_effecting: bool,
        engine_aware_return_type: bool,
        arg_types: Vec<(String, TypeId)>,
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
        let args = arg_types
            .into_iter()
            .map(|(name, typ)| (name, DependencyKey::new(typ)))
            .collect();

        self.preparing = Some(Task {
            id: RuleId::new(&name),
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

    pub fn add_call(
        &mut self,
        output: TypeId,
        inputs: Vec<TypeId>,
        rule_id: String,
        explicit_args_arity: u16,
    ) {
        let gets = &mut self
            .preparing
            .as_mut()
            .expect("Must `begin()` a task creation before adding calls!")
            .gets;
        gets.push(
            DependencyKey::for_known_rule(
                RuleId::from_string(rule_id),
                output,
                explicit_args_arity,
            )
            .provided_params(inputs),
        )
    }

    pub fn add_get(&mut self, output: TypeId, inputs: Vec<TypeId>) {
        let gets = &mut self
            .preparing
            .as_mut()
            .expect("Must `begin()` a task creation before adding gets!")
            .gets;
        gets.push(DependencyKey::new(output).provided_params(inputs));
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
        self.rules.insert(Rule(Intern::new(task)));
    }

    pub fn query_add(&mut self, product: TypeId, params: Vec<TypeId>) {
        self.queries.insert(Query::new(product, params));
    }
}
