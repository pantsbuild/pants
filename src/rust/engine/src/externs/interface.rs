// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::unseparated_literal_suffix,
// TODO: Falsely triggers for async/await:
//   see https://github.com/rust-lang/rust-clippy/issues/5360
// clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]
// File-specific allowances to silence internal warnings of `py_class!`.
#![allow(
  unused_braces,
  clippy::manual_strip,
  clippy::used_underscore_binding,
  clippy::transmute_ptr_to_ptr,
  clippy::zero_ptr
)]

///
/// This crate is a wrapper around the engine crate which exposes a python module via cpython.
///
/// The engine crate contains some cpython interop which we use, notably externs which are functions
/// and types from Python which we can read from our Rust. This particular wrapper crate is just for
/// how we expose ourselves back to Python.
use std::any::Any;
use std::cell::RefCell;
use std::convert::TryInto;
use std::fs::File;
use std::io;
use std::os::unix::ffi::OsStrExt;
use std::panic;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use async_latch::AsyncLatch;
use cpython::{
  exc, py_class, py_exception, py_fn, py_module_initializer, NoArgs, PyClone, PyDict, PyErr, PyInt,
  PyList, PyObject, PyResult as CPyResult, PyString, PyTuple, PyType, Python, PythonObject,
  ToPyObject,
};
use futures::compat::Future01CompatExt;
use futures::future::FutureExt;
use futures::future::{self as future03, TryFutureExt};
use futures01::Future;
use hashing::Digest;
use indexmap::IndexMap;
use log::{self, debug, error, warn, Log};
use logging::logger::PANTS_LOGGER;
use logging::{Destination, Logger, PythonLogLevel};
use rule_graph::{self, RuleGraph};
use std::collections::hash_map::HashMap;
use task_executor::Executor;
use workunit_store::{UserMetadataItem, Workunit, WorkunitState};

use crate::{
  externs, nodes, sessions_cancel, Core, ExecutionRequest, ExecutionStrategyOptions,
  ExecutionTermination, Failure, Function, Intrinsics, Key, Params, RemotingOptions, Rule,
  Scheduler, Session, Tasks, Types, Value,
};

py_exception!(native_engine, PollTimeout);
py_exception!(native_engine, NailgunConnectionException);
py_exception!(native_engine, NailgunClientException);

py_module_initializer!(native_engine, |py, m| {
  m.add(py, "PollTimeout", py.get_type::<PollTimeout>())
    .unwrap();

  m.add(
    py,
    "NailgunClientException",
    py.get_type::<NailgunClientException>(),
  )?;
  m.add(
    py,
    "NailgunConnectionException",
    py.get_type::<NailgunConnectionException>(),
  )?;

  m.add(py, "default_cache_path", py_fn!(py, default_cache_path()))?;

  m.add(py, "default_config_path", py_fn!(py, default_config_path()))?;

  m.add(py, "cyclic_paths", py_fn!(py, cyclic_paths(a: PyDict)))?;

  m.add(
    py,
    "init_logging",
    py_fn!(
      py,
      init_logging(a: u64, b: bool, c: bool, d: bool, e: PyDict)
    ),
  )?;
  m.add(
    py,
    "setup_pantsd_logger",
    py_fn!(py, setup_pantsd_logger(a: String)),
  )?;
  m.add(py, "setup_stderr_logger", py_fn!(py, setup_stderr_logger()))?;
  m.add(py, "flush_log", py_fn!(py, flush_log()))?;
  m.add(
    py,
    "override_thread_logging_destination",
    py_fn!(py, override_thread_logging_destination(a: String)),
  )?;
  m.add(
    py,
    "write_log",
    py_fn!(py, write_log(a: String, b: u64, c: String)),
  )?;

  m.add(
    py,
    "set_per_run_log_path",
    py_fn!(py, set_per_run_log_path(a: Option<String>)),
  )?;

  m.add(
    py,
    "write_stdout",
    py_fn!(py, write_stdout(a: PySession, b: String)),
  )?;
  m.add(
    py,
    "write_stderr",
    py_fn!(py, write_stderr(a: PySession, b: String)),
  )?;
  m.add(
    py,
    "teardown_dynamic_ui",
    py_fn!(py, teardown_dynamic_ui(a: PyScheduler, b: PySession)),
  )?;

  m.add(py, "set_panic_handler", py_fn!(py, set_panic_handler()))?;

  m.add(py, "externs_set", py_fn!(py, externs_set(a: PyObject)))?;

  m.add(
    py,
    "match_path_globs",
    py_fn!(py, match_path_globs(a: PyObject, b: Vec<String>)),
  )?;
  m.add(
    py,
    "write_digest",
    py_fn!(
      py,
      write_digest(a: PyScheduler, b: PySession, c: PyObject, d: String)
    ),
  )?;
  m.add(
    py,
    "capture_snapshots",
    py_fn!(
      py,
      capture_snapshots(a: PyScheduler, b: PySession, c: PyObject)
    ),
  )?;
  m.add(
    py,
    "run_local_interactive_process",
    py_fn!(
      py,
      run_local_interactive_process(a: PyScheduler, b: PySession, c: PyObject)
    ),
  )?;

  m.add(
    py,
    "graph_invalidate",
    py_fn!(py, graph_invalidate(a: PyScheduler, b: Vec<String>)),
  )?;
  m.add(
    py,
    "graph_invalidate_all_paths",
    py_fn!(py, graph_invalidate_all_paths(a: PyScheduler)),
  )?;
  m.add(py, "graph_len", py_fn!(py, graph_len(a: PyScheduler)))?;
  m.add(
    py,
    "graph_visualize",
    py_fn!(py, graph_visualize(a: PyScheduler, b: PySession, d: String)),
  )?;

  m.add(
    py,
    "nailgun_client_create",
    py_fn!(py, nailgun_client_create(a: PyExecutor, b: u16)),
  )?;

  m.add(
    py,
    "nailgun_server_create",
    py_fn!(
      py,
      nailgun_server_create(a: PyExecutor, b: u16, c: PyObject)
    ),
  )?;
  m.add(
    py,
    "nailgun_server_await_shutdown",
    py_fn!(
      py,
      nailgun_server_await_shutdown(a: PyExecutor, b: PyNailgunServer)
    ),
  )?;

  m.add(
    py,
    "garbage_collect_store",
    py_fn!(py, garbage_collect_store(a: PyScheduler, b: usize)),
  )?;
  m.add(
    py,
    "lease_files_in_graph",
    py_fn!(py, lease_files_in_graph(a: PyScheduler, b: PySession)),
  )?;
  m.add(
    py,
    "check_invalidation_watcher_liveness",
    py_fn!(py, check_invalidation_watcher_liveness(a: PyScheduler)),
  )?;

  m.add(
    py,
    "validate_reachability",
    py_fn!(py, validate_reachability(a: PyScheduler)),
  )?;
  m.add(
    py,
    "rule_graph_consumed_types",
    py_fn!(
      py,
      rule_graph_consumed_types(a: PyScheduler, b: Vec<PyType>, c: PyType)
    ),
  )?;
  m.add(
    py,
    "rule_graph_visualize",
    py_fn!(py, rule_graph_visualize(a: PyScheduler, b: String)),
  )?;
  m.add(
    py,
    "rule_subgraph_visualize",
    py_fn!(
      py,
      rule_subgraph_visualize(a: PyScheduler, b: Vec<PyType>, c: PyType, d: String)
    ),
  )?;

  m.add(
    py,
    "execution_add_root_select",
    py_fn!(
      py,
      execution_add_root_select(
        a: PyScheduler,
        b: PyExecutionRequest,
        c: Vec<PyObject>,
        d: PyType
      )
    ),
  )?;
  m.add(
    py,
    "execution_set_poll",
    py_fn!(py, execution_set_poll(a: PyExecutionRequest, b: bool)),
  )?;
  m.add(
    py,
    "execution_set_poll_delay",
    py_fn!(py, execution_set_poll_delay(a: PyExecutionRequest, b: u64)),
  )?;
  m.add(
    py,
    "execution_set_timeout",
    py_fn!(py, execution_set_timeout(a: PyExecutionRequest, b: u64)),
  )?;

  m.add(
    py,
    "session_new_run_id",
    py_fn!(py, session_new_run_id(a: PySession)),
  )?;
  m.add(
    py,
    "session_cancel",
    py_fn!(py, session_cancel(a: PySession)),
  )?;
  m.add(py, "session_cancel_all", py_fn!(py, session_cancel_all()))?;
  m.add(
    py,
    "session_poll_workunits",
    py_fn!(
      py,
      session_poll_workunits(a: PyScheduler, b: PySession, c: u64)
    ),
  )?;

  m.add(
    py,
    "tasks_task_begin",
    py_fn!(
      py,
      tasks_task_begin(
        a: PyTasks,
        b: PyObject,
        c: PyType,
        d: bool,
        e: bool,
        f: String,
        g: String,
        h: u64
      )
    ),
  )?;
  m.add(
    py,
    "tasks_add_get",
    py_fn!(py, tasks_add_get(a: PyTasks, b: PyType, c: PyType)),
  )?;
  m.add(
    py,
    "tasks_add_select",
    py_fn!(py, tasks_add_select(a: PyTasks, b: PyType)),
  )?;
  m.add(py, "tasks_task_end", py_fn!(py, tasks_task_end(a: PyTasks)))?;
  m.add(
    py,
    "tasks_query_add",
    py_fn!(py, tasks_query_add(a: PyTasks, b: PyType, c: Vec<PyType>)),
  )?;

  m.add(
    py,
    "scheduler_execute",
    py_fn!(
      py,
      scheduler_execute(a: PyScheduler, b: PySession, c: PyExecutionRequest)
    ),
  )?;
  m.add(
    py,
    "scheduler_metrics",
    py_fn!(py, scheduler_metrics(a: PyScheduler, b: PySession)),
  )?;
  m.add(
    py,
    "scheduler_create",
    py_fn!(
      py,
      scheduler_create(
        executor_ptr: PyExecutor,
        tasks_ptr: PyTasks,
        types_ptr: PyTypes,
        build_root_buf: String,
        local_store_dir_buf: String,
        local_execution_root_dir_buf: String,
        named_caches_dir_buf: String,
        ca_certs_path: Option<String>,
        ignore_patterns: Vec<String>,
        use_gitignore: bool,
        remoting_options: PyRemotingOptions,
        exec_strategy_opts: PyExecutionStrategyOptions
      )
    ),
  )?;

  m.add(
    py,
    "single_file_digests_to_bytes",
    py_fn!(py, single_file_digests_to_bytes(a: PyScheduler, b: PyList)),
  )?;

  m.add(
    py,
    "ensure_remote_has_recursive",
    py_fn!(py, ensure_remote_has_recursive(a: PyScheduler, b: PyList)),
  )?;

  m.add_class::<PyExecutionRequest>(py)?;
  m.add_class::<PyExecutionStrategyOptions>(py)?;
  m.add_class::<PyExecutor>(py)?;
  m.add_class::<PyNailgunServer>(py)?;
  m.add_class::<PyNailgunClient>(py)?;
  m.add_class::<PyRemotingOptions>(py)?;
  m.add_class::<PyResult>(py)?;
  m.add_class::<PyScheduler>(py)?;
  m.add_class::<PySession>(py)?;
  m.add_class::<PySessionCancellationLatch>(py)?;
  m.add_class::<PyTasks>(py)?;
  m.add_class::<PyTypes>(py)?;

  m.add_class::<externs::PyGeneratorResponseBreak>(py)?;
  m.add_class::<externs::PyGeneratorResponseGet>(py)?;
  m.add_class::<externs::PyGeneratorResponseGetMulti>(py)?;

  m.add_class::<externs::fs::PyDigest>(py)?;

  Ok(())
});

