// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::time::Duration;

use deepsize::DeepSizeOf;
use fs::RelativePath;
use graph::CompoundNode;
use process_execution::{
    self, CacheName, InputDigests, Process, ProcessCacheScope, ProcessExecutionStrategy,
    ProcessResultSource,
};
use pyo3::prelude::{PyAny, Python};
use store::{self, Store, StoreError};
use workunit_store::{
    Metric, ObservationMetric, RunningWorkunit, UserMetadataItem, WorkunitMetadata,
};

use super::{lift_directory_digest, NodeKey, NodeOutput, NodeResult};
use crate::context::Context;
use crate::externs;
use crate::python::{throw, Value};

/// A Node that represents a process to execute.
///
#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct ExecuteProcess {
    pub process: Process,
}

impl ExecuteProcess {
    async fn lift_process_input_digests(
        store: &Store,
        value: &Value,
    ) -> Result<InputDigests, StoreError> {
        let input_digests_fut: Result<_, String> = Python::with_gil(|py| {
            let value = (**value).as_ref(py);
            let input_files = lift_directory_digest(externs::getattr(value, "input_digest")?)
                .map_err(|err| format!("Error parsing input_digest {err}"))?;
            let immutable_inputs =
                externs::getattr_from_str_frozendict::<&PyAny>(value, "immutable_input_digests")
                    .into_iter()
                    .map(|(path, digest)| {
                        Ok((RelativePath::new(path)?, lift_directory_digest(digest)?))
                    })
                    .collect::<Result<BTreeMap<_, _>, String>>()?;
            let use_nailgun = externs::getattr::<Vec<String>>(value, "use_nailgun")?
                .into_iter()
                .map(RelativePath::new)
                .collect::<Result<BTreeSet<_>, _>>()?;

            Ok(InputDigests::new(
                store,
                input_files,
                immutable_inputs,
                use_nailgun,
            ))
        });

        input_digests_fut?
            .await
            .map_err(|e| e.enrich("Failed to merge input digests for process"))
    }

    fn lift_process_fields(
        value: &PyAny,
        input_digests: InputDigests,
        process_config: externs::process::PyProcessExecutionEnvironment,
    ) -> Result<Process, StoreError> {
        let env = externs::getattr_from_str_frozendict(value, "env");

        let working_directory = externs::getattr_as_optional_string(value, "working_directory")
            .map_err(|e| format!("Failed to get `working_directory` from field: {e}"))?
            .map(RelativePath::new)
            .transpose()?;

        let output_files = externs::getattr::<Vec<String>>(value, "output_files")?
            .into_iter()
            .map(RelativePath::new)
            .collect::<Result<_, _>>()?;

        let output_directories = externs::getattr::<Vec<String>>(value, "output_directories")?
            .into_iter()
            .map(RelativePath::new)
            .collect::<Result<_, _>>()?;

        let timeout_in_seconds: f64 = externs::getattr(value, "timeout_seconds")?;

        let timeout = if timeout_in_seconds < 0.0 {
            None
        } else {
            Some(Duration::from_millis((timeout_in_seconds * 1000.0) as u64))
        };

        let description: String = externs::getattr(value, "description")?;

        let py_level = externs::getattr(value, "level")?;

        let level = externs::val_to_log_level(py_level)?;

        let append_only_caches =
            externs::getattr_from_str_frozendict::<&str>(value, "append_only_caches")
                .into_iter()
                .map(|(name, dest)| Ok((CacheName::new(name)?, RelativePath::new(dest)?)))
                .collect::<Result<_, String>>()?;

        let jdk_home = externs::getattr_as_optional_string(value, "jdk_home")
            .map_err(|e| format!("Failed to get `jdk_home` from field: {e}"))?
            .map(PathBuf::from);

        let execution_slot_variable =
            externs::getattr_as_optional_string(value, "execution_slot_variable")
                .map_err(|e| format!("Failed to get `execution_slot_variable` for field: {e}"))?;

        let concurrency_available: usize = externs::getattr(value, "concurrency_available")?;

        let cache_scope: ProcessCacheScope = {
            let cache_scope_enum = externs::getattr(value, "cache_scope")?;
            externs::getattr::<String>(cache_scope_enum, "name")?.try_into()?
        };

        let remote_cache_speculation_delay = std::time::Duration::from_millis(
            externs::getattr::<i32>(value, "remote_cache_speculation_delay_millis")
                .map_err(|e| format!("Failed to get `name` for field: {e}"))? as u64,
        );

        let attempt = externs::getattr(value, "attempt").unwrap_or(0);

        Ok(Process {
            argv: externs::getattr(value, "argv").unwrap(),
            env,
            working_directory,
            input_digests,
            output_files,
            output_directories,
            timeout,
            description,
            level,
            append_only_caches,
            jdk_home,
            execution_slot_variable,
            concurrency_available,
            cache_scope,
            execution_environment: process_config.environment,
            remote_cache_speculation_delay,
            attempt,
        })
    }

    pub async fn lift(
        store: &Store,
        value: Value,
        process_config: externs::process::PyProcessExecutionEnvironment,
    ) -> Result<Self, StoreError> {
        let input_digests = Self::lift_process_input_digests(store, &value).await?;
        let process = Python::with_gil(|py| {
            Self::lift_process_fields((*value).as_ref(py), input_digests, process_config)
        })?;
        Ok(Self { process })
    }

