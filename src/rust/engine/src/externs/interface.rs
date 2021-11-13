// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// File-specific allowances to silence internal warnings of `[pyclass]`.
#![allow(clippy::used_underscore_binding)]

/// This crate is a wrapper around the engine crate which exposes a Python module via PyO3.
use std::any::Any;
use std::cell::RefCell;
use std::collections::hash_map::HashMap;
use std::convert::TryInto;
use std::fs::File;
use std::io;
use std::panic;
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use async_latch::AsyncLatch;
use futures::future::FutureExt;
use futures::future::{self, TryFutureExt};
use futures::Future;
use hashing::Digest;
use log::{self, debug, error, warn, Log};
use logging::logger::PANTS_LOGGER;
use logging::{Logger, PythonLogLevel};
use petgraph::graph::{DiGraph, Graph};
use process_execution::RemoteCacheWarningsBehavior;
use pyo3::exceptions::{PyException, PyIOError, PyKeyboardInterrupt, PyValueError};
use pyo3::prelude::{
  pyclass, pyfunction, pymethods, pymodule, wrap_pyfunction, Py, PyModule, PyObject,
  PyResult as PyO3Result, Python,
};
use pyo3::types::{PyBytes, PyDict, PyList, PyString, PyTuple, PyType};
use pyo3::{create_exception, IntoPy, PyAny};
use regex::Regex;
use rule_graph::{self, RuleGraph};
use task_executor::Executor;
use workunit_store::{
  ArtifactOutput, ObservationMetric, UserMetadataItem, Workunit, WorkunitState,
};

use crate::{
  externs, nodes, Context, Core, ExecutionRequest, ExecutionStrategyOptions, ExecutionTermination,
  Failure, Function, Intrinsic, Intrinsics, Key, LocalStoreOptions, Params, RemotingOptions, Rule,
  Scheduler, Session, Tasks, TypeId, Types, Value,
};

#[pymodule]
fn native_engine(py: Python, m: &PyModule) -> PyO3Result<()> {
  m.add("PollTimeout", py.get_type::<PollTimeout>())?;

  m.add_class::<PyExecutionRequest>()?;
  m.add_class::<PyExecutionStrategyOptions>()?;
  m.add_class::<PyExecutor>()?;
  m.add_class::<PyNailgunServer>()?;
  m.add_class::<PyRemotingOptions>()?;
  m.add_class::<PyLocalStoreOptions>()?;
  m.add_class::<PyResult>()?;
  m.add_class::<PyScheduler>()?;
  m.add_class::<PySession>()?;
  m.add_class::<PySessionCancellationLatch>()?;
  m.add_class::<PyStdioDestination>()?;
  m.add_class::<PyTasks>()?;
  m.add_class::<PyTypes>()?;

  m.add_class::<externs::PyGeneratorResponseBreak>()?;
  m.add_class::<externs::PyGeneratorResponseGet>()?;
  m.add_class::<externs::PyGeneratorResponseGetMulti>()?;

  m.add_class::<externs::fs::PyDigest>()?;
  m.add_class::<externs::fs::PySnapshot>()?;

  m.add_function(wrap_pyfunction!(stdio_initialize, m)?)?;
  m.add_function(wrap_pyfunction!(stdio_thread_console_set, m)?)?;
  m.add_function(wrap_pyfunction!(stdio_thread_console_color_mode_set, m)?)?;
  m.add_function(wrap_pyfunction!(stdio_thread_console_clear, m)?)?;
  m.add_function(wrap_pyfunction!(stdio_thread_get_destination, m)?)?;
  m.add_function(wrap_pyfunction!(stdio_thread_set_destination, m)?)?;

  m.add_function(wrap_pyfunction!(flush_log, m)?)?;
  m.add_function(wrap_pyfunction!(write_log, m)?)?;
  m.add_function(wrap_pyfunction!(set_per_run_log_path, m)?)?;
  m.add_function(wrap_pyfunction!(teardown_dynamic_ui, m)?)?;
  m.add_function(wrap_pyfunction!(maybe_set_panic_handler, m)?)?;

  m.add_function(wrap_pyfunction!(task_side_effected, m)?)?;

  m.add_function(wrap_pyfunction!(tasks_task_begin, m)?)?;
  m.add_function(wrap_pyfunction!(tasks_task_end, m)?)?;
  m.add_function(wrap_pyfunction!(tasks_add_get, m)?)?;
  m.add_function(wrap_pyfunction!(tasks_add_union, m)?)?;
  m.add_function(wrap_pyfunction!(tasks_add_select, m)?)?;
  m.add_function(wrap_pyfunction!(tasks_add_query, m)?)?;

  m.add_function(wrap_pyfunction!(write_digest, m)?)?;
  m.add_function(wrap_pyfunction!(capture_snapshots, m)?)?;

  m.add_function(wrap_pyfunction!(graph_invalidate_paths, m)?)?;
  m.add_function(wrap_pyfunction!(graph_invalidate_all_paths, m)?)?;
  m.add_function(wrap_pyfunction!(graph_invalidate_all, m)?)?;
  m.add_function(wrap_pyfunction!(graph_len, m)?)?;
  m.add_function(wrap_pyfunction!(graph_visualize, m)?)?;

  m.add_function(wrap_pyfunction!(nailgun_server_create, m)?)?;
  m.add_function(wrap_pyfunction!(nailgun_server_await_shutdown, m)?)?;

  m.add_function(wrap_pyfunction!(garbage_collect_store, m)?)?;
  m.add_function(wrap_pyfunction!(lease_files_in_graph, m)?)?;
  m.add_function(wrap_pyfunction!(check_invalidation_watcher_liveness, m)?)?;

  m.add_function(wrap_pyfunction!(validate_reachability, m)?)?;
  m.add_function(wrap_pyfunction!(rule_graph_consumed_types, m)?)?;
  m.add_function(wrap_pyfunction!(rule_graph_visualize, m)?)?;
  m.add_function(wrap_pyfunction!(rule_subgraph_visualize, m)?)?;

  m.add_function(wrap_pyfunction!(execution_add_root_select, m)?)?;

  m.add_function(wrap_pyfunction!(session_new_run_id, m)?)?;
  m.add_function(wrap_pyfunction!(session_poll_workunits, m)?)?;
  m.add_function(wrap_pyfunction!(session_run_interactive_process, m)?)?;
  m.add_function(wrap_pyfunction!(session_get_observation_histograms, m)?)?;
  m.add_function(wrap_pyfunction!(session_record_test_observation, m)?)?;
  m.add_function(wrap_pyfunction!(session_isolated_shallow_clone, m)?)?;

  m.add_function(wrap_pyfunction!(single_file_digests_to_bytes, m)?)?;
  m.add_function(wrap_pyfunction!(ensure_remote_has_recursive, m)?)?;

  m.add_function(wrap_pyfunction!(scheduler_execute, m)?)?;
  m.add_function(wrap_pyfunction!(scheduler_metrics, m)?)?;
  m.add_function(wrap_pyfunction!(scheduler_create, m)?)?;
  m.add_function(wrap_pyfunction!(scheduler_shutdown, m)?)?;

  m.add_function(wrap_pyfunction!(strongly_connected_components, m)?)?;

  Ok(())
}