py_class!(class PyTasks |py| {
    data tasks: RefCell<Tasks>;
    def __new__(_cls) -> CPyResult<Self> {
      Self::create_instance(py, RefCell::new(Tasks::new()))
    }
});

py_class!(class PyTypes |py| {
  data types: RefCell<Option<Types>>;

  def __new__(
      _cls,
      file_digest: PyType,
      snapshot: PyType,
      paths: PyType,
      file_content: PyType,
      digest_contents: PyType,
      path_globs: PyType,
      merge_digests: PyType,
      add_prefix: PyType,
      remove_prefix: PyType,
      create_digest: PyType,
      digest_subset: PyType,
      download_file: PyType,
      platform: PyType,
      multi_platform_process: PyType,
      process_result: PyType,
      coroutine: PyType,
      session_values: PyType,
      interactive_process_result: PyType,
      engine_aware_parameter: PyType
  ) -> CPyResult<Self> {
    Self::create_instance(
        py,
        RefCell::new(Some(Types {
        directory_digest: externs::type_for(py.get_type::<externs::fs::PyDigest>()),
        file_digest: externs::type_for(file_digest),
        snapshot: externs::type_for(snapshot),
        paths: externs::type_for(paths),
        file_content: externs::type_for(file_content),
        digest_contents: externs::type_for(digest_contents),
        path_globs: externs::type_for(path_globs),
        merge_digests: externs::type_for(merge_digests),
        add_prefix: externs::type_for(add_prefix),
        remove_prefix: externs::type_for(remove_prefix),
        create_digest: externs::type_for(create_digest),
        digest_subset: externs::type_for(digest_subset),
        download_file: externs::type_for(download_file),
        platform: externs::type_for(platform),
        multi_platform_process: externs::type_for(multi_platform_process),
        process_result: externs::type_for(process_result),
        coroutine: externs::type_for(coroutine),
        session_values: externs::type_for(session_values),
        interactive_process_result: externs::type_for(interactive_process_result),
        engine_aware_parameter: externs::type_for(engine_aware_parameter),
    })),
    )
  }
});

py_class!(class PyExecutor |py| {
    data executor: Executor;
    def __new__(_cls) -> CPyResult<Self> {
      let executor = Executor::new_owned().map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))?;
      Self::create_instance(py, executor)
    }
});

py_class!(class PyScheduler |py| {
    data scheduler: Scheduler;
});

// Represents configuration related to process execution strategies.
//
// The data stored by PyExecutionStrategyOptions originally was passed directly into
// scheduler_create but has been broken out separately because the large number of options
// became unwieldy.
py_class!(class PyExecutionStrategyOptions |py| {
  data options: ExecutionStrategyOptions;

  def __new__(
    _cls,
    local_parallelism: u64,
    remote_parallelism: u64,
    cleanup_local_dirs: bool,
    speculation_delay: f64,
    speculation_strategy: String,
    use_local_cache: bool,
    local_enable_nailgun: bool,
    remote_cache_read: bool,
    remote_cache_write: bool
  ) -> CPyResult<Self> {
    Self::create_instance(py,
      ExecutionStrategyOptions {
        local_parallelism: local_parallelism as usize,
        remote_parallelism: remote_parallelism as usize,
        cleanup_local_dirs,
        speculation_delay: Duration::from_millis((speculation_delay * 1000.0).round() as u64),
        speculation_strategy,
        use_local_cache,
        local_enable_nailgun,
        remote_cache_read,
        remote_cache_write,
      }
    )
  }
});