    pub(super) async fn run_node(
        self,
        context: Context,
        workunit: &mut RunningWorkunit,
        backtrack_level: usize,
    ) -> NodeResult<ProcessResult> {
        let request = self.process;

        let command_runner = context
            .core
            .command_runners
            .get(backtrack_level)
            .ok_or_else(|| {
                // NB: We only backtrack for a Process if it produces a Digest which cannot be consumed
                // from disk: if we've fallen all the way back to local execution, and even that
                // produces an unreadable Digest, then there is a fundamental implementation issue.
                throw(format!(
          "Process {request:?} produced an invalid result on all configured command runners."
        ))
            })?;

        let execution_context = process_execution::Context::new(
            context.session.workunit_store(),
            context.session.build_id().to_string(),
            context.session.run_id(),
            context.session.tail_tasks(),
        );

        let res = command_runner
            .run(execution_context, workunit, request.clone())
            .await?;

        let definition = serde_json::to_string(&request)
            .map_err(|e| throw(format!("Failed to serialize process: {e}")))?;
        workunit.update_metadata(|initial| {
            initial.map(|(initial, level)| {
                let mut user_metadata = Vec::with_capacity(7);
                user_metadata.push((
                    "definition".to_string(),
                    UserMetadataItem::String(definition),
                ));
                user_metadata.push((
                    "source".to_string(),
                    UserMetadataItem::String(format!("{:?}", res.metadata.source)),
                ));
                user_metadata.push((
                    "exit_code".to_string(),
                    UserMetadataItem::Int(res.exit_code as i64),
                ));
                user_metadata.push((
                    "environment_type".to_string(),
                    UserMetadataItem::String(
                        res.metadata.environment.strategy.strategy_type().to_owned(),
                    ),
                ));
                if let Some(environment_name) = res.metadata.environment.name.clone() {
                    user_metadata.push((
                        "environment_name".to_string(),
                        UserMetadataItem::String(environment_name),
                    ));
                }
                if let Some(total_elapsed) = res.metadata.total_elapsed {
                    user_metadata.push((
                        "total_elapsed_ms".to_string(),
                        UserMetadataItem::Int(Duration::from(total_elapsed).as_millis() as i64),
                    ));
                }
                if let Some(saved_by_cache) = res.metadata.saved_by_cache {
                    user_metadata.push((
                        "saved_by_cache_ms".to_string(),
                        UserMetadataItem::Int(Duration::from(saved_by_cache).as_millis() as i64),
                    ));
                }

                (
                    WorkunitMetadata {
                        stdout: Some(res.stdout_digest),
                        stderr: Some(res.stderr_digest),
                        user_metadata,
                        ..initial
                    },
                    level,
                )
            })
        });
        if let Some(total_elapsed) = res.metadata.total_elapsed {
            let total_elapsed = Duration::from(total_elapsed).as_millis() as u64;
            match (res.metadata.source, &res.metadata.environment.strategy) {
                (ProcessResultSource::Ran, ProcessExecutionStrategy::Local) => {
                    workunit.increment_counter(Metric::LocalProcessTotalTimeRunMs, total_elapsed);
                    context.session.workunit_store().record_observation(
                        ObservationMetric::LocalProcessTimeRunMs,
                        total_elapsed,
                    );
                }
                (ProcessResultSource::Ran, ProcessExecutionStrategy::RemoteExecution { .. }) => {
                    workunit.increment_counter(Metric::RemoteProcessTotalTimeRunMs, total_elapsed);
                    context.session.workunit_store().record_observation(
                        ObservationMetric::RemoteProcessTimeRunMs,
                        total_elapsed,
                    );
                }
                _ => {}
            }
        }

        if backtrack_level > 0 {
            // TODO: This message is symmetrical to the "Making attempt {} to backtrack and retry {}"
            // message in `context.rs`, but both of them are effectively debug output. They should be
            // quieted down as part of https://github.com/pantsbuild/pants/issues/15867 once all bugs
            // have been shaken out.
            log::info!(
                "On backtrack attempt {} for `{}`, produced: {:?}",
                backtrack_level,
                request.description,
                res.output_directory.digests()
            );
        }

        Ok(ProcessResult {
            result: res,
            backtrack_level,
        })
    }
}

impl From<ExecuteProcess> for NodeKey {
    fn from(n: ExecuteProcess) -> Self {
        NodeKey::ExecuteProcess(Box::new(n))
    }
}

impl CompoundNode<NodeKey> for ExecuteProcess {
    type Item = ProcessResult;
}

#[derive(Clone, Debug, DeepSizeOf, Eq, PartialEq)]
pub struct ProcessResult {
    pub result: process_execution::FallibleProcessResultWithPlatform,
    /// The backtrack_level which produced this result. If a Digest from a particular result is
    /// missing, the next attempt needs to use a higher level of backtracking (i.e.: remove more
    /// caches).
    pub backtrack_level: usize,
}

impl TryFrom<NodeOutput> for ProcessResult {
    type Error = ();

    fn try_from(nr: NodeOutput) -> Result<Self, ()> {
        match nr {
            NodeOutput::ProcessResult(v) => Ok(*v),
            _ => Err(()),
        }
    }
}
