// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::env::current_dir;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::str::FromStr;

use futures::future::TryFutureExt;
use process_execution::local::{
    apply_chroot, create_sandbox, prepare_workdir, setup_run_sh_script, KeepSandboxes,
};
use process_execution::{ManagedChild, ProcessExecutionStrategy};
use pyo3::prelude::{pyfunction, wrap_pyfunction, PyAny, PyModule, PyResult, Python, ToPyObject};
use stdio::TryCloneAsFile;
use tokio::process;
use workunit_store::{in_workunit, Level};

use crate::context::Context;
use crate::externs::{self, PyGeneratorResponseNativeCall};
use crate::nodes::{task_get_context, task_side_effected, ExecuteProcess, NodeResult};
use crate::python::{Failure, Value};

pub fn register(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(interactive_process, m)?)?;

    Ok(())
}

#[pyfunction]
fn interactive_process(
    interactive_process: Value,
    process_config: Value,
) -> PyGeneratorResponseNativeCall {
    PyGeneratorResponseNativeCall::new(in_workunit!(
        "interactive_process",
        Level::Debug,
        |_workunit| async move {
            let context = task_get_context();
            interactive_process_inner(&context, interactive_process, process_config).await
        }
    ))
}

pub async fn interactive_process_inner(
    context: &Context,
    interactive_process: Value,
    process_config: Value,
) -> NodeResult<Value> {
    let types = &context.core.types;
    let interactive_process_result = types.interactive_process_result;

    let (py_interactive_process, py_process, process_config): (
        Value,
        Value,
        externs::process::PyProcessExecutionEnvironment,
    ) = Python::with_gil(|py| {
        let py_interactive_process = interactive_process.as_ref().as_ref(py);
        let py_process: Value = externs::getattr(py_interactive_process, "process").unwrap();
        let process_config = process_config.as_ref().as_ref(py).extract().unwrap();
        (
            py_interactive_process.extract().unwrap(),
            py_process,
            process_config,
        )
    });

    match process_config.environment.strategy {
        ProcessExecutionStrategy::Docker(_) | ProcessExecutionStrategy::RemoteExecution(_) => {
            // TODO: #17182 covers adding support for running processes interactively in Docker.
            Err(format!(
                "Only local environments support running processes \
       interactively, but a {} environment was used.",
                process_config.environment.strategy.strategy_type(),
            ))
        }
        _ => Ok(()),
    }?;
    let mut process = ExecuteProcess::lift(&context.core.store(), py_process, process_config)
        .await?
        .process;
    let (run_in_workspace, restartable, keep_sandboxes) = Python::with_gil(|py| {
        let py_interactive_process_obj = py_interactive_process.to_object(py);
        let py_interactive_process = py_interactive_process_obj.as_ref(py);
        let run_in_workspace: bool =
            externs::getattr(py_interactive_process, "run_in_workspace").unwrap();
        let restartable: bool = externs::getattr(py_interactive_process, "restartable").unwrap();
        let keep_sandboxes_value: &PyAny =
            externs::getattr(py_interactive_process, "keep_sandboxes").unwrap();
        let keep_sandboxes =
            KeepSandboxes::from_str(externs::getattr(keep_sandboxes_value, "value").unwrap())
                .unwrap();
        (run_in_workspace, restartable, keep_sandboxes)
    });

    let session = context.session.clone();

    let mut tempdir = create_sandbox(
        context.core.executor.clone(),
        &context.core.local_execution_root_dir,
        "interactive process",
        keep_sandboxes,
    )?;
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
    let program_name = if !run_in_workspace && p.is_relative() {
        let mut buf = PathBuf::new();
        buf.push(tempdir.path());
        buf.push(p);
        buf
    } else {
        p.to_path_buf()
    };

    let mut command = process::Command::new(program_name);
    if !run_in_workspace {
        command.current_dir(tempdir.path());
    }
    for arg in process.argv[1..].iter() {
        command.arg(arg);
    }

    command.env_clear();
    command.envs(&process.env);

    if !restartable {
        task_side_effected()?;
    }

    let exit_status = session.clone()
.with_console_ui_disabled(async move {
  // Once any UI is torn down, grab exclusive access to the console.
  let (term_stdin, term_stdout, term_stderr) =
    stdio::get_destination().exclusive_start(Box::new(|_| {
      // A stdio handler that will immediately trigger logging.
      Err(())
    }))?;
  // NB: Command's stdio methods take ownership of a file-like to use, so we use
  // `TryCloneAsFile` here to `dup` our thread-local stdio.
  command
    .stdin(Stdio::from(
      term_stdin
        .try_clone_as_file()
        .map_err(|e| format!("Couldn't clone stdin: {e}"))?,
    ))
    .stdout(Stdio::from(
      term_stdout
        .try_clone_as_file()
        .map_err(|e| format!("Couldn't clone stdout: {e}"))?,
    ))
    .stderr(Stdio::from(
      term_stderr
        .try_clone_as_file()
        .map_err(|e| format!("Couldn't clone stderr: {e}"))?,
    ));
  let mut subprocess =
      ManagedChild::spawn(&mut command, Some(context.core.graceful_shutdown_timeout))
        .map_err(|e| format!("Error executing interactive process: {e}"))?;
  tokio::select! {
    _ = session.cancelled() => {
      // The Session was cancelled: attempt to kill the process group / process, and
      // then wait for it to exit (to avoid zombies).
      if let Err(e) = subprocess.attempt_shutdown_sync() {
        // Failed to kill the PGID: try the non-group form.
        log::warn!("Failed to kill spawned process group ({}). Will try killing only the top process.\n\
                  This is unexpected: please file an issue about this problem at \
                  [https://github.com/pantsbuild/pants/issues/new]", e);
        subprocess.kill().map_err(|e| format!("Failed to interrupt child process: {e}")).await?;
      };
      subprocess.wait().await.map_err(|e| e.to_string())
    }
    exit_status = subprocess.wait() => {
      // The process exited.
      exit_status.map_err(|e| e.to_string())
    }
  }
})
.await?;

    let code = exit_status.code().unwrap_or(-1);
    if keep_sandboxes == KeepSandboxes::Always
        || keep_sandboxes == KeepSandboxes::OnFailure && code != 0
    {
        tempdir.keep("interactive process");
        let do_setup_run_sh_script = |workdir_path| -> Result<(), String> {
            setup_run_sh_script(
                tempdir.path(),
                &process.env,
                &process.working_directory,
                &process.argv,
                workdir_path,
            )
        };
        if run_in_workspace {
            let cwd = current_dir()
                .map_err(|e| format!("Could not detect current working directory: {e}"))?;
            do_setup_run_sh_script(cwd.as_path())?;
        } else {
            do_setup_run_sh_script(tempdir.path())?;
        }
    }
    Ok::<_, Failure>(Python::with_gil(|py| {
        externs::unsafe_call(
            py,
            interactive_process_result,
            &[externs::store_i64(py, i64::from(code))],
        )
    }))
}