// Represents configuration related to remote execution and caching.
//
// The data stored by PyRemotingOptions originally was passed directly into scheduler_create
// but has been broken out separately because the large number of options became unwieldy.
py_class!(class PyRemotingOptions |py| {
  data options: RemotingOptions;

  def __new__(
    _cls,
    execution_enable: bool,
    store_servers: Vec<String>,
    execution_server: Option<String>,
    execution_process_cache_namespace: Option<String>,
    instance_name: Option<String>,
    root_ca_certs_path: Option<String>,
    oauth_bearer_token_path: Option<String>,
    store_thread_count: u64,
    store_chunk_bytes: u64,
    store_chunk_upload_timeout: u64,
    store_rpc_retries: u64,
    store_connection_limit: u64,
    store_initial_timeout: u64,
    store_timeout_multiplier: f64,
    store_maximum_timeout: u64,
    execution_extra_platform_properties: Vec<(String, String)>,
    execution_headers: Vec<(String, String)>,
    execution_overall_deadline_secs: u64
  ) -> CPyResult<Self> {
    Self::create_instance(py,
      RemotingOptions {
        execution_enable,
        store_servers,
        execution_server,
        execution_process_cache_namespace,
        instance_name,
        root_ca_certs_path: root_ca_certs_path.map(PathBuf::from),
        oauth_bearer_token_path: oauth_bearer_token_path.map(PathBuf::from),
        store_thread_count: store_thread_count as usize,
        store_chunk_bytes: store_chunk_bytes as usize,
        store_chunk_upload_timeout: Duration::from_secs(store_chunk_upload_timeout),
        store_rpc_retries: store_rpc_retries as usize,
        store_connection_limit: store_connection_limit as usize,
        store_initial_timeout: Duration::from_millis(store_initial_timeout),
        store_timeout_multiplier,
        store_maximum_timeout: Duration::from_millis(store_maximum_timeout),
        execution_extra_platform_properties,
        execution_headers: execution_headers.into_iter().collect(),
        execution_overall_deadline: Duration::from_secs(execution_overall_deadline_secs),
      }
    )
  }
});

py_class!(class PySession |py| {
    data session: Session;
    def __new__(_cls,
          scheduler: PyScheduler,
          should_render_ui: bool,
          build_id: String,
          should_report_workunits: bool,
          session_values: PyObject,
          cancellation_latch: PySessionCancellationLatch,
    ) -> CPyResult<Self> {
      Self::create_instance(py, Session::new(
          scheduler.scheduler(py),
          should_render_ui,
          build_id,
          should_report_workunits,
          session_values.into(),
          cancellation_latch.cancelled(py).clone(),
        )
      )
    }
});

py_class!(class PySessionCancellationLatch |py| {
    data cancelled: AsyncLatch;
    def __new__(_cls) -> CPyResult<Self> {
      Self::create_instance(py, AsyncLatch::new())
    }

    def is_cancelled(&self) -> CPyResult<bool> {
        Ok(self.cancelled(py).poll_triggered())
    }
});

py_class!(class PyNailgunServer |py| {
    data server: RefCell<Option<nailgun::Server>>;

    def port(&self) -> CPyResult<u16> {
        let borrowed_server = self.server(py).borrow();
        let server = borrowed_server.as_ref().ok_or_else(|| {
          PyErr::new::<exc::Exception, _>(py, ("Cannot get the port of a server that has already shut down.",))
        })?;
        Ok(server.port())
    }
});

py_class!(class PyNailgunClient |py| {
  data executor: PyExecutor;
  data port: u16;

  def execute(&self, command: String, args: Vec<String>, env: PyDict) -> CPyResult<PyInt> {
    use nailgun::NailgunClientError;

    let env_list: Vec<(String, String)> = env
    .items(py)
    .into_iter()
    .map(|(k, v): (PyObject, PyObject)| -> Result<(String, String), PyErr> {
      let k: String = k.extract::<String>(py)?;
      let v: String = v.extract::<String>(py)?;
      Ok((k, v))
    })
    .collect::<Result<Vec<_>, _>>()?;

    let port = *self.port(py);
    let executor_ptr = self.executor(py);

    with_executor(py, executor_ptr, |executor| {
      executor.block_on(nailgun::client_execute(
        port,
        command,
        args,
        env_list,
      )).map(|code| code.to_py_object(py)).map_err(|e| match e{
        NailgunClientError::PreConnect(err_str) => PyErr::new::<NailgunConnectionException, _>(py, (err_str,)),
        NailgunClientError::PostConnect(s) => {
          let err_str = format!("Nailgun client error: {:?}", s);
          PyErr::new::<NailgunClientException, _>(py, (err_str,))
        },
        NailgunClientError::ExplicitQuit => {
          PyErr::new::<NailgunClientException, _>(py, ("Explicit quit",))
        }
      })
    })
  }
});

py_class!(class PyExecutionRequest |py| {
    data execution_request: RefCell<ExecutionRequest>;
    def __new__(_cls) -> CPyResult<Self> {
      Self::create_instance(py, RefCell::new(ExecutionRequest::new()))
    }
});

py_class!(class PyResult |py| {
    data _is_throw: bool;
    data _result: PyObject;
    data _python_traceback: PyString;
    data _engine_traceback: PyList;

    def __new__(_cls, is_throw: bool, result: PyObject, python_traceback: PyString, engine_traceback: PyList) -> CPyResult<Self> {
      Self::create_instance(py, is_throw, result, python_traceback, engine_traceback)
    }

    def is_throw(&self) -> CPyResult<bool> {
        Ok(*self._is_throw(py))
    }

    def result(&self) -> CPyResult<PyObject> {
        Ok(self._result(py).clone_ref(py))
    }

    def python_traceback(&self) -> CPyResult<PyString> {
        Ok(self._python_traceback(py).clone_ref(py))
    }

    def engine_traceback(&self) -> CPyResult<PyList> {
        Ok(self._engine_traceback(py).clone_ref(py))
    }
});

fn py_result_from_root(py: Python, result: Result<Value, Failure>) -> CPyResult<PyResult> {
  match result {
    Ok(val) => {
      let engine_traceback: Vec<String> = vec![];
      PyResult::create_instance(
        py,
        false,
        val.into(),
        "".to_py_object(py),
        engine_traceback.to_py_object(py),
      )
    }
    Err(f) => {
      let (val, python_traceback, engine_traceback) = match f {
        f @ Failure::Invalidated => {
          let msg = format!("{}", f);
          (
            externs::create_exception(&msg),
            Failure::native_traceback(&msg),
            Vec::new(),
          )
        }
        Failure::Throw {
          val,
          python_traceback,
          engine_traceback,
        } => (val, python_traceback, engine_traceback),
      };
      PyResult::create_instance(
        py,
        true,
        val.into(),
        python_traceback.to_py_object(py),
        engine_traceback.to_py_object(py),
      )
    }
  }
}

// TODO: It's not clear how to return "nothing" (None) in a CPyResult, so this is a placeholder.
type PyUnitResult = CPyResult<Option<bool>>;

fn externs_set(_: Python, externs: PyObject) -> PyUnitResult {
  externs::set_externs(externs);
  Ok(None)
}

fn nailgun_client_create(
  py: Python,
  executor_ptr: PyExecutor,
  port: u16,
) -> CPyResult<PyNailgunClient> {
  PyNailgunClient::create_instance(py, executor_ptr, port)
}

