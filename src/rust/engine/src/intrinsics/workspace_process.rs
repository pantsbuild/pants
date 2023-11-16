// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::env::current_dir;
use std::path::Path;
use std::process::Stdio;
use std::str::FromStr;
use std::sync::Arc;

use futures::future::{BoxFuture, FutureExt};
use process_execution::local::{
    apply_chroot, create_sandbox, prepare_workdir, setup_run_sh_script, CommandRunner,
    KeepSandboxes,
};
use process_execution::ProcessExecutionStrategy;
use pyo3::{PyAny, Python, ToPyObject};

use crate::context::Context;
use crate::externs;
use crate::nodes::{ExecuteProcess, NodeResult, Snapshot};
use crate::python::Value;

pub(crate) fn workspace_process(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    log::trace!("workspace_process generating work unit closure");
    // TODO: in_workunit!("workspace_process", Level::Debug, |_workunit| async move {
    async move {
        let types = &context.core.types;
        let workspace_process_result = types.workspace_process_result;

        log::trace!("entering workspace_process");

        let (py_workspace_process, py_process, process_config): (
            Value,
            Value,
            externs::process::PyProcessExecutionEnvironment,
        ) = Python::with_gil(|py| {
            let py_workspace_process = (*args[0]).as_ref(py);
            let py_process: Value = externs::getattr(py_workspace_process, "process").unwrap();
            let process_config = (*args[1]).as_ref(py).extract().unwrap();
            (
                py_workspace_process.extract().unwrap(),
                py_process,
                process_config,
            )
        });
        log::trace!("extracted py_workspace_process and friends");
        match process_config.environment.strategy {
            ProcessExecutionStrategy::Docker(_) | ProcessExecutionStrategy::RemoteExecution(_) => {
                Err(format!(
                    "Only local environments support running processes \
               in the workspace, but a {} environment was used.",
                    process_config.environment.strategy.strategy_type(),
                ))
            }
            _ => Ok(()),
        }?;
        log::trace!("checked environment strategy");

        let mut process = ExecuteProcess::lift(&context.core.store(), py_process, process_config)
            .await?
            .process;
        log::trace!("process {process:?}");
        let keep_sandboxes = Python::with_gil(|py| {
            let py_interactive_process_obj = py_workspace_process.to_object(py);
            let py_workspace_process = py_interactive_process_obj.as_ref(py);
            let keep_sandboxes_value: &PyAny =
                externs::getattr(py_workspace_process, "keep_sandboxes").unwrap();
            KeepSandboxes::from_str(externs::getattr(keep_sandboxes_value, "value").unwrap())
                .unwrap()
        });
        log::trace!("keep_sandboxes={keep_sandboxes:?}");

        let mut tempdir = create_sandbox(
            context.core.executor.clone(),
            &context.core.local_execution_root_dir,
            "workspace process",
            keep_sandboxes,
        )?;
        log::trace!("tempdir = {}", tempdir.path().display());
        prepare_workdir(
            tempdir.path().to_owned(),
            &context.core.local_execution_root_dir,
            &process,
            process.input_digests.inputs.clone(),
            &context.core.store(),
            &context.core.named_caches,
            &context.core.immutable_inputs,
            None,
            None,
        )
        .await?;
        apply_chroot(tempdir.path().to_str().unwrap(), &mut process);

        let p = Path::new(&process.argv[0]);
        // TODO: Deprecate this program name calculation, and recommend `{chroot}` replacement in args
        // instead.
        let program_name = p.to_path_buf();

        let mut command = tokio::process::Command::new(program_name);
        for arg in process.argv[1..].iter() {
            command.arg(arg);
        }
        command.current_dir(context.context().core.build_root.clone());

        command.env_clear();
        command.envs(&process.env);
        command
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        let output = command.output().await.map_err(|e| e.to_string())?;

        let store = context.core.store();
        let posix_fs = Arc::new(
            fs::PosixFS::new(
                tempdir.path(),
                fs::GitignoreStyleExcludes::empty(),
                context.core.executor.clone(),
            )
            .map_err(|err| {
                format!(
                    "Error making posix_fs to fetch workspace process execution output files: {err}"
                )
            })?,
        );

        log::trace!("before construct_output_snapshot");

        let snapshot = CommandRunner::construct_output_snapshot(
            store,
            posix_fs,
            process.output_files,
            process.output_directories,
        )
        .await?;

        log::trace!("after construct_output_snapshot");

        let code = output.status.code().unwrap_or(-1);
        log::trace!("code = {code}");
        if keep_sandboxes == KeepSandboxes::Always
            || keep_sandboxes == KeepSandboxes::OnFailure && code != 0
        {
            tempdir.keep("workspace process");
            let do_setup_run_sh_script = |workdir_path| -> Result<(), String> {
                setup_run_sh_script(
                    tempdir.path(),
                    &process.env,
                    &process.working_directory,
                    &process.argv,
                    workdir_path,
                )
            };
            let cwd = current_dir()
                .map_err(|e| format!("Could not detect current working directory: {e}"))?;
            do_setup_run_sh_script(cwd.as_path())?;
        }

        Ok(Python::with_gil(|py| {
            externs::unsafe_call(
                py,
                workspace_process_result,
                &[
                    externs::store_i64(py, i64::from(code)),
                    Snapshot::store_snapshot(py, snapshot)
                        .expect("TODO: Do proper error handling."),
                    externs::store_bytes(py, &output.stdout),
                    externs::store_bytes(py, &output.stderr),
                ],
            )
        }))
    }
    .boxed()
}