create_exception!(native_engine, PollTimeout, PyException);

#[pyclass]
#[derive(Debug)]
struct PyTasks(RefCell<Tasks>);

#[pymethods]
impl PyTasks {
  #[new]
  fn __new__() -> Self {
    Self(RefCell::new(Tasks::new()))
  }
}

#[pyclass]
#[derive(Debug)]
struct PyTypes(RefCell<Option<Types>>);

#[pymethods]
impl PyTypes {
  #[new]
  fn __new__(
    file_digest: &PyType,
    snapshot: &PyType,
    paths: &PyType,
    file_content: &PyType,
    file_entry: &PyType,
    directory: &PyType,
    digest_contents: &PyType,
    digest_entries: &PyType,
    path_globs: &PyType,
    merge_digests: &PyType,
    add_prefix: &PyType,
    remove_prefix: &PyType,
    create_digest: &PyType,
    digest_subset: &PyType,
    download_file: &PyType,
    platform: &PyType,
    multi_platform_process: &PyType,
    process_result: &PyType,
    process_result_metadata: &PyType,
    coroutine: &PyType,
    session_values: &PyType,
    run_id: &PyType,
    interactive_process: &PyType,
    interactive_process_result: &PyType,
    engine_aware_parameter: &PyType,
    py: Python,
  ) -> Self {
    Self(RefCell::new(Some(Types {
      directory_digest: TypeId::new(py.get_type::<externs::fs::PyDigest>()),
      file_digest: TypeId::new(file_digest),
      snapshot: TypeId::new(snapshot),
      paths: TypeId::new(paths),
      file_content: TypeId::new(file_content),
      file_entry: TypeId::new(file_entry),
      directory: TypeId::new(directory),
      digest_contents: TypeId::new(digest_contents),
      digest_entries: TypeId::new(digest_entries),
      path_globs: TypeId::new(path_globs),
      merge_digests: TypeId::new(merge_digests),
      add_prefix: TypeId::new(add_prefix),
      remove_prefix: TypeId::new(remove_prefix),
      create_digest: TypeId::new(create_digest),
      digest_subset: TypeId::new(digest_subset),
      download_file: TypeId::new(download_file),
      platform: TypeId::new(platform),
      multi_platform_process: TypeId::new(multi_platform_process),
      process_result: TypeId::new(process_result),
      process_result_metadata: TypeId::new(process_result_metadata),
      coroutine: TypeId::new(coroutine),
      session_values: TypeId::new(session_values),
      run_id: TypeId::new(run_id),
      interactive_process: TypeId::new(interactive_process),
      interactive_process_result: TypeId::new(interactive_process_result),
      engine_aware_parameter: TypeId::new(engine_aware_parameter),
    })))
  }
}

#[pyclass]
#[derive(Debug)]
struct PyExecutor(task_executor::Executor);

#[pymethods]
impl PyExecutor {
  #[new]
  fn __new__(core_threads: usize, max_threads: usize) -> PyO3Result<Self> {
    let executor = Executor::global(core_threads, max_threads).map_err(PyException::new_err)?;
    Ok(Self(executor))
  }
}

#[pyclass]
struct PyScheduler(Scheduler);

#[pyclass]
#[derive(Debug)]
struct PyStdioDestination(Arc<stdio::Destination>);

/// Represents configuration related to process execution strategies.
///
/// The data stored by PyExecutionStrategyOptions originally was passed directly into
/// scheduler_create but has been broken out separately because the large number of options
/// became unwieldy.
#[pyclass]
#[derive(Debug)]
struct PyExecutionStrategyOptions(ExecutionStrategyOptions);

#[pymethods]
impl PyExecutionStrategyOptions {
  #[new]
  fn __new__(
    local_parallelism: usize,
    remote_parallelism: usize,
    local_cleanup: bool,
    local_cache: bool,
    local_enable_nailgun: bool,
    remote_cache_read: bool,
    remote_cache_write: bool,
  ) -> Self {
    Self(ExecutionStrategyOptions {
      local_parallelism,
      remote_parallelism,
      local_cleanup,
      local_cache,
      local_enable_nailgun,
      remote_cache_read,
      remote_cache_write,
    })
  }
}

/// Represents configuration related to remote execution and caching.
#[pyclass]
#[derive(Debug)]
struct PyRemotingOptions(RemotingOptions);

#[pymethods]
impl PyRemotingOptions {
  #[new]
  fn __new__(
    execution_enable: bool,
    store_address: Option<String>,
    execution_address: Option<String>,
    execution_process_cache_namespace: Option<String>,
    instance_name: Option<String>,
    root_ca_certs_path: Option<String>,
    store_headers: Vec<(String, String)>,
    store_chunk_bytes: usize,
    store_chunk_upload_timeout: u64,
    store_rpc_retries: usize,
    store_rpc_concurrency: usize,
    store_batch_api_size_limit: usize,
    cache_warnings_behavior: String,
    cache_eager_fetch: bool,
    cache_rpc_concurrency: usize,
    execution_extra_platform_properties: Vec<(String, String)>,
    execution_headers: Vec<(String, String)>,
    execution_overall_deadline_secs: u64,
    execution_rpc_concurrency: usize,
  ) -> Self {
    Self(RemotingOptions {
      execution_enable,
      store_address,
      execution_address,
      execution_process_cache_namespace,
      instance_name,
      root_ca_certs_path: root_ca_certs_path.map(PathBuf::from),
      store_headers: store_headers.into_iter().collect(),
      store_chunk_bytes,
      store_chunk_upload_timeout: Duration::from_secs(store_chunk_upload_timeout),
      store_rpc_retries,
      store_rpc_concurrency,
      store_batch_api_size_limit,
      cache_warnings_behavior: RemoteCacheWarningsBehavior::from_str(&cache_warnings_behavior)
        .unwrap(),
      cache_eager_fetch,
      cache_rpc_concurrency,
      execution_extra_platform_properties,
      execution_headers: execution_headers.into_iter().collect(),
      execution_overall_deadline: Duration::from_secs(execution_overall_deadline_secs),
      execution_rpc_concurrency,
    })
  }
}

#[pyclass]
#[derive(Debug)]
struct PyLocalStoreOptions(LocalStoreOptions);