fn nailgun_server_create(
  py: Python,
  executor_ptr: PyExecutor,
  port: u16,
  runner: PyObject,
) -> CPyResult<PyNailgunServer> {
  with_executor(py, &executor_ptr, |executor| {
    let server_future = {
      let runner: Value = runner.into();
      let executor = executor.clone();
      nailgun::Server::new(executor, port, move |exe: nailgun::RawFdExecution| {
        let command = externs::store_utf8(&exe.cmd.command);
        let args = externs::store_tuple(
          exe
            .cmd
            .args
            .iter()
            .map(|s| externs::store_utf8(s))
            .collect::<Vec<_>>(),
        );
        let env = externs::store_dict(
          exe
            .cmd
            .env
            .iter()
            .map(|(k, v)| (externs::store_utf8(k), externs::store_utf8(v)))
            .collect::<Vec<_>>(),
        )
        .unwrap();
        let working_dir = externs::store_bytes(exe.cmd.working_dir.as_os_str().as_bytes());
        let stdin_fd = externs::store_i64(exe.stdin_fd.into());
        let stdout_fd = externs::store_i64(exe.stdout_fd.into());
        let stderr_fd = externs::store_i64(exe.stderr_fd.into());
        let cancellation_latch = {
          let gil = Python::acquire_gil();
          let py = gil.python();
          PySessionCancellationLatch::create_instance(py, exe.cancelled)
            .unwrap()
            .into_object()
            .into()
        };
        let runner_args = vec![
          command,
          args,
          env,
          working_dir,
          cancellation_latch,
          stdin_fd,
          stdout_fd,
          stderr_fd,
        ];
        match externs::call_function(&runner, &runner_args) {
          Ok(exit_code) => {
            let gil = Python::acquire_gil();
            let py = gil.python();
            let code: i32 = exit_code.extract(py).unwrap();
            nailgun::ExitCode(code)
          }
          Err(e) => {
            error!("Uncaught exception in nailgun handler: {:#?}", e);
            nailgun::ExitCode(1)
          }
        }
      })
    };

    let server = executor
      .block_on(server_future)
      .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))?;
    PyNailgunServer::create_instance(py, RefCell::new(Some(server)))
  })
}

fn nailgun_server_await_shutdown(
  py: Python,
  executor_ptr: PyExecutor,
  nailgun_server_ptr: PyNailgunServer,
) -> PyUnitResult {
  with_executor(py, &executor_ptr, |executor| {
    with_nailgun_server(py, nailgun_server_ptr, |nailgun_server| {
      let shutdown_result = if let Some(server) = nailgun_server.borrow_mut().take() {
        py.allow_threads(|| executor.block_on(server.shutdown()))
      } else {
        Ok(())
      };
      shutdown_result.map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))?;
      Ok(None)
    })
  })
}

///
/// Given a set of Tasks and type information, creates a Scheduler.
///
/// The given Tasks struct will be cloned, so no additional mutation of the reference will
/// affect the created Scheduler.
///
fn scheduler_create(
  py: Python,
  executor_ptr: PyExecutor,
  tasks_ptr: PyTasks,
  types_ptr: PyTypes,
  build_root_buf: String,
  local_store_dir_buf: String,
  local_execution_root_dir_buf: String,
  named_caches_dir_buf: String,
  ca_certs_path_buf: Option<String>,
  ignore_patterns: Vec<String>,
  use_gitignore: bool,
  remoting_options: PyRemotingOptions,
  exec_strategy_opts: PyExecutionStrategyOptions,
) -> CPyResult<PyScheduler> {
  match fs::increase_limits() {
    Ok(msg) => debug!("{}", msg),
    Err(e) => warn!("{}", e),
  }
  let core: Result<Core, String> = with_executor(py, &executor_ptr, |executor| {
    let types = types_ptr
      .types(py)
      .borrow_mut()
      .take()
      .ok_or_else(|| "An instance of PyTypes may only be used once.".to_owned())?;
    let intrinsics = Intrinsics::new(&types);
    let mut tasks = tasks_ptr.tasks(py).replace(Tasks::new());
    tasks.intrinsics_set(&intrinsics);

    Core::new(
      executor.clone(),
      tasks,
      types,
      intrinsics,
      PathBuf::from(build_root_buf),
      ignore_patterns,
      use_gitignore,
      PathBuf::from(local_store_dir_buf),
      PathBuf::from(local_execution_root_dir_buf),
      PathBuf::from(named_caches_dir_buf),
      ca_certs_path_buf.map(PathBuf::from),
      remoting_options.options(py).clone(),
      exec_strategy_opts.options(py).clone(),
    )
  });
  PyScheduler::create_instance(
    py,
    Scheduler::new(core.map_err(|e| PyErr::new::<exc::ValueError, _>(py, (e,)))?),
  )
}

async fn workunit_to_py_value(
  workunit: &Workunit,
  core: &Arc<Core>,
  session: &Session,
) -> CPyResult<Value> {
  use std::time::UNIX_EPOCH;

  let mut dict_entries = vec![
    (
      externs::store_utf8("name"),
      externs::store_utf8(&workunit.name),
    ),
    (
      externs::store_utf8("span_id"),
      externs::store_utf8(&format!("{}", workunit.span_id)),
    ),
    (
      externs::store_utf8("level"),
      externs::store_utf8(&workunit.metadata.level.to_string()),
    ),
  ];
  if let Some(parent_id) = workunit.parent_id {
    dict_entries.push((
      externs::store_utf8("parent_id"),
      externs::store_utf8(&format!("{}", parent_id)),
    ));
  }

  match workunit.state {
    WorkunitState::Started { start_time } => {
      let duration = start_time
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::default());
      dict_entries.extend_from_slice(&[
        (
          externs::store_utf8("start_secs"),
          externs::store_u64(duration.as_secs()),
        ),
        (
          externs::store_utf8("start_nanos"),
          externs::store_u64(duration.subsec_nanos() as u64),
        ),
      ])
    }
    WorkunitState::Completed { time_span } => {
      dict_entries.extend_from_slice(&[
        (
          externs::store_utf8("start_secs"),
          externs::store_u64(time_span.start.secs),
        ),
        (
          externs::store_utf8("start_nanos"),
          externs::store_u64(u64::from(time_span.start.nanos)),
        ),
        (
          externs::store_utf8("duration_secs"),
          externs::store_u64(time_span.duration.secs),
        ),
        (
          externs::store_utf8("duration_nanos"),
          externs::store_u64(u64::from(time_span.duration.nanos)),
        ),
      ]);
    }
  };

  if let Some(desc) = &workunit.metadata.desc.as_ref() {
    dict_entries.push((
      externs::store_utf8("description"),
      externs::store_utf8(desc),
    ));
  }

  let mut artifact_entries = Vec::new();

  for (artifact_name, digest) in workunit.metadata.artifacts.iter() {
    let store = core.store();
    let snapshot = store::Snapshot::from_digest(store, *digest)
      .await
      .map_err(|err_str| {
        let gil = Python::acquire_gil();
        let py = gil.python();
        PyErr::new::<exc::Exception, _>(py, (err_str,))
      })?;
    artifact_entries.push((
      externs::store_utf8(artifact_name.as_str()),
      crate::nodes::Snapshot::store_snapshot(core, &snapshot).map_err(|err_str| {
        let gil = Python::acquire_gil();
        let py = gil.python();
        PyErr::new::<exc::Exception, _>(py, (err_str,))
      })?,
    ))
  }

  let mut user_metadata_entries = Vec::new();
  for (user_metadata_key, user_metadata_item) in workunit.metadata.user_metadata.iter() {
    match user_metadata_item {
      UserMetadataItem::ImmediateId(n) => {
        user_metadata_entries.push((
          externs::store_utf8(user_metadata_key.as_str()),
          externs::store_i64(*n),
        ));
      }
      UserMetadataItem::PyValue(py_val_handle) => {
        match session.with_metadata_map(|map| map.get(py_val_handle).cloned()) {
          None => log::warn!(
            "Workunit metadata() value not found for key: {}",
            user_metadata_key
          ),
          Some(v) => {
            user_metadata_entries.push((externs::store_utf8(user_metadata_key.as_str()), v));
          }
        }
      }
    }
  }

  dict_entries.push((
    externs::store_utf8("metadata"),
    externs::store_dict(user_metadata_entries)?,
  ));

  if let Some(stdout_digest) = &workunit.metadata.stdout.as_ref() {
    artifact_entries.push((
      externs::store_utf8("stdout_digest"),
      crate::nodes::Snapshot::store_file_digest(core, stdout_digest),
    ));
  }

  if let Some(stderr_digest) = &workunit.metadata.stderr.as_ref() {
    artifact_entries.push((
      externs::store_utf8("stderr_digest"),
      crate::nodes::Snapshot::store_file_digest(core, stderr_digest),
    ));
  }

  dict_entries.push((
    externs::store_utf8("artifacts"),
    externs::store_dict(artifact_entries)?,
  ));

  if !workunit.counters.is_empty() {
    let counters_entries = workunit
      .counters
      .iter()
      .map(|(counter_name, counter_value)| {
        (
          externs::store_utf8(counter_name.as_str()),
          externs::store_u64(*counter_value),
        )
      })
      .collect();

    dict_entries.push((
      externs::store_utf8("counters"),
      externs::store_dict(counters_entries)?,
    ));
  }

  externs::store_dict(dict_entries)
}

