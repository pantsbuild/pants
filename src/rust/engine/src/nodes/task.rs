// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use deepsize::DeepSizeOf;
use futures::future::{self, BoxFuture, FutureExt};
use graph::CompoundNode;
use internment::Intern;
use pyo3::prelude::{PyErr, Python};
use pyo3::types::{PyDict, PyTuple};
use pyo3::{IntoPy, ToPyObject};
use rule_graph::DependencyKey;
use workunit_store::{in_workunit, Level, RunningWorkunit};

use super::{select, task_context, NodeKey, NodeResult, Params};
use crate::context::Context;
use crate::externs::engine_aware::EngineAwareReturnType;
use crate::externs::{self, GeneratorInput, GeneratorResponse};
use crate::python::{throw, Failure, Key, TypeId, Value};
use crate::tasks::{self, Rule};

#[derive(DeepSizeOf, Derivative, Clone)]
#[derivative(Eq, PartialEq, Hash)]
pub struct Task {
    pub params: Params,
    // A key for a tuple of explicit positional arguments.
    pub(super) args: Option<Key>,
    // The number of explicit positional arguments.
    pub(super) args_arity: u16,
    pub(super) task: Intern<tasks::Task>,
    // The Params and the Task struct are sufficient to uniquely identify it.
    #[derivative(PartialEq = "ignore", Hash = "ignore")]
    pub(super) entry: Intern<rule_graph::Entry<Rule>>,
    // Does not affect the identity of the Task.
    #[derivative(PartialEq = "ignore", Hash = "ignore")]
    pub(super) side_effected: Arc<AtomicBool>,
}

impl Task {
    // Handles the case where a generator requests a `Call` to a known `@rule`.
    async fn gen_call(
        context: &Context,
        mut params: Params,
        entry: Intern<rule_graph::Entry<Rule>>,
        call: externs::Call,
    ) -> NodeResult<Value> {
        let context = context.clone();
        let dependency_key =
            DependencyKey::for_known_rule(call.rule_id.clone(), call.output_type, call.args_arity)
                .provided_params(call.inputs.iter().map(|t| *t.type_id()));
        params.extend(call.inputs.iter().cloned());

        let edges = context
            .core
            .rule_graph
            .edges_for_inner(&entry)
            .ok_or_else(|| throw(format!("No edges for task {entry:?} exist!")))?;

        // Find the entry for the Call.
        let entry = edges.entry_for(&dependency_key).ok_or_else(|| {
            // NB: The Python constructor for `Call()` will have already errored if
            // `type(input) != input_type`.
            throw(format!(
                "{call} was not detected in your @rule body at rule compile time."
            ))
        })?;
        select(context, call.args, call.args_arity, params, entry).await
    }

    // Handles the case where a generator produces a `Get` for an unknown `@rule`.
    async fn gen_get(
        context: &Context,
        mut params: Params,
        entry: Intern<rule_graph::Entry<Rule>>,
        get: externs::Get,
    ) -> NodeResult<Value> {
        let dependency_key =
            DependencyKey::new(get.output).provided_params(get.inputs.iter().map(|t| *t.type_id()));
        params.extend(get.inputs.iter().cloned());

        let edges = context
            .core
            .rule_graph
            .edges_for_inner(&entry)
            .ok_or_else(|| throw(format!("No edges for task {entry:?} exist!")))?;

        // Find the entry for the Get.
        let entry = edges
            .entry_for(&dependency_key)
            .or_else(|| {
                // The Get might have involved a @union: if so, include its in_scope types in the
                // lookup.
                let in_scope_types = get
                    .input_types
                    .iter()
                    .find_map(|t| t.union_in_scope_types())?;
                edges.entry_for(
                    &DependencyKey::new(get.output)
                        .provided_params(get.inputs.iter().map(|k| *k.type_id()))
                        .in_scope_params(in_scope_types),
                )
            })
            .ok_or_else(|| {
                if get.input_types.iter().any(|t| t.is_union()) {
                    throw(format!(
            "Invalid Get. Because an input type for `{get}` was annotated with `@union`, \
             the value for that type should be a member of that union. Did you \
             intend to register a `UnionRule`? If not, you may be using the incorrect \
             explicitly declared type.",
          ))
                } else {
                    // NB: The Python constructor for `Get()` will have already errored if
                    // `type(input) != input_type`.
                    throw(format!(
                        "{get} was not detected in your @rule body at rule compile time. \
             Was the `Get` constructor called in a non async-function, or \
             was it inside an async function defined after the @rule? \
             Make sure the `Get` is defined before or inside the @rule body.",
                    ))
                }
            })?;
        select(context.clone(), None, 0, params, entry).await
    }

