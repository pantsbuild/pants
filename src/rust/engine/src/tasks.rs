// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::{collections::HashMap, fmt};

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

// Map of base rule -> map of derived type to derived rule for that type.
type VTable = HashMap<RuleId, HashMap<TypeId, RuleId>>;

///
/// Registry of user Tasks.
///
#[derive(Clone, Debug)]
pub struct Tasks {
    rules: IndexSet<Rule>,
    queries: IndexSet<Query<TypeId>>,
    vtable: VTable,
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
            queries: IndexSet::default(),
            vtable: VTable::default(),
            preparing: None,
        }
    }

    pub fn rules(&self) -> &IndexSet<Rule> {
        &self.rules
    }

    pub fn queries(&self) -> &IndexSet<Query<TypeId>> {
        &self.queries
    }

    pub fn vtable(&self) -> &VTable {
        &self.vtable
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
        rule_id: RuleId,
        explicit_args_arity: u16,
        vtable_entries: Option<HashMap<TypeId, RuleId>>,
        in_scope_types: Option<Vec<TypeId>>,
    ) {
        let calls = &mut self
            .preparing
            .as_mut()
            .expect("Must `begin()` a task creation before adding calls!")
            .gets;

        if let Some(vtable_entries) = vtable_entries {
            // This is a polymorphic call, so in_scope_types must be provided by the caller.
            // TODO: We would like to deprecate the in_scope_types argument to the @union decorator,
            // and instead let the in-scope types be defined by the signature of the polymorphic
            // rule (i.e., they would be the explicit params in the signature other than the union
            // type). However this would require access to the rule's signature (which is distinct
            // from the call's signature) both here and in gen_call() in task.rs. So for now we
            // continue to use the legacy in_scope_types @union arg, and we can revisit once we're
            // fully call-by-name.
            // See https://github.com/pantsbuild/pants/issues/22483
            let in_scope_types = in_scope_types.unwrap_or_else(|| {
                panic!("No in_scope_types passed in for a polymorphic call");
            });

            // Note that the Python code calling this function has already verified that there
            // is a relevant union type in the inputs, so this should never panic in practice.
            let union_type = inputs.iter().find(|t| t.is_union()).unwrap_or_else(|| {
                panic!("No union argument found in inputs of call to {rule_id}")
            });
            // Add calls for each vtable member. At runtime we'll select the relevant one.
            for (member_type, member_rule) in vtable_entries.iter() {
                let member_rule_inputs = inputs
                    .iter()
                    .map(|t| if t == union_type { member_type } else { t })
                    .map(TypeId::clone)
                    .collect::<Vec<TypeId>>();
                calls.push(
                    DependencyKey::for_known_rule(member_rule.clone(), output, explicit_args_arity)
                        .provided_params(member_rule_inputs)
                        .in_scope_params(in_scope_types.clone()),
                );
            }
            self.vtable.insert(rule_id.clone(), vtable_entries);

            // Add the polymorphic call itself.
            calls.push(
                DependencyKey::for_known_rule(rule_id, output, explicit_args_arity)
                    .provided_params(inputs)
                    .in_scope_params(in_scope_types.clone()),
            );
        } else {
            calls.push(
                DependencyKey::for_known_rule(rule_id, output, explicit_args_arity)
                    .provided_params(inputs),
            );
        }
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