async fn workunits_to_py_tuple_value<'a>(
  workunits: impl Iterator<Item = &'a Workunit>,
  core: &Arc<Core>,
  session: &Session,
) -> CPyResult<Value> {
  // Acquire the GIL here so that calls into the externs::store_* helpers via workunit_to_py_value
  // do not block on obtaining the GIL for every value conversion. (This API supports recursive
  // acquisition of the GIL.)
  let _gil = Python::acquire_gil();

  let mut workunit_values = Vec::new();
  for workunit in workunits {
    let py_value = workunit_to_py_value(workunit, core, session).await?;
    workunit_values.push(py_value);
  }
  Ok(externs::store_tuple(workunit_values))
}

fn session_poll_workunits(
  py: Python,
  scheduler_ptr: PyScheduler,
  session_ptr: PySession,
  max_log_verbosity_level: u64,
) -> CPyResult<PyObject> {
  let py_level: PythonLogLevel = max_log_verbosity_level
    .try_into()
    .map_err(|e| PyErr::new::<exc::Exception, _>(py, (format!("{}", e),)))?;
  with_scheduler(py, scheduler_ptr, |scheduler| {
    with_session(py, session_ptr, |session| {
      let core = scheduler.core.clone();
      py.allow_threads(|| {
        session
          .workunit_store()
          .with_latest_workunits(py_level.into(), |started, completed| {
            let mut started_iter = started.iter();
            let started = core.executor.block_on(workunits_to_py_tuple_value(
              &mut started_iter,
              &scheduler.core,
              &session,
            ))?;

            let mut completed_iter = completed.iter();
            let completed = core.executor.block_on(workunits_to_py_tuple_value(
              &mut completed_iter,
              &scheduler.core,
              &session,
            ))?;

            Ok(externs::store_tuple(vec![started, completed]).into())
          })
      })
    })
  })
}

fn scheduler_metrics(
  py: Python,
  scheduler_ptr: PyScheduler,
  session_ptr: PySession,
) -> CPyResult<PyObject> {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    with_session(py, session_ptr, |session| {
      let values = scheduler
        .metrics(session)
        .into_iter()
        .map(|(metric, value)| (externs::store_utf8(metric), externs::store_i64(value)))
        .collect::<Vec<_>>();
      externs::store_dict(values).map(|d| d.consume_into_py_object(py))
    })
  })
}

fn scheduler_execute(
  py: Python,
  scheduler_ptr: PyScheduler,
  session_ptr: PySession,
  execution_request_ptr: PyExecutionRequest,
) -> CPyResult<PyTuple> {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    with_execution_request(py, execution_request_ptr, |execution_request| {
      with_session(py, session_ptr, |session| {
        // TODO: A parent_id should be an explicit argument.
        session.workunit_store().init_thread_state(None);
        py.allow_threads(|| scheduler.execute(execution_request, session))
          .map(|root_results| {
            let py_results = root_results
              .into_iter()
              .map(|rr| py_result_from_root(py, rr).unwrap().into_object())
              .collect::<Vec<_>>();
            PyTuple::new(py, &py_results)
          })
          .map_err(|e| match e {
            ExecutionTermination::KeyboardInterrupt => {
              PyErr::new::<exc::KeyboardInterrupt, _>(py, NoArgs)
            }
            ExecutionTermination::PollTimeout => PyErr::new::<PollTimeout, _>(py, NoArgs),
            ExecutionTermination::Fatal(msg) => PyErr::new::<exc::Exception, _>(py, (msg,)),
          })
      })
    })
  })
}

fn execution_add_root_select(
  py: Python,
  scheduler_ptr: PyScheduler,
  execution_request_ptr: PyExecutionRequest,
  param_vals: Vec<PyObject>,
  product: PyType,
) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    with_execution_request(py, execution_request_ptr, |execution_request| {
      let product = externs::type_for(product);
      let keys = param_vals
        .into_iter()
        .map(|p| externs::key_for(p.into()))
        .collect::<Result<Vec<_>, _>>()?;
      Params::new(keys)
        .and_then(|params| scheduler.add_root_select(execution_request, params, product))
        .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))
        .map(|()| None)
    })
  })
}

fn execution_set_poll(
  py: Python,
  execution_request_ptr: PyExecutionRequest,
  poll: bool,
) -> PyUnitResult {
  with_execution_request(py, execution_request_ptr, |execution_request| {
    execution_request.poll = poll;
  });
  Ok(None)
}

fn execution_set_poll_delay(
  py: Python,
  execution_request_ptr: PyExecutionRequest,
  poll_delay_in_ms: u64,
) -> PyUnitResult {
  with_execution_request(py, execution_request_ptr, |execution_request| {
    execution_request.poll_delay = Some(Duration::from_millis(poll_delay_in_ms));
  });
  Ok(None)
}

fn execution_set_timeout(
  py: Python,
  execution_request_ptr: PyExecutionRequest,
  timeout_in_ms: u64,
) -> PyUnitResult {
  with_execution_request(py, execution_request_ptr, |execution_request| {
    execution_request.timeout = Some(Duration::from_millis(timeout_in_ms));
  });
  Ok(None)
}

fn tasks_task_begin(
  py: Python,
  tasks_ptr: PyTasks,
  func: PyObject,
  output_type: PyType,
  can_modify_workunit: bool,
  cacheable: bool,
  name: String,
  desc: String,
  level: u64,
) -> PyUnitResult {
  let py_level: PythonLogLevel = level
    .try_into()
    .map_err(|e| PyErr::new::<exc::Exception, _>(py, (format!("{}", e),)))?;
  with_tasks(py, tasks_ptr, |tasks| {
    let func = Function(externs::key_for(func.into())?);
    let output_type = externs::type_for(output_type);
    tasks.task_begin(
      func,
      output_type,
      can_modify_workunit,
      cacheable,
      name,
      if desc.is_empty() { None } else { Some(desc) },
      py_level.into(),
    );
    Ok(None)
  })
}