    // Handles the case where a generator produces either a `Get` or a generator.
    fn gen_get_or_generator(
        context: &Context,
        params: Params,
        entry: Intern<rule_graph::Entry<Rule>>,
        gog: externs::GetOrGenerator,
    ) -> BoxFuture<NodeResult<Value>> {
        async move {
            match gog {
                externs::GetOrGenerator::Get(get) => {
                    Self::gen_get(context, params, entry, get).await
                }
                externs::GetOrGenerator::Generator(generator) => {
                    // TODO: The generator may run concurrently with any other generators requested in an
                    // `All`/`MultiGet` (due to `future::try_join_all`), and so it needs its own workunit.
                    // Should look into removing this constraint: possibly by running all generators from an
                    // `All` on a tokio `LocalSet`.
                    in_workunit!("generator", Level::Trace, |workunit| async move {
                        let (value, _type_id) =
                            Self::generate(context, workunit, params, entry, generator).await?;
                        Ok(value)
                    })
                    .await
                }
            }
        }
        .boxed()
    }

    ///
    /// Given a python generator Value, loop to request the generator's dependencies until
    /// it completes with a result Value or fails with an error.
    ///
    async fn generate(
        context: &Context,
        workunit: &mut RunningWorkunit,
        params: Params,
        entry: Intern<rule_graph::Entry<Rule>>,
        generator: Value,
    ) -> NodeResult<(Value, TypeId)> {
        let mut input = GeneratorInput::Initial;
        loop {
            let response = Python::with_gil(|py| {
                externs::generator_send(py, &context.core.types.coroutine, &generator, input)
            })?;
            match response {
                GeneratorResponse::NativeCall(call) => {
                    let _blocking_token = workunit.blocking();
                    let result = (call.call).await;
                    match result {
                        Ok(value) => {
                            input = GeneratorInput::Arg(value);
                        }
                        Err(throw @ Failure::Throw { .. }) => {
                            input = GeneratorInput::Err(PyErr::from(throw));
                        }
                        Err(failure) => break Err(failure),
                    }
                }
                GeneratorResponse::Call(call) => {
                    let _blocking_token = workunit.blocking();
                    let result = Self::gen_call(context, params.clone(), entry, call).await;
                    match result {
                        Ok(value) => {
                            input = GeneratorInput::Arg(value);
                        }
                        Err(throw @ Failure::Throw { .. }) => {
                            input = GeneratorInput::Err(PyErr::from(throw));
                        }
                        Err(failure) => break Err(failure),
                    }
                }
                GeneratorResponse::Get(get) => {
                    let _blocking_token = workunit.blocking();
                    let result = Self::gen_get(context, params.clone(), entry, get).await;
                    match result {
                        Ok(value) => {
                            input = GeneratorInput::Arg(value);
                        }
                        Err(throw @ Failure::Throw { .. }) => {
                            input = GeneratorInput::Err(PyErr::from(throw));
                        }
                        Err(failure) => break Err(failure),
                    }
                }
                GeneratorResponse::All(gogs) => {
                    let _blocking_token = workunit.blocking();
                    let get_futures = gogs
                        .into_iter()
                        .map(|gog| Self::gen_get_or_generator(context, params.clone(), entry, gog))
                        .collect::<Vec<_>>();
                    match future::try_join_all(get_futures).await {
                        Ok(values) => {
                            input = GeneratorInput::Arg(Python::with_gil(|py| {
                                externs::store_tuple(py, values)
                            }));
                        }
                        Err(throw @ Failure::Throw { .. }) => {
                            input = GeneratorInput::Err(PyErr::from(throw));
                        }
                        Err(failure) => break Err(failure),
                    }
                }
                GeneratorResponse::Break(val, type_id) => {
                    break Ok((val, type_id));
                }
            }
        }
    }