#[pymethods]
impl PyLocalStoreOptions {
  #[new]
  fn __new__(
    store_dir: String,
    process_cache_max_size_bytes: usize,
    files_max_size_bytes: usize,
    directories_max_size_bytes: usize,
    lease_time_millis: u64,
    shard_count: u8,
  ) -> PyO3Result<Self> {
    if shard_count.count_ones() != 1 {
      return Err(PyValueError::new_err(format!(
        "The local store shard count must be a power of two: got {}",
        shard_count
      )));
    }
    Ok(Self(LocalStoreOptions {
      store_dir: PathBuf::from(store_dir),
      process_cache_max_size_bytes,
      files_max_size_bytes,
      directories_max_size_bytes,
      lease_time: Duration::from_millis(lease_time_millis),
      shard_count,
    }))
  }
}

#[pyclass]
struct PySession(Session);

#[pymethods]
impl PySession {
  #[new]
  fn __new__(
    scheduler: &PyScheduler,
    should_render_ui: bool,
    build_id: String,
    session_values: PyObject,
    cancellation_latch: &PySessionCancellationLatch,
    py: Python,
  ) -> PyO3Result<Self> {
    let core = scheduler.0.core.clone();
    let cancellation_latch = cancellation_latch.0.clone();
    // NB: Session creation interacts with the Graph, which must not be accessed while the GIL is
    // held.
    let session = py
      .allow_threads(|| {
        Session::new(
          core,
          should_render_ui,
          build_id,
          session_values.into(),
          cancellation_latch,
        )
      })
      .map_err(PyException::new_err)?;
    Ok(Self(session))
  }

  fn cancel(&self) {
    self.0.cancel()
  }

  fn is_cancelled(&self) -> bool {
    self.0.is_cancelled()
  }
}

#[pyclass]
struct PySessionCancellationLatch(AsyncLatch);

#[pymethods]
impl PySessionCancellationLatch {
  #[new]
  fn __new__() -> Self {
    Self(AsyncLatch::new())
  }

  fn is_cancelled(&self) -> bool {
    self.0.poll_triggered()
  }
}

#[pyclass]
struct PyNailgunServer {
  server: RefCell<Option<nailgun::Server>>,
  executor: Executor,
}

#[pymethods]
impl PyNailgunServer {
  fn port(&self) -> PyO3Result<u16> {
    let borrowed_server = self.server.borrow();
    let server = borrowed_server.as_ref().ok_or_else(|| {
      PyException::new_err("Cannot get the port of a server that has already shut down.")
    })?;
    Ok(server.port())
  }
}

#[pyclass]
#[derive(Debug)]
struct PyExecutionRequest(RefCell<ExecutionRequest>);

#[pymethods]
impl PyExecutionRequest {
  #[new]
  fn __new__(poll: bool, poll_delay_in_ms: Option<u64>, timeout_in_ms: Option<u64>) -> Self {
    let request = ExecutionRequest {
      poll,
      poll_delay: poll_delay_in_ms.map(Duration::from_millis),
      timeout: timeout_in_ms.map(Duration::from_millis),
      ..ExecutionRequest::default()
    };
    Self(RefCell::new(request))
  }
}

#[pyclass]
#[derive(Debug)]
struct PyResult {
  #[pyo3(get)]
  is_throw: bool,
  #[pyo3(get)]
  result: PyObject,
  #[pyo3(get)]
  python_traceback: Option<String>,
  #[pyo3(get)]
  engine_traceback: Vec<String>,
}

fn py_result_from_root(py: Python, result: Result<Value, Failure>) -> PyResult {
  match result {
    Ok(val) => PyResult {
      is_throw: false,
      result: val.into(),
      python_traceback: None,
      engine_traceback: vec![],
    },
    Err(f) => {
      let (val, python_traceback, engine_traceback) = match f {
        f @ Failure::Invalidated => {
          let msg = format!("{}", f);
          let python_traceback = Failure::native_traceback(&msg);
          (
            externs::create_exception(py, msg),
            python_traceback,
            Vec::new(),
          )
        }
        Failure::Throw {
          val,
          python_traceback,
          engine_traceback,
        } => (val, python_traceback, engine_traceback),
      };
      PyResult {
        is_throw: true,
        result: val.into(),
        python_traceback: Some(python_traceback),
        engine_traceback,
      }
    }
  }
}

#[pyfunction]
fn nailgun_server_create(
  executor_ptr: &PyExecutor,
  port: u16,
  runner: PyObject,
) -> PyO3Result<PyNailgunServer> {
  with_executor(executor_ptr, |executor| {
    let server_future = {
      let executor = executor.clone();
      nailgun::Server::new(executor, port, move |exe: nailgun::RawFdExecution| {
        let gil = Python::acquire_gil();
        let py = gil.python();
        let result = runner.as_ref(py).call1((
          exe.cmd.command,
          PyTuple::new(py, exe.cmd.args),
          exe.cmd.env.into_iter().collect::<HashMap<String, String>>(),
          PySessionCancellationLatch(exe.cancelled),
          exe.stdin_fd as i64,
          exe.stdout_fd as i64,
          exe.stderr_fd as i64,
        ));
        match result {
          Ok(exit_code) => {
            let code: i32 = exit_code.extract().unwrap();
            nailgun::ExitCode(code)
          }
          Err(e) => {
            error!(
              "Uncaught exception in nailgun handler: {:#?}",
              Failure::from_py_err_with_gil(py, e)
            );
            nailgun::ExitCode(1)
          }
        }
      })
    };

    let server = executor
      .block_on(server_future)
      .map_err(PyException::new_err)?;
    Ok(PyNailgunServer {
      server: RefCell::new(Some(server)),
      executor: executor.clone(),
    })
  })
}

#[pyfunction]
fn nailgun_server_await_shutdown(
  py: Python,
  nailgun_server_ptr: &PyNailgunServer,
) -> PyO3Result<()> {
  if let Some(server) = nailgun_server_ptr.server.borrow_mut().take() {
    let executor = nailgun_server_ptr.executor.clone();
    py.allow_threads(|| executor.block_on(server.shutdown()))
      .map_err(PyException::new_err)
  } else {
    Ok(())
  }
}