fn tasks_add_get(py: Python, tasks_ptr: PyTasks, output: PyType, input: PyType) -> PyUnitResult {
  with_tasks(py, tasks_ptr, |tasks| {
    let output = externs::type_for(output);
    let input = externs::type_for(input);
    tasks.add_get(output, input);
    Ok(None)
  })
}

fn tasks_add_select(py: Python, tasks_ptr: PyTasks, selector: PyType) -> PyUnitResult {
  with_tasks(py, tasks_ptr, |tasks| {
    let selector = externs::type_for(selector);
    tasks.add_select(selector);
    Ok(None)
  })
}

fn tasks_task_end(py: Python, tasks_ptr: PyTasks) -> PyUnitResult {
  with_tasks(py, tasks_ptr, |tasks| {
    tasks.task_end();
    Ok(None)
  })
}

fn tasks_query_add(
  py: Python,
  tasks_ptr: PyTasks,
  output_type: PyType,
  input_types: Vec<PyType>,
) -> PyUnitResult {
  with_tasks(py, tasks_ptr, |tasks| {
    tasks.query_add(
      externs::type_for(output_type),
      input_types.into_iter().map(externs::type_for).collect(),
    );
    Ok(None)
  })
}

fn graph_invalidate(py: Python, scheduler_ptr: PyScheduler, paths: Vec<String>) -> CPyResult<u64> {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    let paths = paths.into_iter().map(PathBuf::from).collect();
    py.allow_threads(|| Ok(scheduler.invalidate(&paths) as u64))
  })
}

fn graph_invalidate_all_paths(py: Python, scheduler_ptr: PyScheduler) -> CPyResult<u64> {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    py.allow_threads(|| Ok(scheduler.invalidate_all_paths() as u64))
  })
}

fn check_invalidation_watcher_liveness(py: Python, scheduler_ptr: PyScheduler) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    scheduler
      .is_valid()
      .map(|()| None)
      .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))
  })
}

fn graph_len(py: Python, scheduler_ptr: PyScheduler) -> CPyResult<u64> {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    py.allow_threads(|| Ok(scheduler.core.graph.len() as u64))
  })
}

fn graph_visualize(
  py: Python,
  scheduler_ptr: PyScheduler,
  session_ptr: PySession,
  path: String,
) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    with_session(py, session_ptr, |session| {
      let path = PathBuf::from(path);
      scheduler
        .visualize(session, path.as_path())
        .map_err(|e| {
          let e = format!("Failed to visualize to {}: {:?}", path.display(), e);
          PyErr::new::<exc::Exception, _>(py, (e,))
        })
        .map(|()| None)
    })
  })
}

fn session_new_run_id(py: Python, session_ptr: PySession) -> PyUnitResult {
  with_session(py, session_ptr, |session| {
    session.new_run_id();
    Ok(None)
  })
}

fn session_cancel(py: Python, session_ptr: PySession) -> PyUnitResult {
  with_session(py, session_ptr, |session| {
    session.core().executor.block_on(session.cancel());
    Ok(None)
  })
}

fn session_cancel_all(py: Python) -> PyUnitResult {
  py.allow_threads(|| {
    sessions_cancel();
    Ok(None)
  })
}

fn validate_reachability(py: Python, scheduler_ptr: PyScheduler) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    scheduler
      .core
      .rule_graph
      .validate_reachability()
      .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))
      .map(|()| None)
  })
}

fn rule_graph_consumed_types(
  py: Python,
  scheduler_ptr: PyScheduler,
  param_types: Vec<PyType>,
  product_type: PyType,
) -> CPyResult<Vec<PyType>> {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    let param_types = param_types
      .into_iter()
      .map(externs::type_for)
      .collect::<Vec<_>>();

    let subgraph = scheduler
      .core
      .rule_graph
      .subgraph(param_types, externs::type_for(product_type))
      .map_err(|e| PyErr::new::<exc::ValueError, _>(py, (e,)))?;

    Ok(
      subgraph
        .consumed_types()
        .into_iter()
        .map(externs::type_for_type_id)
        .collect(),
    )
  })
}

fn rule_graph_visualize(py: Python, scheduler_ptr: PyScheduler, path: String) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    let path = PathBuf::from(path);

    // TODO(#7117): we want to represent union types in the graph visualizer somehow!!!
    write_to_file(path.as_path(), &scheduler.core.rule_graph)
      .map_err(|e| {
        let e = format!("Failed to visualize to {}: {:?}", path.display(), e);
        PyErr::new::<exc::IOError, _>(py, (e,))
      })
      .map(|()| None)
  })
}

fn rule_subgraph_visualize(
  py: Python,
  scheduler_ptr: PyScheduler,
  param_types: Vec<PyType>,
  product_type: PyType,
  path: String,
) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    let param_types = param_types
      .into_iter()
      .map(externs::type_for)
      .collect::<Vec<_>>();
    let product_type = externs::type_for(product_type);
    let path = PathBuf::from(path);

    // TODO(#7117): we want to represent union types in the graph visualizer somehow!!!
    let subgraph = scheduler
      .core
      .rule_graph
      .subgraph(param_types, product_type)
      .map_err(|e| PyErr::new::<exc::ValueError, _>(py, (e,)))?;

    write_to_file(path.as_path(), &subgraph)
      .map_err(|e| {
        let e = format!("Failed to visualize to {}: {:?}", path.display(), e);
        PyErr::new::<exc::IOError, _>(py, (e,))
      })
      .map(|()| None)
  })
}

pub(crate) fn generate_panic_string(payload: &(dyn Any + Send)) -> String {
  match payload
    .downcast_ref::<String>()
    .cloned()
    .or_else(|| payload.downcast_ref::<&str>().map(|&s| s.to_string()))
  {
    Some(ref s) => format!("panic at '{}'", s),
    None => format!("Non-string panic payload at {:p}", payload),
  }
}

fn set_panic_handler(_: Python) -> PyUnitResult {
  panic::set_hook(Box::new(|panic_info| {
    let payload = panic_info.payload();
    let mut panic_str = generate_panic_string(payload);

    if let Some(location) = panic_info.location() {
      let panic_location_str = format!(", {}:{}", location.file(), location.line());
      panic_str.push_str(&panic_location_str);
    }

    error!("{}", panic_str);

    let panic_file_bug_str = "Please set RUST_BACKTRACE=1, re-run, and then file a bug at https://github.com/pantsbuild/pants/issues.";
    error!("{}", panic_file_bug_str);
  }));
  Ok(None)
}

fn garbage_collect_store(
  py: Python,
  scheduler_ptr: PyScheduler,
  target_size_bytes: usize,
) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    py.allow_threads(|| {
      scheduler
        .core
        .store()
        .garbage_collect(target_size_bytes, store::ShrinkBehavior::Fast)
    })
    .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))
    .map(|()| None)
  })
}

fn lease_files_in_graph(
  py: Python,
  scheduler_ptr: PyScheduler,
  session_ptr: PySession,
) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    with_session(py, session_ptr, |session| {
      let digests = scheduler.all_digests(session);
      py.allow_threads(|| {
        scheduler
          .core
          .executor
          .block_on(scheduler.core.store().lease_all_recursively(digests.iter()))
      })
      .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))
      .map(|()| None)
    })
  })
}