    pub(super) async fn run_node(
        self,
        context: Context,
        workunit: &mut RunningWorkunit,
    ) -> NodeResult<Value> {
        let params = self.params;
        let deps = {
            // While waiting for dependencies, mark ourselves blocking.
            let _blocking_token = workunit.blocking();
            let edges = &context
                .core
                .rule_graph
                .edges_for_inner(&self.entry)
                .expect("edges for task exist.");
            future::try_join_all(
                self.task
                    .args
                    .iter()
                    .skip(self.args_arity.into())
                    .map(|(_name, dependency_key)| {
                        let entry = edges.entry_for(dependency_key).unwrap_or_else(|| {
                            panic!(
                                "{:?} did not declare a dependency on {dependency_key:?}",
                                self.task
                            )
                        });
                        select(context.clone(), None, 0, params.clone(), entry)
                    })
                    .collect::<Vec<_>>(),
            )
            .await?
        };

        let args = self.args;

        let (mut result_val, mut result_type) = task_context(
            context.clone(),
            self.task.side_effecting,
            &self.side_effected,
            async move {
                Python::with_gil(|py| {
                    let func = (*self.task.func.0.value).as_ref(py);

                    // If there are explicit positional arguments, apply any computed arguments as
                    // keywords. Otherwise, apply computed arguments as positional.
                    let res = if let Some(args) = args {
                        let args = args.value.extract::<&PyTuple>(py)?;
                        let kwargs = PyDict::new(py);
                        for ((name, _), value) in self
                            .task
                            .args
                            .iter()
                            .skip(self.args_arity.into())
                            .zip(deps.into_iter())
                        {
                            kwargs.set_item(name, &value)?;
                        }
                        func.call(args, Some(kwargs))
                    } else {
                        let args_tuple = PyTuple::new(py, deps.iter().map(|v| v.to_object(py)));
                        func.call1(args_tuple)
                    };

                    res.map(|res| {
                        let type_id = TypeId::new(res.get_type());
                        let val = Value::new(res.into_py(py));
                        (val, type_id)
                    })
                    .map_err(Failure::from)
                })
            },
        )
        .await?;

        if result_type == context.core.types.coroutine {
            let (new_val, new_type) = task_context(
                context.clone(),
                self.task.side_effecting,
                &self.side_effected,
                Self::generate(&context, workunit, params, self.entry, result_val),
            )
            .await?;
            result_val = new_val;
            result_type = new_type;
        }

        if result_type != self.task.product {
            return Err(externs::IncorrectProductError::new_err(format!(
                "{:?} returned a result value that did not satisfy its constraints: {:?}",
                self.task.func, result_val
            ))
            .into());
        }

        if self.task.engine_aware_return_type {
            Python::with_gil(|py| {
                EngineAwareReturnType::update_workunit(workunit, (*result_val).as_ref(py))
            })
        };

        Ok(result_val)
    }
}

impl fmt::Debug for Task {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "Task {{ func: {}, params: {}, product: {}, cacheable: {} }}",
            self.task.func, self.params, self.task.product, self.task.cacheable,
        )
    }
}

impl CompoundNode<NodeKey> for Task {
    type Item = Value;
}

impl From<Task> for NodeKey {
    fn from(n: Task) -> Self {
        NodeKey::Task(Box::new(n))
    }
}