#[pyfunction]
fn strongly_connected_components(
  py: Python,
  adjacency_lists: Vec<(PyObject, Vec<PyObject>)>,
) -> PyO3Result<Vec<Vec<PyObject>>> {
  let mut graph: DiGraph<Key, (), u32> = Graph::new();
  let mut node_ids: HashMap<Key, _> = HashMap::new();

  for (node, adjacency_list) in adjacency_lists {
    let node_key = Key::from_value(node.into())?;
    let node_id = *node_ids
      .entry(node_key)
      .or_insert_with(|| graph.add_node(node_key));
    for dependency in adjacency_list {
      let dependency_key = Key::from_value(dependency.into())?;
      let dependency_id = node_ids
        .entry(dependency_key)
        .or_insert_with(|| graph.add_node(dependency_key));
      graph.add_edge(node_id, *dependency_id, ());
    }
  }

  Ok(
    petgraph::algo::tarjan_scc(&graph)
      .into_iter()
      .map(|component| {
        component
          .into_iter()
          .map(|node_id| graph[node_id].to_value().consume_into_py_object(py))
          .collect::<Vec<_>>()
      })
      .collect(),
  )
}

///
/// Given a set of Tasks and type information, creates a Scheduler.
///
/// The given Tasks struct will be cloned, so no additional mutation of the reference will
/// affect the created Scheduler.
///
#[pyfunction]
fn scheduler_create(
  executor_ptr: &PyExecutor,
  tasks_ptr: &PyTasks,
  types_ptr: &PyTypes,
  build_root_buf: String,
  local_execution_root_dir_buf: String,
  named_caches_dir_buf: String,
  ca_certs_path_buf: Option<String>,
  ignore_patterns: Vec<String>,
  use_gitignore: bool,
  watch_filesystem: bool,
  remoting_options: &PyRemotingOptions,
  local_store_options: &PyLocalStoreOptions,
  exec_strategy_opts: &PyExecutionStrategyOptions,
) -> PyO3Result<PyScheduler> {
  match fs::increase_limits() {
    Ok(msg) => debug!("{}", msg),
    Err(e) => warn!("{}", e),
  }
  let core: Result<Core, String> = with_executor(executor_ptr, |executor| {
    let types = types_ptr
      .0
      .borrow_mut()
      .take()
      .ok_or_else(|| "An instance of PyTypes may only be used once.".to_owned())?;
    let intrinsics = Intrinsics::new(&types);
    let mut tasks = tasks_ptr.0.replace(Tasks::new());
    tasks.intrinsics_set(&intrinsics);

    // NOTE: Enter the Tokio runtime so that libraries like Tonic (for gRPC) are able to
    // use `tokio::spawn` since Python does not setup Tokio for the main thread. This also
    // ensures that the correct executor is used by those libraries.
    executor.enter(|| {
      Core::new(
        executor.clone(),
        tasks,
        types,
        intrinsics,
        PathBuf::from(build_root_buf),
        ignore_patterns,
        use_gitignore,
        watch_filesystem,
        PathBuf::from(local_execution_root_dir_buf),
        PathBuf::from(named_caches_dir_buf),
        ca_certs_path_buf.map(PathBuf::from),
        local_store_options.0.clone(),
        remoting_options.0.clone(),
        exec_strategy_opts.0.clone(),
      )
    })
  });
  let scheduler = Scheduler::new(core.map_err(PyValueError::new_err)?);
  Ok(PyScheduler(scheduler))
}

async fn workunit_to_py_value(
  workunit: &Workunit,
  core: &Arc<Core>,
  session: &Session,
) -> PyO3Result<Value> {
  let mut dict_entries = {
    let gil = Python::acquire_gil();
    let py = gil.python();
    let mut dict_entries = vec![
      (
        externs::store_utf8(py, "name"),
        externs::store_utf8(py, &workunit.name),
      ),
      (
        externs::store_utf8(py, "span_id"),
        externs::store_utf8(py, &format!("{}", workunit.span_id)),
      ),
      (
        externs::store_utf8(py, "level"),
        externs::store_utf8(py, &workunit.metadata.level.to_string()),
      ),
    ];

    if let Some(parent_id) = workunit.parent_id {
      dict_entries.push((
        externs::store_utf8(py, "parent_id"),
        externs::store_utf8(py, &format!("{}", parent_id)),
      ));
    }

    match workunit.state {
      WorkunitState::Started { start_time, .. } => {
        let duration = start_time
          .duration_since(std::time::UNIX_EPOCH)
          .unwrap_or_else(|_| Duration::default());
        dict_entries.extend_from_slice(&[
          (
            externs::store_utf8(py, "start_secs"),
            externs::store_u64(py, duration.as_secs()),
          ),
          (
            externs::store_utf8(py, "start_nanos"),
            externs::store_u64(py, duration.subsec_nanos() as u64),
          ),
        ])
      }
      WorkunitState::Completed { time_span } => {
        dict_entries.extend_from_slice(&[
          (
            externs::store_utf8(py, "start_secs"),
            externs::store_u64(py, time_span.start.secs),
          ),
          (
            externs::store_utf8(py, "start_nanos"),
            externs::store_u64(py, u64::from(time_span.start.nanos)),
          ),
          (
            externs::store_utf8(py, "duration_secs"),
            externs::store_u64(py, time_span.duration.secs),
          ),
          (
            externs::store_utf8(py, "duration_nanos"),
            externs::store_u64(py, u64::from(time_span.duration.nanos)),
          ),
        ]);
      }
    };

    if let Some(desc) = &workunit.metadata.desc.as_ref() {
      dict_entries.push((
        externs::store_utf8(py, "description"),
        externs::store_utf8(py, desc),
      ));
    }
    dict_entries
  };

  let mut artifact_entries = Vec::new();

  for (artifact_name, digest) in workunit.metadata.artifacts.iter() {
    let store = core.store();
    let py_val = match digest {
      ArtifactOutput::FileDigest(digest) => {
        let gil = Python::acquire_gil();
        crate::nodes::Snapshot::store_file_digest(gil.python(), &core.types, digest)
      }
      ArtifactOutput::Snapshot(digest) => {
        let snapshot = store::Snapshot::from_digest(store, *digest)
          .await
          .map_err(PyException::new_err)?;
        let gil = Python::acquire_gil();
        let py = gil.python();
        crate::nodes::Snapshot::store_snapshot(py, snapshot).map_err(PyException::new_err)?
      }
    };

    let gil = Python::acquire_gil();
    artifact_entries.push((
      externs::store_utf8(gil.python(), artifact_name.as_str()),
      py_val,
    ))
  }

  let gil = Python::acquire_gil();
  let py = gil.python();

  let mut user_metadata_entries = Vec::with_capacity(workunit.metadata.user_metadata.len());
  for (user_metadata_key, user_metadata_item) in workunit.metadata.user_metadata.iter() {
    let value = match user_metadata_item {
      UserMetadataItem::ImmediateString(v) => externs::store_utf8(py, v),
      UserMetadataItem::ImmediateInt(n) => externs::store_i64(py, *n),
      UserMetadataItem::PyValue(py_val_handle) => {
        match session.with_metadata_map(|map| map.get(py_val_handle).cloned()) {
          None => {
            log::warn!(
              "Workunit metadata() value not found for key: {}",
              user_metadata_key
            );
            continue;
          }
          Some(v) => v,
        }
      }
    };
    user_metadata_entries.push((externs::store_utf8(py, user_metadata_key.as_str()), value));
  }

  dict_entries.push((
    externs::store_utf8(py, "metadata"),
    externs::store_dict(py, user_metadata_entries)?,
  ));

  if let Some(stdout_digest) = &workunit.metadata.stdout.as_ref() {
    artifact_entries.push((
      externs::store_utf8(py, "stdout_digest"),
      crate::nodes::Snapshot::store_file_digest(py, &core.types, stdout_digest),
    ));
  }

  if let Some(stderr_digest) = &workunit.metadata.stderr.as_ref() {
    artifact_entries.push((
      externs::store_utf8(py, "stderr_digest"),
      crate::nodes::Snapshot::store_file_digest(py, &core.types, stderr_digest),
    ));
  }

  dict_entries.push((
    externs::store_utf8(py, "artifacts"),
    externs::store_dict(py, artifact_entries)?,
  ));

  if !workunit.counters.is_empty() {
    let counters_entries = workunit
      .counters
      .iter()
      .map(|(counter_name, counter_value)| {
        (
          externs::store_utf8(py, counter_name.as_ref()),
          externs::store_u64(py, *counter_value),
        )
      })
      .collect();

    dict_entries.push((
      externs::store_utf8(py, "counters"),
      externs::store_dict(py, counters_entries)?,
    ));
  }

  externs::store_dict(py, dict_entries)
}