fn match_path_globs(
  py: Python,
  path_globs: PyObject,
  paths: Vec<String>,
) -> CPyResult<Vec<String>> {
  let matches = py
    .allow_threads(|| {
      let path_globs = nodes::Snapshot::lift_prepared_path_globs(&path_globs.into())?;

      Ok(
        paths
          .into_iter()
          .map(PathBuf::from)
          .filter(|pb| path_globs.matches(pb.as_ref()))
          .collect::<Vec<_>>(),
      )
    })
    .map_err(|e: String| PyErr::new::<exc::ValueError, _>(py, (e,)))?;

  matches
    .into_iter()
    .map(|pb| {
      pb.into_os_string().into_string().map_err(|s| {
        PyErr::new::<exc::Exception, _>(py, (format!("Could not decode {:?} as a string.", s),))
      })
    })
    .collect::<Result<Vec<_>, _>>()
}

fn capture_snapshots(
  py: Python,
  scheduler_ptr: PyScheduler,
  session_ptr: PySession,
  path_globs_and_root_tuple_wrapper: PyObject,
) -> CPyResult<PyObject> {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    with_session(py, session_ptr, |session| {
      // TODO: A parent_id should be an explicit argument.
      session.workunit_store().init_thread_state(None);
      let core = scheduler.core.clone();

      let values = externs::collect_iterable(&path_globs_and_root_tuple_wrapper).unwrap();
      let path_globs_and_roots = values
        .iter()
        .map(|value| {
          let root = PathBuf::from(externs::getattr_as_string(&value, "root"));
          let path_globs = nodes::Snapshot::lift_prepared_path_globs(
            &externs::getattr(&value, "path_globs").unwrap(),
          );
          let digest_hint = {
            let maybe_digest: PyObject = externs::getattr(&value, "digest_hint").unwrap();
            if maybe_digest == externs::none() {
              None
            } else {
              Some(nodes::lift_directory_digest(
                &core.types,
                &Value::new(maybe_digest),
              )?)
            }
          };
          path_globs.map(|path_globs| (path_globs, root, digest_hint))
        })
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| PyErr::new::<exc::ValueError, _>(py, (e,)))?;

      let snapshot_futures = path_globs_and_roots
        .into_iter()
        .map(|(path_globs, root, digest_hint)| {
          let core = core.clone();
          async move {
            let snapshot = store::Snapshot::capture_snapshot_from_arbitrary_root(
              core.store(),
              core.executor.clone(),
              root,
              path_globs,
              digest_hint,
            )
            .await?;
            nodes::Snapshot::store_snapshot(&core, &snapshot)
          }
        })
        .collect::<Vec<_>>();
      py.allow_threads(|| {
        core.executor.block_on(
          future03::try_join_all(snapshot_futures)
            .map_ok(|values| externs::store_tuple(values).into()),
        )
      })
      .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))
    })
  })
}

fn ensure_remote_has_recursive(
  py: Python,
  scheduler_ptr: PyScheduler,
  py_digests: PyList,
) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    let core = scheduler.core.clone();
    let store = core.store();

    // NB: Supports either a FileDigest or Digest as input.
    let digests: Vec<Digest> = py_digests
      .iter(py)
      .map(|item| {
        let value = item.into();
        crate::nodes::lift_directory_digest(&core.types, &value)
          .or_else(|_| crate::nodes::lift_file_digest(&core.types, &value))
      })
      .collect::<Result<Vec<Digest>, _>>()
      .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))?;

    let _upload_summary = py
      .allow_threads(|| {
        core
          .executor
          .block_on(store.ensure_remote_has_recursive(digests).compat())
      })
      .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))?;
    Ok(None)
  })
}

/// This functions assumes that the Digest in question represents the contents of a single File rather than a Directory,
/// and will fail on Digests representing a Directory.
fn single_file_digests_to_bytes(
  py: Python,
  scheduler_ptr: PyScheduler,
  py_file_digests: PyList,
) -> CPyResult<PyList> {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    let core = scheduler.core.clone();

    let digests: Vec<Digest> = py_file_digests
      .iter(py)
      .map(|item| crate::nodes::lift_file_digest(&core.types, &item.into()))
      .collect::<Result<Vec<Digest>, _>>()
      .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))?;

    let digest_futures = digests.into_iter().map(|digest| {
      let store = core.store();
      async move {
        store
          .load_file_bytes_with(digest, externs::store_bytes)
          .await
          .and_then(|maybe_bytes: Option<(Value, _)>| {
            maybe_bytes
              .map(|bytes_tuple| bytes_tuple.0)
              .ok_or_else(|| format!("Error loading bytes from digest: {:?}", digest))
          })
      }
    });

    let bytes_values: Vec<PyObject> = py
      .allow_threads(|| {
        core.executor.block_on(
          future03::try_join_all(digest_futures)
            .map_ok(|values: Vec<Value>| values.into_iter().map(|val| val.into()).collect()),
        )
      })
      .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))?;

    let output_list = PyList::new(py, &bytes_values);
    Ok(output_list)
  })
}

fn run_local_interactive_process(
  py: Python,
  scheduler_ptr: PyScheduler,
  session_ptr: PySession,
  request: PyObject,
) -> CPyResult<PyObject> {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    with_session(py, session_ptr, |session| {
      let types = &scheduler.core.types;
      let interactive_process_result = types.interactive_process_result;

      let value: Value = request.into();

      let argv: Vec<String> = externs::getattr(&value, "argv").unwrap();
      if argv.is_empty() {
        return Err("Empty argv list not permitted".to_string());
      }

      let run_in_workspace: bool = externs::getattr(&value, "run_in_workspace").unwrap();
      let input_digest_value: Value = externs::getattr(&value, "input_digest").unwrap();
      let input_digest: Digest = nodes::lift_directory_digest(types, &input_digest_value)?;
      let hermetic_env: bool = externs::getattr(&value, "hermetic_env").unwrap();
      let env = externs::getattr_from_frozendict(&value, "env");

      let code = block_in_place_and_wait(py, || {
        scheduler
          .run_local_interactive_process(
            session,
            input_digest,
            argv,
            env,
            hermetic_env,
            run_in_workspace,
          )
          .boxed_local()
          .compat()
      })?;

      Ok(
        externs::unsafe_call(
          interactive_process_result,
          &[externs::store_i64(i64::from(code))],
        )
        .into(),
      )
    })
  })
  .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))
}

fn write_digest(
  py: Python,
  scheduler_ptr: PyScheduler,
  session_ptr: PySession,
  digest: PyObject,
  path_prefix: String,
) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |scheduler| {
    with_session(py, session_ptr, |session| {
      // TODO: A parent_id should be an explicit argument.
      session.workunit_store().init_thread_state(None);

      let lifted_digest = nodes::lift_directory_digest(&scheduler.core.types, &digest.into())
        .map_err(|e| PyErr::new::<exc::ValueError, _>(py, (e,)))?;

      // Python will have already validated that path_prefix is a relative path.
      let mut destination = PathBuf::new();
      destination.push(scheduler.core.build_root.clone());
      destination.push(path_prefix);

      block_in_place_and_wait(py, || {
        scheduler
          .core
          .store()
          .materialize_directory(destination.clone(), lifted_digest)
      })
      .map_err(|e| PyErr::new::<exc::ValueError, _>(py, (e,)))?;
      Ok(None)
    })
  })
}

fn default_cache_path(py: Python) -> CPyResult<String> {
  fs::default_cache_path()
    .into_os_string()
    .into_string()
    .map_err(|s| {
      PyErr::new::<exc::Exception, _>(
        py,
        (format!(
          "Default cache path {:?} could not be converted to a string.",
          s
        ),),
      )
    })
}

fn default_config_path(py: Python) -> CPyResult<String> {
  fs::default_config_path()
    .into_os_string()
    .into_string()
    .map_err(|s| {
      PyErr::new::<exc::Exception, _>(
        py,
        (format!(
          "Default config path {:?} could not be converted to a string.",
          s
        ),),
      )
    })
}

fn cyclic_paths(py: Python, adjacencies: PyDict) -> CPyResult<Vec<PyTuple>> {
  let adjacencies = adjacencies
    .items(py)
    .into_iter()
    .map(|(k, v)| {
      let node = externs::key_for(k.into())?;
      let adjacent = v
        .extract::<Vec<PyObject>>(py)?
        .into_iter()
        .map(|v| externs::key_for(v.into()))
        .collect::<Result<Vec<Key>, _>>()?;
      let res: Result<_, PyErr> = Ok((node, adjacent));
      res
    })
    .collect::<Result<IndexMap<Key, Vec<Key>>, _>>()?;
  let paths = py.allow_threads(move || crate::core::cyclic_paths(adjacencies));

  Ok(
    paths
      .into_iter()
      .map(|path| {
        let gil = Python::acquire_gil();
        let path_vec = path
          .iter()
          .map(externs::val_for)
          .map(|node| node.consume_into_py_object(gil.python()))
          .collect::<Vec<_>>();
        PyTuple::new(gil.python(), &path_vec)
      })
      .collect(),
  )
}

fn init_logging(
  py: Python,
  level: u64,
  show_rust_3rdparty_logs: bool,
  use_color: bool,
  show_target: bool,
  log_levels_by_target: PyDict,
) -> PyUnitResult {
  let log_levels_by_target = log_levels_by_target
    .items(py)
    .iter()
    .map(|(k, v)| {
      let k: String = k.extract(py).unwrap();
      let v: u64 = v.extract(py).unwrap();
      (k, v)
    })
    .collect::<HashMap<_, _>>();
  Logger::init(
    level,
    show_rust_3rdparty_logs,
    use_color,
    show_target,
    log_levels_by_target,
  );
  Ok(None)
}

fn setup_pantsd_logger(py: Python, log_file: String) -> CPyResult<i64> {
  logging::set_thread_destination(Destination::Pantsd);
  let path = PathBuf::from(log_file);
  PANTS_LOGGER
    .set_pantsd_logger(path)
    .map(i64::from)
    .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))
}

fn setup_stderr_logger(_: Python) -> PyUnitResult {
  logging::set_thread_destination(Destination::Stderr);
  Ok(None)
}

fn set_per_run_log_path(py: Python, log_path: Option<String>) -> PyUnitResult {
  py.allow_threads(|| {
    PANTS_LOGGER.set_per_run_logs(log_path.map(PathBuf::from));
    Ok(None)
  })
}

fn write_log(py: Python, msg: String, level: u64, path: String) -> PyUnitResult {
  py.allow_threads(|| {
    Logger::log_from_python(&msg, level, &path).expect("Error logging message");
    Ok(None)
  })
}

fn write_stdout(py: Python, session_ptr: PySession, msg: String) -> PyUnitResult {
  with_session(py, session_ptr, |session| {
    block_in_place_and_wait(py, || session.write_stdout(&msg).boxed_local().compat())
      .map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))?;
    Ok(None)
  })
}

fn write_stderr(py: Python, session_ptr: PySession, msg: String) -> PyUnitResult {
  with_session(py, session_ptr, |session| {
    py.allow_threads(|| {
      session.write_stderr(&msg);
      Ok(None)
    })
  })
}

fn teardown_dynamic_ui(
  py: Python,
  scheduler_ptr: PyScheduler,
  session_ptr: PySession,
) -> PyUnitResult {
  with_scheduler(py, scheduler_ptr, |_scheduler| {
    with_session(py, session_ptr, |session| {
      let _ = block_in_place_and_wait(py, || {
        session
          .maybe_display_teardown()
          .unit_error()
          .boxed_local()
          .compat()
      });
      Ok(None)
    })
  })
}

fn flush_log(py: Python) -> PyUnitResult {
  py.allow_threads(|| {
    PANTS_LOGGER.flush();
    Ok(None)
  })
}

fn override_thread_logging_destination(py: Python, destination: String) -> PyUnitResult {
  let destination = destination
    .as_str()
    .try_into()
    .map_err(|e| PyErr::new::<exc::ValueError, _>(py, (e,)))?;
  logging::set_thread_destination(destination);
  Ok(None)
}

fn write_to_file(path: &Path, graph: &RuleGraph<Rule>) -> io::Result<()> {
  let file = File::create(path)?;
  let mut f = io::BufWriter::new(file);
  graph.visualize(&mut f)
}

///
/// Calling `wait()` in the context of a @goal_rule blocks a thread that is owned by the tokio
/// runtime. To do that safely, we need to relinquish it.
///   see https://github.com/pantsbuild/pants/issues/9476
///
/// TODO: The alternative to blocking the runtime would be to have the Python code `await` special
/// methods for things like `write_digest` and etc.
///
fn block_in_place_and_wait<T, E, F>(py: Python, f: impl FnOnce() -> F + Sync + Send) -> Result<T, E>
where
  F: Future<Item = T, Error = E>,
{
  py.allow_threads(|| {
    let future = f();
    tokio::task::block_in_place(|| future.wait())
  })
}

///
/// Scheduler, Session, and nailgun::Server are intended to be shared between threads, and so their
/// context methods provide immutable references. The remaining types are not intended to be shared
/// between threads, so mutable access is provided.
///
fn with_scheduler<F, T>(py: Python, scheduler_ptr: PyScheduler, f: F) -> T
where
  F: FnOnce(&Scheduler) -> T,
{
  let scheduler = scheduler_ptr.scheduler(py);
  scheduler.core.executor.enter(|| f(scheduler))
}

///
/// See `with_scheduler`.
///
fn with_executor<F, T>(py: Python, executor_ptr: &PyExecutor, f: F) -> T
where
  F: FnOnce(&Executor) -> T,
{
  let executor = executor_ptr.executor(py);
  f(&executor)
}

///
/// See `with_scheduler`.
///
fn with_session<F, T>(py: Python, session_ptr: PySession, f: F) -> T
where
  F: FnOnce(&Session) -> T,
{
  let session = session_ptr.session(py);
  f(&session)
}

///
/// See `with_scheduler`.
///
fn with_nailgun_server<F, T>(py: Python, nailgun_server_ptr: PyNailgunServer, f: F) -> T
where
  F: FnOnce(&RefCell<Option<nailgun::Server>>) -> T,
{
  let nailgun_server = nailgun_server_ptr.server(py);
  f(&nailgun_server)
}

///
/// See `with_scheduler`.
///
fn with_execution_request<F, T>(py: Python, execution_request_ptr: PyExecutionRequest, f: F) -> T
where
  F: FnOnce(&mut ExecutionRequest) -> T,
{
  let mut execution_request = execution_request_ptr.execution_request(py).borrow_mut();
  f(&mut execution_request)
}

///
/// See `with_scheduler`.
///
fn with_tasks<F, T>(py: Python, tasks_ptr: PyTasks, f: F) -> T
where
  F: FnOnce(&mut Tasks) -> T,
{
  let mut tasks = tasks_ptr.tasks(py).borrow_mut();
  f(&mut tasks)
}