async fn workunits_to_py_tuple_value<'a>(
  workunits: impl Iterator<Item = &'a Workunit>,
  core: &Arc<Core>,
  session: &Session,
) -> PyO3Result<Value> {
  let mut workunit_values = Vec::new();
  for workunit in workunits {
    let py_value = workunit_to_py_value(workunit, core, session).await?;
    workunit_values.push(py_value);
  }

  let gil = Python::acquire_gil();
  Ok(externs::store_tuple(gil.python(), workunit_values))
}

#[pyfunction]
fn session_poll_workunits(
  py: Python,
  scheduler_ptr: &PyScheduler,
  session_ptr: &PySession,
  max_log_verbosity_level: u64,
) -> PyO3Result<PyObject> {
  let py_level: PythonLogLevel = max_log_verbosity_level
    .try_into()
    .map_err(|e| PyException::new_err(format!("{}", e)))?;
  let (started, completed) = with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      let core = scheduler.core.clone();
      py.allow_threads(|| {
        session
          .workunit_store()
          .with_latest_workunits(py_level.into(), |started, completed| {
            let mut started_iter = started.iter();
            let started = core.executor.block_on(workunits_to_py_tuple_value(
              &mut started_iter,
              &scheduler.core,
              session,
            ))?;

            let mut completed_iter = completed.iter();
            let completed = core.executor.block_on(workunits_to_py_tuple_value(
              &mut completed_iter,
              &scheduler.core,
              session,
            ))?;
            let res: PyO3Result<(Value, Value)> = Ok((started, completed));
            res
          })
      })
    })
  })?;
  Ok(externs::store_tuple(py, vec![started, completed]).into())
}

#[pyfunction]
fn session_run_interactive_process(
  py: Python,
  session_ptr: &PySession,
  interactive_process: PyObject,
) -> PyO3Result<PyObject> {
  with_session(session_ptr, |session| {
    let core = session.core().clone();
    let context = Context::new(core.clone(), session.clone());
    let interactive_process: Value = interactive_process.into();
    py.allow_threads(|| {
      context
        .core
        .executor
        .clone()
        .block_on(nodes::maybe_side_effecting(
          true,
          &Arc::new(std::sync::atomic::AtomicBool::new(true)),
          core.intrinsics.run(
            Intrinsic {
              product: context.core.types.interactive_process_result,
              inputs: vec![context.core.types.interactive_process],
            },
            context,
            vec![interactive_process],
          ),
        ))
    })
    .map(|v| v.into())
    .map_err(|e| PyException::new_err(e.to_string()))
  })
}

#[pyfunction]
fn scheduler_metrics(
  py: Python,
  scheduler_ptr: &PyScheduler,
  session_ptr: &PySession,
) -> PyO3Result<PyObject> {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      let values = scheduler
        .metrics(session)
        .into_iter()
        .map(|(metric, value)| {
          (
            externs::store_utf8(py, metric),
            externs::store_i64(py, value),
          )
        })
        .collect::<Vec<_>>();
      externs::store_dict(py, values).map(|d| d.consume_into_py_object(py))
    })
  })
}

#[pyfunction]
fn scheduler_shutdown(py: Python, scheduler_ptr: &PyScheduler, timeout_secs: u64) {
  with_scheduler(scheduler_ptr, |scheduler| {
    py.allow_threads(|| {
      scheduler
        .core
        .executor
        .block_on(scheduler.core.shutdown(Duration::from_secs(timeout_secs)));
    })
  });
}

#[pyfunction]
fn scheduler_execute<'py>(
  py: Python<'py>,
  scheduler_ptr: &PyScheduler,
  session_ptr: &PySession,
  execution_request_ptr: &PyExecutionRequest,
) -> PyO3Result<&'py PyTuple> {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_execution_request(execution_request_ptr, |execution_request| {
      with_session(session_ptr, |session| {
        // TODO: A parent_id should be an explicit argument.
        session.workunit_store().init_thread_state(None);
        let execute_result = py.allow_threads(|| scheduler.execute(execution_request, session));
        execute_result
          .map(|root_results| {
            let py_results = root_results
              .into_iter()
              .map(|err| Py::new(py, py_result_from_root(py, err)).unwrap())
              .collect::<Vec<_>>();
            PyTuple::new(py, &py_results)
          })
          .map_err(|e| match e {
            ExecutionTermination::KeyboardInterrupt => PyKeyboardInterrupt::new_err(()),
            ExecutionTermination::PollTimeout => PollTimeout::new_err(()),
            ExecutionTermination::Fatal(msg) => PyException::new_err(msg),
          })
      })
    })
  })
}

#[pyfunction]
fn execution_add_root_select(
  scheduler_ptr: &PyScheduler,
  execution_request_ptr: &PyExecutionRequest,
  param_vals: Vec<PyObject>,
  product: &PyType,
) -> PyO3Result<()> {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_execution_request(execution_request_ptr, |execution_request| {
      let product = TypeId::new(product);
      let keys = param_vals
        .into_iter()
        .map(|p| Key::from_value(p.into()))
        .collect::<Result<Vec<_>, _>>()?;
      Params::new(keys)
        .and_then(|params| scheduler.add_root_select(execution_request, params, product))
        .map_err(PyException::new_err)
    })
  })
}

#[pyfunction]
fn tasks_task_begin(
  tasks_ptr: &PyTasks,
  func: PyObject,
  output_type: &PyType,
  side_effecting: bool,
  engine_aware_return_type: bool,
  cacheable: bool,
  name: String,
  desc: String,
  level: u64,
) -> PyO3Result<()> {
  let py_level: PythonLogLevel = level
    .try_into()
    .map_err(|e| PyException::new_err(format!("{}", e)))?;
  with_tasks(tasks_ptr, |tasks| {
    let func = Function(Key::from_value(func.into())?);
    let output_type = TypeId::new(output_type);
    tasks.task_begin(
      func,
      output_type,
      side_effecting,
      engine_aware_return_type,
      cacheable,
      name,
      if desc.is_empty() { None } else { Some(desc) },
      py_level.into(),
    );
    Ok(())
  })
}

#[pyfunction]
fn tasks_task_end(tasks_ptr: &PyTasks) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.task_end();
  })
}

#[pyfunction]
fn tasks_add_get(tasks_ptr: &PyTasks, output: &PyType, input: &PyType) {
  with_tasks(tasks_ptr, |tasks| {
    let output = TypeId::new(output);
    let input = TypeId::new(input);
    tasks.add_get(output, input);
  })
}

#[pyfunction]
fn tasks_add_union(tasks_ptr: &PyTasks, output_type: &PyType, input_types: Vec<&PyType>) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.add_union(
      TypeId::new(output_type),
      input_types
        .into_iter()
        .map(|type_id| TypeId::new(type_id))
        .collect(),
    );
  })
}

#[pyfunction]
fn tasks_add_select(tasks_ptr: &PyTasks, selector: &PyType) {
  with_tasks(tasks_ptr, |tasks| {
    let selector = TypeId::new(selector);
    tasks.add_select(selector);
  })
}

#[pyfunction]
fn tasks_add_query(tasks_ptr: &PyTasks, output_type: &PyType, input_types: Vec<&PyType>) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.query_add(
      TypeId::new(output_type),
      input_types
        .into_iter()
        .map(|type_id| TypeId::new(type_id))
        .collect(),
    );
  })
}

#[pyfunction]
fn graph_invalidate_paths(py: Python, scheduler_ptr: &PyScheduler, paths: Vec<String>) -> u64 {
  with_scheduler(scheduler_ptr, |scheduler| {
    let paths = paths.into_iter().map(PathBuf::from).collect();
    py.allow_threads(|| scheduler.invalidate_paths(&paths) as u64)
  })
}

#[pyfunction]
fn graph_invalidate_all_paths(py: Python, scheduler_ptr: &PyScheduler) -> u64 {
  with_scheduler(scheduler_ptr, |scheduler| {
    py.allow_threads(|| scheduler.invalidate_all_paths() as u64)
  })
}

#[pyfunction]
fn graph_invalidate_all(py: Python, scheduler_ptr: &PyScheduler) {
  with_scheduler(scheduler_ptr, |scheduler| {
    py.allow_threads(|| scheduler.invalidate_all());
  })
}

#[pyfunction]
fn check_invalidation_watcher_liveness(scheduler_ptr: &PyScheduler) -> PyO3Result<()> {
  with_scheduler(scheduler_ptr, |scheduler| {
    scheduler.is_valid().map_err(PyException::new_err)
  })
}

#[pyfunction]
fn graph_len(py: Python, scheduler_ptr: &PyScheduler) -> u64 {
  with_scheduler(scheduler_ptr, |scheduler| {
    py.allow_threads(|| scheduler.core.graph.len() as u64)
  })
}

#[pyfunction]
fn graph_visualize(
  py: Python,
  scheduler_ptr: &PyScheduler,
  session_ptr: &PySession,
  path: String,
) -> PyO3Result<()> {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      let path = PathBuf::from(path);
      // NB: See the note on with_scheduler re: allow_threads.
      py.allow_threads(|| scheduler.visualize(session, path.as_path()))
        .map_err(|e| {
          PyException::new_err(format!(
            "Failed to visualize to {}: {:?}",
            path.display(),
            e
          ))
        })
    })
  })
}

#[pyfunction]
fn session_new_run_id(session_ptr: &PySession) {
  with_session(session_ptr, |session| {
    session.new_run_id();
  })
}

#[pyfunction]
fn session_get_observation_histograms<'py>(
  py: Python<'py>,
  scheduler_ptr: &PyScheduler,
  session_ptr: &PySession,
) -> PyO3Result<&'py PyDict> {
  // Encoding version to return to callers. This should be bumped when the encoded histograms
  // are encoded in a backwards-incompatible manner.
  const OBSERVATIONS_VERSION: u64 = 0;

  with_scheduler(scheduler_ptr, |_scheduler| {
    with_session(session_ptr, |session| {
      let observations = session
        .workunit_store()
        .encode_observations()
        .map_err(PyException::new_err)?;

      let encoded_observations = PyDict::new(py);
      for (metric, encoded_histogram) in &observations {
        encoded_observations.set_item(
          PyString::new(py, metric.as_str()),
          PyBytes::new(py, &encoded_histogram[..]),
        )?;
      }

      let result = PyDict::new(py);
      result.set_item(PyString::new(py, "version"), OBSERVATIONS_VERSION)?;
      result.set_item(PyString::new(py, "histograms"), encoded_observations)?;
      Ok(result)
    })
  })
}

#[pyfunction]
fn session_record_test_observation(
  scheduler_ptr: &PyScheduler,
  session_ptr: &PySession,
  value: u64,
) {
  with_scheduler(scheduler_ptr, |_scheduler| {
    with_session(session_ptr, |session| {
      session
        .workunit_store()
        .record_observation(ObservationMetric::TestObservation, value);
    })
  })
}

#[pyfunction]
fn session_isolated_shallow_clone(
  session_ptr: &PySession,
  build_id: String,
) -> PyO3Result<PySession> {
  with_session(session_ptr, |session| {
    let session_clone = session
      .isolated_shallow_clone(build_id)
      .map_err(PyException::new_err)?;
    Ok(PySession(session_clone))
  })
}

#[pyfunction]
fn validate_reachability(scheduler_ptr: &PyScheduler) -> PyO3Result<()> {
  with_scheduler(scheduler_ptr, |scheduler| {
    scheduler
      .core
      .rule_graph
      .validate_reachability()
      .map_err(PyException::new_err)
  })
}

#[pyfunction]
fn rule_graph_consumed_types<'py>(
  py: Python<'py>,
  scheduler_ptr: &PyScheduler,
  param_types: Vec<&PyType>,
  product_type: &PyType,
) -> PyO3Result<Vec<&'py PyType>> {
  with_scheduler(scheduler_ptr, |scheduler| {
    let param_types = param_types
      .into_iter()
      .map(|type_id| TypeId::new(type_id))
      .collect::<Vec<_>>();

    let subgraph = scheduler
      .core
      .rule_graph
      .subgraph(param_types, TypeId::new(product_type))
      .map_err(PyValueError::new_err)?;

    Ok(
      subgraph
        .consumed_types()
        .into_iter()
        .map(|type_id| type_id.as_py_type(py))
        .collect(),
    )
  })
}

#[pyfunction]
fn rule_graph_visualize(scheduler_ptr: &PyScheduler, path: String) -> PyO3Result<()> {
  with_scheduler(scheduler_ptr, |scheduler| {
    let path = PathBuf::from(path);

    // TODO(#7117): we want to represent union types in the graph visualizer somehow!!!
    write_to_file(path.as_path(), &scheduler.core.rule_graph).map_err(|e| {
      PyIOError::new_err(format!(
        "Failed to visualize to {}: {:?}",
        path.display(),
        e
      ))
    })
  })
}

#[pyfunction]
fn rule_subgraph_visualize(
  scheduler_ptr: &PyScheduler,
  param_types: Vec<&PyType>,
  product_type: &PyType,
  path: String,
) -> PyO3Result<()> {
  with_scheduler(scheduler_ptr, |scheduler| {
    let param_types = param_types
      .into_iter()
      .map(|py_type| TypeId::new(py_type))
      .collect::<Vec<_>>();
    let product_type = TypeId::new(product_type);
    let path = PathBuf::from(path);

    // TODO(#7117): we want to represent union types in the graph visualizer somehow!!!
    let subgraph = scheduler
      .core
      .rule_graph
      .subgraph(param_types, product_type)
      .map_err(PyValueError::new_err)?;

    write_to_file(path.as_path(), &subgraph).map_err(|e| {
      PyIOError::new_err(format!(
        "Failed to visualize to {}: {:?}",
        path.display(),
        e
      ))
    })
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

/// Set up a panic handler, unless RUST_BACKTRACE is set.
#[pyfunction]
fn maybe_set_panic_handler() {
  if std::env::var("RUST_BACKTRACE").unwrap_or_else(|_| "0".to_owned()) != "0" {
    return;
  }
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
}

#[pyfunction]
fn garbage_collect_store(
  py: Python,
  scheduler_ptr: &PyScheduler,
  target_size_bytes: usize,
) -> PyO3Result<()> {
  with_scheduler(scheduler_ptr, |scheduler| {
    py.allow_threads(|| {
      scheduler
        .core
        .store()
        .garbage_collect(target_size_bytes, store::ShrinkBehavior::Fast)
    })
    .map_err(PyException::new_err)
  })
}

#[pyfunction]
fn lease_files_in_graph(
  py: Python,
  scheduler_ptr: &PyScheduler,
  session_ptr: &PySession,
) -> PyO3Result<()> {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      // NB: See the note on with_scheduler re: allow_threads.
      py.allow_threads(|| {
        let digests = scheduler.all_digests(session);
        scheduler
          .core
          .executor
          .block_on(scheduler.core.store().lease_all_recursively(digests.iter()))
      })
      .map_err(PyException::new_err)
    })
  })
}

#[pyfunction]
fn capture_snapshots(
  py: Python,
  scheduler_ptr: &PyScheduler,
  session_ptr: &PySession,
  path_globs_and_root_tuple_wrapper: &PyAny,
) -> PyO3Result<PyObject> {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      // TODO: A parent_id should be an explicit argument.
      session.workunit_store().init_thread_state(None);
      let core = scheduler.core.clone();

      let values = externs::collect_iterable(path_globs_and_root_tuple_wrapper).unwrap();
      let path_globs_and_roots = values
        .into_iter()
        .map(|value| {
          let root = PathBuf::from(externs::getattr::<String>(value, "root").unwrap());
          let path_globs = nodes::Snapshot::lift_prepared_path_globs(
            externs::getattr(value, "path_globs").unwrap(),
          );
          let digest_hint = {
            let maybe_digest: &PyAny = externs::getattr(value, "digest_hint").unwrap();
            if maybe_digest.is_none() {
              None
            } else {
              Some(nodes::lift_directory_digest(maybe_digest)?)
            }
          };
          path_globs.map(|path_globs| (path_globs, root, digest_hint))
        })
        .collect::<Result<Vec<_>, _>>()
        .map_err(PyValueError::new_err)?;

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
            let gil = Python::acquire_gil();
            nodes::Snapshot::store_snapshot(gil.python(), snapshot)
          }
        })
        .collect::<Vec<_>>();
      py.allow_threads(|| {
        let gil = Python::acquire_gil();
        core.executor.block_on(
          future::try_join_all(snapshot_futures)
            .map_ok(|values| externs::store_tuple(gil.python(), values).into()),
        )
      })
      .map_err(PyException::new_err)
    })
  })
}

#[pyfunction]
fn ensure_remote_has_recursive(
  py: Python,
  scheduler_ptr: &PyScheduler,
  py_digests: &PyList,
) -> PyO3Result<()> {
  with_scheduler(scheduler_ptr, |scheduler| {
    let core = scheduler.core.clone();
    let store = core.store();

    // NB: Supports either a FileDigest or Digest as input.
    let digests: Vec<Digest> = py_digests
      .iter()
      .map(|value| {
        crate::nodes::lift_directory_digest(value)
          .or_else(|_| crate::nodes::lift_file_digest(&core.types, value))
      })
      .collect::<Result<Vec<Digest>, _>>()
      .map_err(PyException::new_err)?;

    py.allow_threads(|| {
      core
        .executor
        .block_on(store.ensure_remote_has_recursive(digests))
    })
    .map_err(PyException::new_err)?;
    Ok(())
  })
}

/// This functions assumes that the Digest in question represents the contents of a single File rather than a Directory,
/// and will fail on Digests representing a Directory.
#[pyfunction]
fn single_file_digests_to_bytes<'py>(
  py: Python<'py>,
  scheduler_ptr: &PyScheduler,
  py_file_digests: &PyList,
) -> PyO3Result<&'py PyList> {
  with_scheduler(scheduler_ptr, |scheduler| {
    let core = scheduler.core.clone();

    let digests: Vec<Digest> = py_file_digests
      .iter()
      .map(|item| crate::nodes::lift_file_digest(&core.types, item))
      .collect::<Result<Vec<Digest>, _>>()
      .map_err(PyException::new_err)?;

    let digest_futures = digests.into_iter().map(|digest| {
      let store = core.store();
      async move {
        store
          .load_file_bytes_with(digest, |bytes| {
            let gil = Python::acquire_gil();
            let py = gil.python();
            externs::store_bytes(py, bytes)
          })
          .await
          .and_then(|maybe_bytes| {
            maybe_bytes.ok_or_else(|| format!("Error loading bytes from digest: {:?}", digest))
          })
      }
    });

    let bytes_values: Vec<PyObject> = py
      .allow_threads(|| {
        core.executor.block_on(
          future::try_join_all(digest_futures)
            .map_ok(|values: Vec<Value>| values.into_iter().map(|val| val.into()).collect()),
        )
      })
      .map_err(PyException::new_err)?;

    let output_list = PyList::new(py, &bytes_values);
    Ok(output_list)
  })
}

#[pyfunction]
fn write_digest(
  py: Python,
  scheduler_ptr: &PyScheduler,
  session_ptr: &PySession,
  digest: &PyAny,
  path_prefix: String,
) -> PyO3Result<()> {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      // TODO: A parent_id should be an explicit argument.
      session.workunit_store().init_thread_state(None);

      let lifted_digest = nodes::lift_directory_digest(digest).map_err(PyValueError::new_err)?;

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
      .map_err(PyValueError::new_err)
    })
  })
}

#[pyfunction]
fn stdio_initialize(
  py: Python,
  level: u64,
  show_rust_3rdparty_logs: bool,
  show_target: bool,
  log_levels_by_target: HashMap<String, u64>,
  literal_filters: Vec<String>,
  regex_filters: Vec<String>,
  log_file: String,
) -> PyO3Result<&PyTuple> {
  let regex_filters = regex_filters
    .iter()
    .map(|re| {
      Regex::new(re).map_err(|e| {
        PyException::new_err(
          format!(
            "Failed to parse warning filter. Please check the global option `--ignore-warnings`.\n\n{}",
            e,
          )
        )
      })
    })
    .collect::<Result<Vec<Regex>, _>>()?;

  Logger::init(
    level,
    show_rust_3rdparty_logs,
    show_target,
    log_levels_by_target,
    literal_filters,
    regex_filters,
    PathBuf::from(log_file),
  )
  .map_err(|s| PyException::new_err(format!("Could not initialize logging: {}", s)))?;

  Ok(PyTuple::new(
    py,
    &[
      Py::new(py, externs::stdio::PyStdioRead)?.into_py(py),
      Py::new(py, externs::stdio::PyStdioWrite { is_stdout: true })?.into_py(py),
      Py::new(py, externs::stdio::PyStdioWrite { is_stdout: false })?.into_py(py),
    ],
  ))
}

#[pyfunction]
fn stdio_thread_console_set(stdin_fileno: i32, stdout_fileno: i32, stderr_fileno: i32) {
  let destination = stdio::new_console_destination(stdin_fileno, stdout_fileno, stderr_fileno);
  stdio::set_thread_destination(destination);
}

#[pyfunction]
fn stdio_thread_console_color_mode_set(use_color: bool) {
  stdio::get_destination().stderr_set_use_color(use_color);
}

#[pyfunction]
fn stdio_thread_console_clear() {
  stdio::get_destination().console_clear();
}

#[pyfunction]
fn stdio_thread_get_destination() -> PyStdioDestination {
  let dest = stdio::get_destination();
  PyStdioDestination(dest)
}

#[pyfunction]
fn stdio_thread_set_destination(stdio_destination: &PyStdioDestination) {
  stdio::set_thread_destination(stdio_destination.0.clone());
}

// TODO: Needs to be thread-local / associated with the Console.
#[pyfunction]
fn set_per_run_log_path(py: Python, log_path: Option<String>) {
  py.allow_threads(|| {
    PANTS_LOGGER.set_per_run_logs(log_path.map(PathBuf::from));
  })
}

#[pyfunction]
fn write_log(py: Python, msg: String, level: u64, target: String) {
  py.allow_threads(|| {
    Logger::log_from_python(&msg, level, &target).expect("Error logging message");
  })
}

#[pyfunction]
fn task_side_effected() -> PyO3Result<()> {
  nodes::task_side_effected().map_err(PyException::new_err)
}

#[pyfunction]
fn teardown_dynamic_ui(py: Python, scheduler_ptr: &PyScheduler, session_ptr: &PySession) {
  with_scheduler(scheduler_ptr, |_scheduler| {
    with_session(session_ptr, |session| {
      let _ = block_in_place_and_wait(py, || {
        session.maybe_display_teardown().unit_error().boxed_local()
      });
    })
  })
}

#[pyfunction]
fn flush_log(py: Python) {
  py.allow_threads(|| {
    PANTS_LOGGER.flush();
  })
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
  F: Future<Output = Result<T, E>>,
  T: Send,
  E: Send,
{
  py.allow_threads(|| {
    let future = f();
    tokio::task::block_in_place(|| futures::executor::block_on(future))
  })
}

///
/// Scheduler, Session, and nailgun::Server are intended to be shared between threads, and so their
/// context methods provide immutable references. The remaining types are not intended to be shared
/// between threads, so mutable access is provided.
///
/// TODO: The `Scheduler` and `Session` objects both have lots of internal locks: in general, the GIL
/// should be released (using `py.allow_thread(|| ..)`) before any non-trivial interactions with
/// them. In particular: methods that use the `Graph` should be called outside the GIL. We should
/// make this less error prone: see https://github.com/pantsbuild/pants/issues/11722.
///
fn with_scheduler<F, T>(scheduler_ptr: &PyScheduler, f: F) -> T
where
  F: FnOnce(&Scheduler) -> T,
{
  let scheduler = &scheduler_ptr.0.clone();
  scheduler.core.executor.enter(|| f(scheduler))
}

/// See `with_scheduler`.
fn with_executor<F, T>(executor_ptr: &PyExecutor, f: F) -> T
where
  F: FnOnce(&Executor) -> T,
{
  let executor = &executor_ptr.0.clone();
  f(executor)
}

/// See `with_scheduler`.
fn with_session<F, T>(session_ptr: &PySession, f: F) -> T
where
  F: FnOnce(&Session) -> T,
{
  let session = &session_ptr.0.clone();
  f(session)
}

/// See `with_scheduler`.
fn with_execution_request<F, T>(execution_request_ptr: &PyExecutionRequest, f: F) -> T
where
  F: FnOnce(&mut ExecutionRequest) -> T,
{
  let mut execution_request = execution_request_ptr.0.borrow_mut();
  f(&mut execution_request)
}

/// See `with_scheduler`.
fn with_tasks<F, T>(tasks_ptr: &PyTasks, f: F) -> T
where
  F: FnOnce(&mut Tasks) -> T,
{
  let mut tasks = tasks_ptr.0.borrow_mut();
  f(&mut tasks)
}
