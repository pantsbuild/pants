// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// File-specific allowances to silence internal warnings of `[pyclass]`.
#![allow(clippy::used_underscore_binding)]

/// This crate is a wrapper around the engine crate which exposes a Python module via PyO3.
use std::any::Any;
use std::collections::hash_map::HashMap;
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::convert::TryInto;
use std::fs::File;
use std::hash::Hasher;
use std::io;
use std::panic;
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::sync::Arc;
use std::sync::LazyLock;
use std::time::Duration;

use async_latch::AsyncLatch;
use fnv::FnvHasher;
use fs::DirectoryDigest;
use futures::Future;
use futures::future::{self, FutureExt};
use hashing::Digest;
use log::{self, Log, debug, error, warn};
use logging::logger::PANTS_LOGGER;
use logging::{Logger, PythonLogLevel};
use parking_lot::Mutex as SyncMutex;
use petgraph::graph::{DiGraph, Graph};
use process_execution::CacheContentBehavior;
use pyo3::exceptions::{PyException, PyIOError, PyKeyboardInterrupt, PyValueError};
use pyo3::prelude::{
    PyModule, PyResult as PyO3Result, Python, pyclass, pyfunction, pymethods, pymodule,
    wrap_pyfunction,
};
use pyo3::sync::MutexExt;
use pyo3::types::{
    PyAnyMethods, PyBytes, PyDict, PyDictMethods, PyList, PyListMethods, PyModuleMethods, PyTuple,
    PyType,
};
use pyo3::{Bound, IntoPyObject, Py, PyAny, PyRef, create_exception};
use regex::Regex;
use remote::remote_cache::RemoteCacheWarningsBehavior;
use rule_graph::{self, RuleGraph, RuleId};
use store::RemoteProvider;
use task_executor::Executor;
use tokio::sync::Mutex;
use workunit_store::{
    ArtifactOutput, ObservationMetric, UserMetadataItem, Workunit, WorkunitState, WorkunitStore,
    WorkunitStoreHandle,
};

use crate::externs::fs::{PyFileDigest, possible_store_missing_digest};
use crate::externs::process::PyProcessExecutionEnvironment;
use crate::intrinsics;
use crate::{
    Core, ExecutionRequest, ExecutionStrategyOptions, ExecutionTermination, Failure, Function, Key,
    LocalStoreOptions, Params, RemotingOptions, Rule, Scheduler, Session, SessionCore, Tasks,
    TypeId, Types, Value, externs, nodes,
};

#[pymodule]
fn native_engine(py: Python, m: &Bound<'_, PyModule>) -> PyO3Result<()> {
    intrinsics::register(py, m)?;
    externs::register(py, m)?;
    externs::address::register(py, m)?;
    externs::fs::register(m)?;
    externs::nailgun::register(py, m)?;
    externs::options::register(m)?;
    externs::process::register(m)?;
    externs::pantsd::register(py, m)?;
    externs::scheduler::register(m)?;
    externs::target::register(m)?;
    externs::testutil::register(m)?;
    externs::workunits::register(m)?;
    externs::dep_inference::register(m)?;
    externs::unions::register(py, m)?;

    m.add("PollTimeout", py.get_type::<PollTimeout>())?;

    m.add_class::<PyExecutionRequest>()?;
    m.add_class::<PyExecutionStrategyOptions>()?;
    m.add_class::<PyLocalStoreOptions>()?;
    m.add_class::<PyNailgunServer>()?;
    m.add_class::<PyRemotingOptions>()?;
    m.add_class::<PyResult>()?;
    m.add_class::<PyScheduler>()?;
    m.add_class::<PySession>()?;
    m.add_class::<PySessionCancellationLatch>()?;
    m.add_class::<PyStdioDestination>()?;
    m.add_class::<PyTasks>()?;
    m.add_class::<PyThreadLocals>()?;
    m.add_class::<PyTypes>()?;

    m.add_function(wrap_pyfunction!(initialize, m)?)?;

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
    m.add_function(wrap_pyfunction!(tasks_add_call, m)?)?;
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
    m.add_function(wrap_pyfunction!(session_get_metrics, m)?)?;
    m.add_function(wrap_pyfunction!(session_get_observation_histograms, m)?)?;
    m.add_function(wrap_pyfunction!(session_record_test_observation, m)?)?;
    m.add_function(wrap_pyfunction!(session_isolated_shallow_clone, m)?)?;
    m.add_function(wrap_pyfunction!(session_wait_for_tail_tasks, m)?)?;

    m.add_function(wrap_pyfunction!(single_file_digests_to_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(ensure_remote_has_recursive, m)?)?;
    m.add_function(wrap_pyfunction!(ensure_directory_digest_persisted, m)?)?;

    m.add_function(wrap_pyfunction!(scheduler_execute, m)?)?;
    m.add_function(wrap_pyfunction!(scheduler_metrics, m)?)?;
    m.add_function(wrap_pyfunction!(scheduler_live_items, m)?)?;
    m.add_function(wrap_pyfunction!(scheduler_create, m)?)?;
    m.add_function(wrap_pyfunction!(scheduler_shutdown, m)?)?;

    m.add_function(wrap_pyfunction!(strongly_connected_components, m)?)?;
    m.add_function(wrap_pyfunction!(hash_prefix_zero_bits, m)?)?;

    Ok(())
}

create_exception!(native_engine, PollTimeout, PyException);

#[pyfunction]
pub fn initialize() -> PyO3Result<()> {
    grpc_util::initialize().expect("startup initialization failed");
    Ok(())
}

#[pyclass]
struct PyTasks(SyncMutex<Option<Tasks>>);

#[pymethods]
impl PyTasks {
    #[new]
    fn __new__() -> Self {
        Self(SyncMutex::new(Some(Tasks::new())))
    }
}

#[pyclass]
struct PyTypes(SyncMutex<Option<Types>>);

#[pymethods]
impl PyTypes {
    #[new]
    fn __new__(
        paths: &Bound<'_, PyType>,
        path_metadata_request: &Bound<'_, PyType>,
        path_metadata_result: &Bound<'_, PyType>,
        file_content: &Bound<'_, PyType>,
        file_entry: &Bound<'_, PyType>,
        symlink_entry: &Bound<'_, PyType>,
        directory: &Bound<'_, PyType>,
        digest_contents: &Bound<'_, PyType>,
        digest_entries: &Bound<'_, PyType>,
        path_globs: &Bound<'_, PyType>,
        create_digest: &Bound<'_, PyType>,
        digest_subset: &Bound<'_, PyType>,
        native_download_file: &Bound<'_, PyType>,
        platform: &Bound<'_, PyType>,
        process: &Bound<'_, PyType>,
        process_result: &Bound<'_, PyType>,
        process_result_metadata: &Bound<'_, PyType>,
        coroutine: &Bound<'_, PyType>,
        session_values: &Bound<'_, PyType>,
        run_id: &Bound<'_, PyType>,
        interactive_process: &Bound<'_, PyType>,
        interactive_process_result: &Bound<'_, PyType>,
        engine_aware_parameter: &Bound<'_, PyType>,
        docker_resolve_image_request: &Bound<'_, PyType>,
        docker_resolve_image_result: &Bound<'_, PyType>,
        parsed_python_deps_result: &Bound<'_, PyType>,
        parsed_javascript_deps_result: &Bound<'_, PyType>,
        parsed_dockerfile_info_result: &Bound<'_, PyType>,
        parsed_javascript_deps_candidate_result: &Bound<'_, PyType>,
        py: Python,
    ) -> Self {
        Self(SyncMutex::new(Some(Types {
            directory_digest: TypeId::new(&py.get_type::<externs::fs::PyDigest>()),
            file_digest: TypeId::new(&py.get_type::<externs::fs::PyFileDigest>()),
            snapshot: TypeId::new(&py.get_type::<externs::fs::PySnapshot>()),
            paths: TypeId::new(paths),
            path_metadata_request: TypeId::new(path_metadata_request),
            path_metadata_result: TypeId::new(path_metadata_result),
            file_content: TypeId::new(file_content),
            file_entry: TypeId::new(file_entry),
            symlink_entry: TypeId::new(symlink_entry),
            directory: TypeId::new(directory),
            digest_contents: TypeId::new(digest_contents),
            digest_entries: TypeId::new(digest_entries),
            path_globs: TypeId::new(path_globs),
            merge_digests: TypeId::new(&py.get_type::<externs::fs::PyMergeDigests>()),
            add_prefix: TypeId::new(&py.get_type::<externs::fs::PyAddPrefix>()),
            remove_prefix: TypeId::new(&py.get_type::<externs::fs::PyRemovePrefix>()),
            create_digest: TypeId::new(create_digest),
            digest_subset: TypeId::new(digest_subset),
            native_download_file: TypeId::new(native_download_file),
            platform: TypeId::new(platform),
            process: TypeId::new(process),
            process_result: TypeId::new(process_result),
            process_config_from_environment: TypeId::new(
                &py.get_type::<externs::process::PyProcessExecutionEnvironment>(),
            ),
            process_result_metadata: TypeId::new(process_result_metadata),
            coroutine: TypeId::new(coroutine),
            session_values: TypeId::new(session_values),
            run_id: TypeId::new(run_id),
            interactive_process: TypeId::new(interactive_process),
            interactive_process_result: TypeId::new(interactive_process_result),
            engine_aware_parameter: TypeId::new(engine_aware_parameter),
            docker_resolve_image_request: TypeId::new(docker_resolve_image_request),
            docker_resolve_image_result: TypeId::new(docker_resolve_image_result),
            parsed_python_deps_result: TypeId::new(parsed_python_deps_result),
            parsed_javascript_deps_result: TypeId::new(parsed_javascript_deps_result),
            parsed_dockerfile_info_result: TypeId::new(parsed_dockerfile_info_result),
            parsed_javascript_deps_candidate_result: TypeId::new(
                parsed_javascript_deps_candidate_result,
            ),
            deps_request: TypeId::new(
                &py.get_type::<externs::dep_inference::PyNativeDependenciesRequest>(),
            ),
        })))
    }
}

#[pyclass]
struct PyScheduler(Scheduler);

#[pyclass]
struct PyStdioDestination(PyThreadLocals);

/// Represents configuration related to process execution strategies.
///
/// The data stored by PyExecutionStrategyOptions originally was passed directly into
/// scheduler_create but has been broken out separately because the large number of options
/// became unwieldy.
#[pyclass]
struct PyExecutionStrategyOptions(ExecutionStrategyOptions);

#[pymethods]
impl PyExecutionStrategyOptions {
    #[new]
    fn __new__(
        local_parallelism: usize,
        remote_parallelism: usize,
        use_sandboxer: bool,
        local_cache: bool,
        local_enable_nailgun: bool,
        remote_cache_read: bool,
        remote_cache_write: bool,
        child_default_memory: usize,
        child_max_memory: usize,
        graceful_shutdown_timeout: usize,
    ) -> Self {
        Self(ExecutionStrategyOptions {
            local_parallelism,
            remote_parallelism,
            use_sandboxer,
            local_cache,
            local_enable_nailgun,
            remote_cache_read,
            remote_cache_write,
            child_default_memory,
            child_max_memory,
            graceful_shutdown_timeout: Duration::from_secs(
                graceful_shutdown_timeout.try_into().unwrap(),
            ),
        })
    }
}

/// Represents configuration related to remote execution and caching.
#[pyclass]
struct PyRemotingOptions(RemotingOptions);

#[pymethods]
impl PyRemotingOptions {
    #[new]
    #[pyo3(signature = (
        *,
        provider,
        execution_enable,
        store_headers,
        store_chunk_bytes,
        store_rpc_retries,
        store_rpc_concurrency,
        store_rpc_timeout_millis,
        store_batch_api_size_limit,
        store_batch_load_enabled,
        cache_warnings_behavior,
        cache_content_behavior,
        cache_rpc_concurrency,
        cache_rpc_timeout_millis,
        execution_headers,
        execution_overall_deadline_secs,
        execution_rpc_concurrency,
        store_address,
        execution_address,
        execution_process_cache_namespace,
        instance_name,
        root_ca_certs_path,
        client_certs_path,
        client_key_path,
        append_only_caches_base_path
    ))]
    fn __new__(
        provider: String,
        execution_enable: bool,
        store_headers: BTreeMap<String, String>,
        store_chunk_bytes: usize,
        store_rpc_retries: usize,
        store_rpc_concurrency: usize,
        store_rpc_timeout_millis: u64,
        store_batch_api_size_limit: usize,
        store_batch_load_enabled: bool,
        cache_warnings_behavior: String,
        cache_content_behavior: String,
        cache_rpc_concurrency: usize,
        cache_rpc_timeout_millis: u64,
        execution_headers: BTreeMap<String, String>,
        execution_overall_deadline_secs: u64,
        execution_rpc_concurrency: usize,
        store_address: Option<String>,
        execution_address: Option<String>,
        execution_process_cache_namespace: Option<String>,
        instance_name: Option<String>,
        root_ca_certs_path: Option<PathBuf>,
        client_certs_path: Option<PathBuf>,
        client_key_path: Option<PathBuf>,
        append_only_caches_base_path: Option<String>,
    ) -> Self {
        Self(RemotingOptions {
            provider: RemoteProvider::from_str(&provider).unwrap(),
            execution_enable,
            store_address,
            execution_address,
            execution_process_cache_namespace,
            instance_name,
            root_ca_certs_path,
            client_certs_path,
            client_key_path,
            store_headers,
            store_chunk_bytes,
            store_rpc_retries,
            store_rpc_concurrency,
            store_rpc_timeout: Duration::from_millis(store_rpc_timeout_millis),
            store_batch_api_size_limit,
            store_batch_load_enabled,
            cache_warnings_behavior: RemoteCacheWarningsBehavior::from_str(
                &cache_warnings_behavior,
            )
            .unwrap(),
            cache_content_behavior: CacheContentBehavior::from_str(&cache_content_behavior)
                .unwrap(),
            cache_rpc_concurrency,
            cache_rpc_timeout: Duration::from_millis(cache_rpc_timeout_millis),
            execution_headers,
            execution_overall_deadline: Duration::from_secs(execution_overall_deadline_secs),
            execution_rpc_concurrency,
            append_only_caches_base_path,
        })
    }
}

#[pyclass]
struct PyLocalStoreOptions(LocalStoreOptions);

#[pymethods]
impl PyLocalStoreOptions {
    #[new]
    fn __new__(
        store_dir: PathBuf,
        process_cache_max_size_bytes: usize,
        files_max_size_bytes: usize,
        directories_max_size_bytes: usize,
        lease_time_millis: u64,
        shard_count: u8,
    ) -> PyO3Result<Self> {
        if shard_count.count_ones() != 1 {
            return Err(PyValueError::new_err(format!(
                "The local store shard count must be a power of two: got {shard_count}"
            )));
        }
        Ok(Self(LocalStoreOptions {
            store_dir,
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
        scheduler: &Bound<'_, PyScheduler>,
        dynamic_ui: bool,
        ui_use_prodash: bool,
        max_workunit_level: u64,
        build_id: String,
        session_values: Py<PyAny>,
        cancellation_latch: &Bound<'_, PySessionCancellationLatch>,
        py: Python,
    ) -> PyO3Result<Self> {
        let core = scheduler.borrow().0.core.clone();
        let cancellation_latch = cancellation_latch.borrow().0.clone();
        let py_level: PythonLogLevel = max_workunit_level
            .try_into()
            .map_err(|e| PyException::new_err(format!("{e}")))?;
        // NB: Session creation interacts with the Graph, which must not be accessed while the GIL is
        // held.
        let session = py
            .detach(|| {
                Session::new(
                    core,
                    dynamic_ui,
                    ui_use_prodash,
                    py_level.into(),
                    build_id,
                    session_values,
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

    #[getter]
    fn session_values<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        let session_values = self.0.session_values();
        session_values.bind(py).to_owned()
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
    server: SyncMutex<Option<nailgun::Server>>,
    executor: Executor,
}

#[pymethods]
impl PyNailgunServer {
    fn port(&self, py: Python<'_>) -> PyO3Result<u16> {
        let borrowed_server = self.server.lock_py_attached(py);
        let server = borrowed_server.as_ref().ok_or_else(|| {
            PyException::new_err("Cannot get the port of a server that has already shut down.")
        })?;
        Ok(server.port())
    }
}

#[pyclass]
struct PyExecutionRequest(SyncMutex<ExecutionRequest>);

#[pymethods]
impl PyExecutionRequest {
    #[new]
    #[pyo3(signature = (*, poll, poll_delay_in_ms, timeout_in_ms))]
    fn __new__(poll: bool, poll_delay_in_ms: Option<u64>, timeout_in_ms: Option<u64>) -> Self {
        let request = ExecutionRequest {
            poll,
            poll_delay: poll_delay_in_ms.map(Duration::from_millis),
            timeout: timeout_in_ms.map(Duration::from_millis),
            ..ExecutionRequest::default()
        };
        Self(SyncMutex::new(request))
    }
}

#[pyclass]
struct PyResult {
    #[pyo3(get)]
    is_throw: bool,
    #[pyo3(get)]
    result: Py<PyAny>,
    #[pyo3(get)]
    python_traceback: Option<String>,
    #[pyo3(get)]
    engine_traceback: Vec<(String, Option<String>)>,
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
                f @ (Failure::Invalidated | Failure::MissingDigest { .. }) => {
                    let msg = format!("{f}");
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
                engine_traceback: engine_traceback
                    .into_iter()
                    .map(|ff| (ff.name, ff.desc))
                    .collect(),
            }
        }
    }
}

#[pyclass]
struct PyThreadLocals(Arc<stdio::Destination>, Option<WorkunitStoreHandle>);

impl PyThreadLocals {
    fn get() -> Self {
        let stdio_dest = stdio::get_destination();
        let workunit_store_handle = workunit_store::get_workunit_store_handle();
        Self(stdio_dest, workunit_store_handle)
    }
}

#[pymethods]
impl PyThreadLocals {
    #[classmethod]
    fn get_for_current_thread(_cls: &Bound<'_, PyType>) -> Self {
        Self::get()
    }

    fn set_for_current_thread(&self) {
        stdio::set_thread_destination(self.0.clone());
        workunit_store::set_thread_workunit_store_handle(self.1.clone());
    }
}

#[pyfunction]
fn nailgun_server_create(
    py_executor: &externs::scheduler::PyExecutor,
    port: u16,
    runner: Py<PyAny>,
) -> PyO3Result<PyNailgunServer> {
    let server_future = {
        let executor = py_executor.0.clone();
        nailgun::Server::new(executor, port, move |exe: nailgun::RawFdExecution| {
            Python::attach(|py| {
                let args_tuple = match PyTuple::new(py, exe.cmd.args) {
                    Ok(t) => t,
                    Err(e) => {
                        error!("PyTuple construction failure: {e:?}");
                        return nailgun::ExitCode(1);
                    }
                };

                let result = runner.bind(py).call1((
                    exe.cmd.command,
                    args_tuple,
                    exe.cmd.env.into_iter().collect::<HashMap<String, String>>(),
                    exe.cmd.working_dir,
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
        })
    };

    let server = py_executor
        .0
        .block_on(server_future)
        .map_err(PyException::new_err)?;
    Ok(PyNailgunServer {
        server: SyncMutex::new(Some(server)),
        executor: py_executor.0.clone(),
    })
}

#[pyfunction]
fn nailgun_server_await_shutdown(
    py: Python<'_>,
    nailgun_server_ptr: &Bound<'_, PyNailgunServer>,
) -> PyO3Result<()> {
    if let Some(server) = nailgun_server_ptr
        .borrow()
        .server
        .lock_py_attached(py)
        .take()
    {
        let executor = nailgun_server_ptr.borrow().executor.clone();
        py.detach(|| executor.block_on(server.shutdown()))
            .map_err(PyException::new_err)
    } else {
        Ok(())
    }
}

#[pyfunction]
fn strongly_connected_components(
    py: Python,
    adjacency_lists: Vec<(Py<PyAny>, Vec<Py<PyAny>>)>,
) -> PyO3Result<Vec<Vec<Py<PyAny>>>> {
    let mut graph: DiGraph<Key, (), u32> = Graph::new();
    let mut node_ids: HashMap<Key, _> = HashMap::new();

    for (node, adjacency_list) in adjacency_lists {
        let node_key = Key::from_value(node.into())?;
        let node_id = *node_ids
            .entry(node_key.clone())
            .or_insert_with(|| graph.add_node(node_key));
        for dependency in adjacency_list {
            let dependency_key = Key::from_value(dependency.into())?;
            let dependency_id = node_ids
                .entry(dependency_key.clone())
                .or_insert_with(|| graph.add_node(dependency_key));
            graph.add_edge(node_id, *dependency_id, ());
        }
    }

    Ok(petgraph::algo::tarjan_scc(&graph)
        .into_iter()
        .map(|component| {
            component
                .into_iter()
                .map(|node_id| graph[node_id].to_value().consume_into_py_object(py))
                .collect::<Vec<_>>()
        })
        .collect())
}

/// Return the number of zero bits prefixed on an (undefined, but well balanced) hash of the given
/// string.
///
/// This is mostly in rust because of the convenience of the `leading_zeros` builtin method.
#[pyfunction]
fn hash_prefix_zero_bits(item: &str) -> u32 {
    let mut hasher = FnvHasher::default();
    hasher.write(item.as_bytes());
    hasher.finish().leading_zeros()
}

///
/// Given a set of Tasks and type information, creates a Scheduler.
///
/// The given Tasks struct will be cloned, so no additional mutation of the reference will
/// affect the created Scheduler.
///
#[pyfunction]
#[pyo3(signature = (
    py_executor,
    py_tasks,
    types_ptr,
    build_root,
    pants_workdir,
    local_execution_root_dir,
    named_caches_dir,
    ignore_patterns,
    use_gitignore,
    watch_filesystem,
    remoting_options,
    local_store_options,
    exec_strategy_opts,
    ca_certs_path
))]
fn scheduler_create<'py>(
    py: Python<'py>,
    py_executor: &Bound<'py, externs::scheduler::PyExecutor>,
    py_tasks: &Bound<'py, PyTasks>,
    types_ptr: &Bound<'py, PyTypes>,
    build_root: PathBuf,
    pants_workdir: PathBuf,
    local_execution_root_dir: PathBuf,
    named_caches_dir: PathBuf,
    ignore_patterns: Vec<String>,
    use_gitignore: bool,
    watch_filesystem: bool,
    remoting_options: &Bound<'py, PyRemotingOptions>,
    local_store_options: &Bound<'py, PyLocalStoreOptions>,
    exec_strategy_opts: &Bound<'py, PyExecutionStrategyOptions>,
    ca_certs_path: Option<PathBuf>,
) -> PyO3Result<PyScheduler> {
    match fs::increase_limits() {
        Ok(msg) => debug!("{msg}"),
        Err(e) => warn!("{e}"),
    }
    let types = types_ptr
        .borrow()
        .0
        .lock_py_attached(py)
        .take()
        .ok_or_else(|| PyException::new_err("An instance of PyTypes may only be used once."))?;
    let tasks = py_tasks
        .borrow()
        .0
        .lock_py_attached(py)
        .replace(Tasks::new())
        .unwrap();

    // NOTE: Enter the Tokio runtime so that libraries like Tonic (for gRPC) are able to
    // use `tokio::spawn` since Python does not setup Tokio for the main thread. This also
    // ensures that the correct executor is used by those libraries.
    let py_executor = py_executor.borrow();
    let core = py_executor
        .0
        .enter(|| {
            py_executor.0.block_on(async {
                Core::new(
                    py_executor.0.clone(),
                    tasks,
                    types,
                    build_root,
                    pants_workdir,
                    ignore_patterns,
                    use_gitignore,
                    watch_filesystem,
                    local_execution_root_dir,
                    named_caches_dir,
                    ca_certs_path,
                    local_store_options.borrow().0.clone(),
                    remoting_options.borrow().0.clone(),
                    exec_strategy_opts.borrow().0.clone(),
                )
                .await
            })
        })
        .map_err(PyValueError::new_err)?;
    Ok(PyScheduler(Scheduler::new(core)))
}

async fn workunit_to_py_value(
    workunit_store: &WorkunitStore,
    workunit: Workunit,
    core: &Arc<Core>,
) -> PyO3Result<Value> {
    let metadata = workunit.metadata.ok_or_else(|| {
        PyException::new_err(format!(
            // TODO: It would be better for this to be typesafe, but it isn't currently worth it to
            // split the Workunit struct.
            "Workunit for {} was disabled. Please file an issue at \
            [https://github.com/pantsbuild/pants/issues/new].",
            workunit.span_id
        ))
    })?;
    let has_parent_ids = !workunit.parent_ids.is_empty();
    let mut dict_entries = Python::attach(|py| -> PyO3Result<Vec<(Value, Value)>> {
        let mut dict_entries = vec![
            (
                externs::store_utf8(py, "name"),
                externs::store_utf8(py, workunit.name),
            ),
            (
                externs::store_utf8(py, "span_id"),
                externs::store_utf8(py, &format!("{}", workunit.span_id)),
            ),
            (
                externs::store_utf8(py, "level"),
                externs::store_utf8(py, &workunit.level.to_string()),
            ),
        ];

        let parent_ids = workunit
            .parent_ids
            .into_iter()
            .map(|parent_id| externs::store_utf8(py, &parent_id.to_string()))
            .collect::<Vec<_>>();

        if has_parent_ids {
            // TODO: Remove the single-valued `parent_id` field around version 2.16.0.dev0.
            dict_entries.push((externs::store_utf8(py, "parent_id"), parent_ids[0].clone()));
        }
        dict_entries.push((
            externs::store_utf8(py, "parent_ids"),
            externs::store_tuple(py, parent_ids)?,
        ));

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

        if let Some(desc) = &metadata.desc.as_ref() {
            dict_entries.push((
                externs::store_utf8(py, "description"),
                externs::store_utf8(py, desc),
            ));
        }
        Ok(dict_entries)
    })?;

    let mut artifact_entries = Vec::new();

    for (artifact_name, digest) in metadata.artifacts.iter() {
        let store = core.store();
        let py_val = match digest {
            ArtifactOutput::FileDigest(digest) => Python::attach(|py| {
                crate::nodes::Snapshot::store_file_digest(py, *digest).map_err(PyException::new_err)
            })?,
            ArtifactOutput::Snapshot(digest_handle) => {
                let digest = (**digest_handle)
                    .as_any()
                    .downcast_ref::<DirectoryDigest>()
                    .ok_or_else(|| {
                        PyException::new_err(format!(
                            "Failed to convert {digest_handle:?} to a DirectoryDigest."
                        ))
                    })?;
                let snapshot = store::Snapshot::from_digest(store, digest.clone())
                    .await
                    .map_err(possible_store_missing_digest)?;

                Python::attach(|py| {
                    crate::nodes::Snapshot::store_snapshot(py, snapshot)
                        .map_err(PyException::new_err)
                })?
            }
        };

        Python::attach(|py| {
            artifact_entries.push((externs::store_utf8(py, artifact_name.as_str()), py_val))
        })
    }

    Python::attach(|py| {
        let mut user_metadata_entries = Vec::with_capacity(metadata.user_metadata.len());
        for (user_metadata_key, user_metadata_item) in metadata.user_metadata.iter() {
            let value = match user_metadata_item {
                UserMetadataItem::String(v) => v.into_pyobject(py)?.to_owned().into_any().unbind(),
                UserMetadataItem::Int(n) => n.into_pyobject(py)?.to_owned().into_any().unbind(),
                UserMetadataItem::PyValue(py_val_handle) => (**py_val_handle)
                    .as_any()
                    .downcast_ref::<Value>()
                    .ok_or_else(|| {
                        PyException::new_err(format!(
                            "Failed to convert {py_val_handle:?} to a Value."
                        ))
                    })?
                    .into_pyobject(py)?
                    .into_any()
                    .unbind(),
            };
            user_metadata_entries.push((
                externs::store_utf8(py, user_metadata_key.as_str()),
                Value::new(value),
            ));
        }

        dict_entries.push((
            externs::store_utf8(py, "metadata"),
            externs::store_dict(py, user_metadata_entries)?,
        ));

        if let Some(stdout_digest) = metadata.stdout {
            artifact_entries.push((
                externs::store_utf8(py, "stdout_digest"),
                crate::nodes::Snapshot::store_file_digest(py, stdout_digest)
                    .map_err(PyException::new_err)?,
            ));
        }

        if let Some(stderr_digest) = metadata.stderr {
            artifact_entries.push((
                externs::store_utf8(py, "stderr_digest"),
                crate::nodes::Snapshot::store_file_digest(py, stderr_digest)
                    .map_err(PyException::new_err)?,
            ));
        }

        if let Some(command_digest) = metadata.remote_command {
            artifact_entries.push((
                externs::store_utf8(py, "remote_command_digest"),
                crate::nodes::Snapshot::store_file_digest(py, command_digest)
                    .map_err(PyException::new_err)?,
            ));
        }

        if let Some(action_digest) = metadata.remote_action {
            artifact_entries.push((
                externs::store_utf8(py, "remote_action_digest"),
                crate::nodes::Snapshot::store_file_digest(py, action_digest)
                    .map_err(PyException::new_err)?,
            ));
        }

        if let Some(local_command_digest) = metadata.local_command {
            artifact_entries.push((
                externs::store_utf8(py, "local_command_digest"),
                crate::nodes::Snapshot::store_file_digest(py, local_command_digest)
                    .map_err(PyException::new_err)?,
            ));
        }

        if let Some(local_action_digest) = metadata.local_action {
            artifact_entries.push((
                externs::store_utf8(py, "local_action_digest"),
                crate::nodes::Snapshot::store_file_digest(py, local_action_digest)
                    .map_err(PyException::new_err)?,
            ));
        }

        dict_entries.push((
            externs::store_utf8(py, "artifacts"),
            externs::store_dict(py, artifact_entries)?,
        ));

        // TODO: Temporarily attaching the global counters to the "root" workunit. Callers should
        // switch to consuming `StreamingWorkunitContext.get_metrics`.
        // Remove this deprecation after 2.14.0.dev0.
        if !has_parent_ids {
            let mut metrics = workunit_store.get_metrics();

            metrics.insert("DEPRECATED_ConsumeGlobalCountersInstead", 0);
            let counters_entries: Vec<_> = metrics
                .into_iter()
                .map(|(counter_name, counter_value)| {
                    (
                        externs::store_utf8(py, counter_name),
                        externs::store_u64(py, counter_value),
                    )
                })
                .collect();

            dict_entries.push((
                externs::store_utf8(py, "counters"),
                externs::store_dict(py, counters_entries)?,
            ));
        }
        externs::store_dict(py, dict_entries)
    })
}

async fn workunits_to_py_tuple_value(
    py: Python<'_>,
    workunit_store: &WorkunitStore,
    workunits: Vec<Workunit>,
    core: &Arc<Core>,
) -> PyO3Result<Value> {
    let mut workunit_values = Vec::new();
    for workunit in workunits {
        let py_value = workunit_to_py_value(workunit_store, workunit, core).await?;
        workunit_values.push(py_value);
    }

    externs::store_tuple(py, workunit_values)
}

#[pyfunction]
fn session_poll_workunits(
    py_scheduler: Py<PyAny>,
    py_session: Py<PyAny>,
    max_log_verbosity_level: u64,
) -> PyO3Result<Py<PyAny>> {
    // TODO: Black magic. Py<PyAny> is not marked UnwindSafe, and contains an UnsafeCell. Since PyO3
    // only allows us to receive `pyfunction` arguments as `Py<PyAny>` (or references under a held
    // GIL), we cannot do what it does to use `catch_unwind` which would be interacting with
    // `catch_unwind` while the object is still a raw pointer, and unchecked.
    //
    // Instead, we wrap the call, and assert that it is safe. It really might not be though. So this
    // code should only live long enough to shake out the current issue, and an upstream issue with
    // PyO3 will be the long term solution.
    //
    // see https://github.com/PyO3/pyo3/issues/2102 for more info.
    let py_scheduler = std::panic::AssertUnwindSafe(py_scheduler);
    let py_session = std::panic::AssertUnwindSafe(py_session);
    std::panic::catch_unwind(|| {
        let (core, session, py_level) = {
            Python::attach(|py| -> PyO3Result<_> {
                let py_scheduler = py_scheduler.extract::<PyRef<PyScheduler>>(py)?;
                let py_session = py_session.extract::<PyRef<PySession>>(py)?;
                let py_level: PythonLogLevel = max_log_verbosity_level
                    .try_into()
                    .map_err(|e| PyException::new_err(format!("{e}")))?;
                Ok((py_scheduler.0.core.clone(), py_session.0.clone(), py_level))
            })?
        };
        core.executor.enter(|| {
            let workunit_store = session.workunit_store();
            let (started, completed) = workunit_store.latest_workunits(py_level.into());

            Python::attach(|py| -> PyO3Result<_> {
                let started_val = core.executor.block_on(workunits_to_py_tuple_value(
                    py,
                    &workunit_store,
                    started,
                    &core,
                ))?;
                let completed_val = core.executor.block_on(workunits_to_py_tuple_value(
                    py,
                    &workunit_store,
                    completed,
                    &core,
                ))?;
                Ok(externs::store_tuple(py, vec![started_val, completed_val])?.into())
            })
        })
    })
    .unwrap_or_else(|e| {
        log::warn!("Panic in `session_poll_workunits`: {e:?}");
        std::panic::resume_unwind(e);
    })
}

#[pyfunction]
fn session_run_interactive_process(
    py: Python,
    py_session: &Bound<'_, PySession>,
    interactive_process: Py<PyAny>,
    process_config_from_environment: &Bound<'_, PyProcessExecutionEnvironment>,
) -> PyO3Result<Py<PyAny>> {
    let core = py_session.borrow().0.core().clone();
    let session = &py_session.borrow().0;
    let context = core.graph.context(SessionCore::new(session.clone()));

    let interactive_process: Value = interactive_process.into();
    let process_config = Value::from(process_config_from_environment.as_any());

    py.detach(|| {
        core.executor.clone().block_on(nodes::task_context(
            context.clone(),
            true,
            &Arc::new(std::sync::atomic::AtomicBool::new(true)),
            intrinsics::interactive_process_inner(&context, interactive_process, process_config),
        ))
    })
    .map(|v| v.into())
    .map_err(|e| PyException::new_err(e.to_string()))
}

#[pyfunction]
fn scheduler_metrics<'py>(
    py: Python<'py>,
    py_scheduler: &Bound<'py, PyScheduler>,
    py_session: &Bound<'py, PySession>,
) -> HashMap<String, i64> {
    let core = py_session.borrow().0.core().clone();
    let scheduler = &py_scheduler.borrow().0;
    let session = &py_session.borrow().0;

    core.executor.enter(|| {
        py.detach(|| {
            let result = scheduler.metrics(session);
            result.into_iter().map(|(k, v)| (k.to_owned(), v)).collect()
        })
    })
}

#[allow(clippy::type_complexity)]
#[pyfunction]
fn scheduler_live_items<'py>(
    py: Python<'py>,
    py_scheduler: &Bound<'py, PyScheduler>,
    py_session: &Bound<'_, PySession>,
) -> (Vec<Py<PyAny>>, HashMap<&'static str, (usize, usize)>) {
    let core = py_scheduler.borrow().0.core.clone();
    let scheduler = &py_scheduler.borrow().0;
    let session = &py_session.borrow().0;

    let (items, sizes) = core
        .executor
        .enter(|| py.detach(|| scheduler.live_items(session)));
    let py_items = items
        .into_iter()
        .map(|value| value.bind(py).clone().unbind())
        .collect();
    (py_items, sizes)
}

#[pyfunction]
fn scheduler_shutdown(py: Python, py_scheduler: &Bound<'_, PyScheduler>, timeout_secs: u64) {
    let core = py_scheduler.borrow().0.core.clone();
    core.executor.enter(|| {
        py.detach(|| {
            core.executor
                .block_on(core.shutdown(Duration::from_secs(timeout_secs)));
        })
    })
}

#[pyfunction]
fn scheduler_execute<'py>(
    py: Python<'py>,
    py_scheduler: &Bound<'py, PyScheduler>,
    py_session: &Bound<'py, PySession>,
    py_execution_request: &Bound<'py, PyExecutionRequest>,
) -> PyO3Result<Vec<PyResult>> {
    let scheduler = &py_scheduler.borrow().0;
    let session = &py_session.borrow().0;
    let execution_request_cell_ref = py_execution_request.borrow();
    let execution_request = execution_request_cell_ref.0.lock_py_attached(py);

    scheduler.core.executor.enter(|| {
        // TODO: A parent_id should be an explicit argument.
        session.workunit_store().init_thread_state(None);

        Ok(py
            .detach(|| {
                scheduler
                    .execute(&execution_request, session)
                    .map_err(|e| match e {
                        ExecutionTermination::KeyboardInterrupt => PyKeyboardInterrupt::new_err(()),
                        ExecutionTermination::PollTimeout => PollTimeout::new_err(()),
                        ExecutionTermination::Fatal(msg) => PyException::new_err(msg),
                    })
            })?
            .into_iter()
            .map(|root_result| py_result_from_root(py, root_result))
            .collect())
    })
}

#[pyfunction]
fn execution_add_root_select<'py>(
    py: Python<'py>,
    py_scheduler: &Bound<'py, PyScheduler>,
    py_execution_request: &Bound<'py, PyExecutionRequest>,
    param_vals: Vec<Py<PyAny>>,
    product: &Bound<'py, PyType>,
) -> PyO3Result<()> {
    let scheduler = &py_scheduler.borrow().0;
    let execution_request_cell_ref = py_execution_request.borrow();
    let mut execution_request = execution_request_cell_ref.0.lock_py_attached(py);

    scheduler.core.executor.enter(|| {
        let product = TypeId::new(product);
        let keys = param_vals
            .into_iter()
            .map(|p| Key::from_value(p.into()))
            .collect::<Result<Vec<_>, _>>()?;
        Params::new(keys)
            .and_then(|params| scheduler.add_root_select(&mut execution_request, params, product))
            .map_err(PyException::new_err)
    })
}

#[pyfunction]
fn tasks_task_begin<'py>(
    py: Python<'py>,
    py_tasks: &Bound<'py, PyTasks>,
    func: Py<PyAny>,
    output_type: &Bound<'py, PyType>,
    arg_types: Vec<(String, Bound<'py, PyType>)>,
    masked_types: Vec<Bound<'py, PyType>>,
    side_effecting: bool,
    engine_aware_return_type: bool,
    cacheable: bool,
    name: String,
    desc: String,
    level: u64,
) -> PyO3Result<()> {
    let py_level: PythonLogLevel = level
        .try_into()
        .map_err(|e| PyException::new_err(format!("{e}")))?;
    let func = Function(Key::from_value(func.into())?);
    let output_type = TypeId::new(output_type);
    let arg_types = arg_types
        .into_iter()
        .map(|(name, typ)| (name, TypeId::new(&typ.as_borrowed())))
        .collect();
    let masked_types = masked_types.into_iter().map(|t| TypeId::new(&t)).collect();
    py_tasks
        .borrow_mut()
        .0
        .lock_py_attached(py)
        .as_mut()
        .unwrap()
        .task_begin(
            func,
            output_type,
            side_effecting,
            engine_aware_return_type,
            arg_types,
            masked_types,
            cacheable,
            name,
            if desc.is_empty() { None } else { Some(desc) },
            py_level.into(),
        );
    Ok(())
}

#[pyfunction]
fn tasks_task_end(py: Python<'_>, py_tasks: &Bound<'_, PyTasks>) {
    py_tasks
        .borrow_mut()
        .0
        .lock_py_attached(py)
        .as_mut()
        .unwrap()
        .task_end();
}

#[pyfunction]
fn tasks_add_call<'py>(
    py: Python<'py>,
    py_tasks: &Bound<'py, PyTasks>,
    output: &Bound<'py, PyType>,
    inputs: Vec<Bound<'py, PyType>>,
    rule_id: String,
    explicit_args_arity: u16,
    vtable_entries: Option<Vec<(Bound<'py, PyType>, String)>>,
    in_scope_types: Option<Vec<Bound<'py, PyType>>>,
) {
    let output = TypeId::new(output);
    let inputs = inputs.into_iter().map(|t| TypeId::new(&t)).collect();
    let in_scope_types =
        in_scope_types.map(|ist| ist.into_iter().map(|t| TypeId::new(&t)).collect());
    py_tasks
        .borrow_mut()
        .0
        .lock_py_attached(py)
        .as_mut()
        .unwrap()
        .add_call(
            output,
            inputs,
            RuleId::from_string(rule_id),
            explicit_args_arity,
            vtable_entries.map(|vte| {
                vte.into_iter()
                    .map(|(k, v)| (TypeId::new(&k), RuleId::from_string(v)))
                    .collect()
            }),
            in_scope_types,
        );
}

#[pyfunction]
fn tasks_add_query<'py>(
    py: Python<'py>,
    py_tasks: &Bound<'py, PyTasks>,
    output_type: &Bound<'py, PyType>,
    input_types: Vec<Bound<'py, PyType>>,
) {
    let product = TypeId::new(output_type);
    let params = input_types.into_iter().map(|t| TypeId::new(&t)).collect();
    py_tasks
        .borrow_mut()
        .0
        .lock_py_attached(py)
        .as_mut()
        .unwrap()
        .query_add(product, params);
}

#[pyfunction]
fn graph_invalidate_paths(
    py: Python,
    py_scheduler: &Bound<'_, PyScheduler>,
    paths: HashSet<PathBuf>,
) -> u64 {
    let scheduler = &py_scheduler.borrow().0;
    scheduler
        .core
        .executor
        .enter(|| py.detach(|| scheduler.invalidate_paths(&paths) as u64))
}

#[pyfunction]
fn graph_invalidate_all_paths(py: Python, py_scheduler: &Bound<'_, PyScheduler>) -> u64 {
    let scheduler = &py_scheduler.borrow().0;
    scheduler
        .core
        .executor
        .enter(|| py.detach(|| scheduler.invalidate_all_paths() as u64))
}

#[pyfunction]
fn graph_invalidate_all(py: Python, py_scheduler: &Bound<'_, PyScheduler>) {
    let scheduler = &py_scheduler.borrow().0;
    scheduler
        .core
        .executor
        .enter(|| py.detach(|| scheduler.invalidate_all()))
}

#[pyfunction]
fn check_invalidation_watcher_liveness(py_scheduler: &Bound<'_, PyScheduler>) -> PyO3Result<()> {
    let scheduler = &py_scheduler.borrow().0;
    scheduler
        .core
        .executor
        .enter(|| scheduler.is_valid().map_err(PyException::new_err))
}

#[pyfunction]
fn graph_len(py: Python, py_scheduler: &Bound<'_, PyScheduler>) -> u64 {
    let core = &py_scheduler.borrow().0.core;
    core.executor
        .enter(|| py.detach(|| core.graph.len() as u64))
}

#[pyfunction]
fn graph_visualize(
    py: Python<'_>,
    py_scheduler: &Bound<'_, PyScheduler>,
    py_session: &Bound<'_, PySession>,
    path: PathBuf,
) -> PyO3Result<()> {
    let scheduler = &py_scheduler.borrow().0;
    let session = &py_session.borrow().0;
    scheduler.core.executor.enter(|| {
        py.detach(|| scheduler.visualize(session, path.as_path()))
            .map_err(|e| {
                PyException::new_err(format!(
                    "Failed to visualize to {}: {:?}",
                    path.display(),
                    e
                ))
            })
    })
}

#[pyfunction]
fn session_new_run_id(py_session: &Bound<'_, PySession>) {
    py_session.borrow().0.new_run_id();
}

#[pyfunction]
fn session_get_metrics(
    py: Python<'_>,
    py_session: &Bound<'_, PySession>,
) -> HashMap<&'static str, u64> {
    let session = &py_session.borrow().0;
    py.detach(|| session.workunit_store().get_metrics())
}

#[pyfunction]
fn session_get_observation_histograms<'py>(
    py: Python<'py>,
    py_scheduler: &Bound<'py, PyScheduler>,
    py_session: &Bound<'py, PySession>,
) -> PyO3Result<Bound<'py, PyDict>> {
    // Encoding version to return to callers. This should be bumped when the encoded histograms
    // are encoded in a backwards-incompatible manner.
    const OBSERVATIONS_VERSION: u64 = 0;

    let session = &py_session.borrow().0;
    py_scheduler.borrow().0.core.executor.enter(|| {
        let observations = py.detach(|| {
            session
                .workunit_store()
                .encode_observations()
                .map_err(PyException::new_err)
        })?;

        let encoded_observations = PyDict::new(py);
        for (metric, encoded_histogram) in &observations {
            encoded_observations.set_item(metric, PyBytes::new(py, &encoded_histogram[..]))?;
        }

        let result = PyDict::new(py);
        result.set_item("version", OBSERVATIONS_VERSION)?;
        result.set_item("histograms", encoded_observations)?;
        Ok(result)
    })
}

#[pyfunction]
fn session_record_test_observation(
    py_scheduler: &Bound<'_, PyScheduler>,
    py_session: &Bound<'_, PySession>,
    value: u64,
) {
    let session = &py_session.borrow().0;
    py_scheduler.borrow().0.core.executor.enter(|| {
        session
            .workunit_store()
            .record_observation(ObservationMetric::TestObservation, value);
    })
}

#[pyfunction]
fn session_isolated_shallow_clone(
    py_session: &Bound<'_, PySession>,
    build_id: String,
) -> PyO3Result<PySession> {
    let session_clone = py_session
        .borrow()
        .0
        .isolated_shallow_clone(build_id)
        .map_err(PyException::new_err)?;
    Ok(PySession(session_clone))
}

#[pyfunction]
fn session_wait_for_tail_tasks(
    py: Python<'_>,
    py_scheduler: &Bound<'_, PyScheduler>,
    py_session: &Bound<'_, PySession>,
    timeout: f64,
) -> PyO3Result<()> {
    let core = &py_scheduler.borrow().0.core;
    let timeout = Duration::from_secs_f64(timeout);
    let session = &py_session.borrow().0;

    core.executor.enter(|| {
        py.detach(|| {
            core.executor.block_on(session.tail_tasks().wait(timeout));
        })
    });
    Ok(())
}

#[pyfunction]
fn validate_reachability(py_scheduler: &Bound<'_, PyScheduler>) -> PyO3Result<()> {
    let core = &py_scheduler.borrow().0.core;
    core.executor.enter(|| {
        core.rule_graph
            .validate_reachability()
            .map_err(PyException::new_err)
    })
}

#[pyfunction]
fn rule_graph_consumed_types<'py>(
    py: Python<'py>,
    py_scheduler: &Bound<'py, PyScheduler>,
    param_types: Vec<Bound<'py, PyType>>,
    product_type: &Bound<'_, PyType>,
) -> PyO3Result<Vec<Bound<'py, PyType>>> {
    let core = &py_scheduler.borrow().0.core;
    core.executor.enter(|| {
        let param_types = param_types
            .into_iter()
            .map(|t| TypeId::new(&t))
            .collect::<Vec<_>>();
        let subgraph = core
            .rule_graph
            .subgraph(param_types, TypeId::new(product_type))
            .map_err(PyValueError::new_err)?;

        Ok(subgraph
            .consumed_types()
            .into_iter()
            .map(|type_id| type_id.as_py_type(py))
            .collect())
    })
}

#[pyfunction]
fn rule_graph_visualize(py_scheduler: &Bound<'_, PyScheduler>, path: PathBuf) -> PyO3Result<()> {
    let core = &py_scheduler.borrow().0.core;
    core.executor.enter(|| {
        // TODO(#7117): we want to represent union types in the graph visualizer somehow!!!
        write_to_file(path.as_path(), &core.rule_graph).map_err(|e| {
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
    py_scheduler: &Bound<'_, PyScheduler>,
    param_types: Vec<Bound<'_, PyType>>,
    product_type: &Bound<'_, PyType>,
    path: PathBuf,
) -> PyO3Result<()> {
    let scheduler = &py_scheduler.borrow().0;

    scheduler.core.executor.enter(|| {
        let param_types = param_types
            .into_iter()
            .map(|t| TypeId::new(&t.as_borrowed()))
            .collect::<Vec<_>>();
        let product_type = TypeId::new(product_type);

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
        Some(ref s) => format!("panic at '{s}'"),
        None => format!("Non-string panic payload at {payload:p}"),
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

        error!("{panic_str}");

        let panic_file_bug_str = "Please set RUST_BACKTRACE=1, re-run, and then file a bug at https://github.com/pantsbuild/pants/issues.";
        error!("{panic_file_bug_str}");
    }));
}

#[pyfunction]
fn garbage_collect_store(
    py: Python,
    py_scheduler: &Bound<'_, PyScheduler>,
    target_size_bytes: usize,
) -> PyO3Result<()> {
    let core = py_scheduler.borrow().0.core.clone();
    core.clone().executor.enter(|| {
        py.detach(|| {
            core.executor.block_on(
                core.store()
                    .garbage_collect(target_size_bytes, store::ShrinkBehavior::Fast),
            )
        })
        .map_err(PyException::new_err)
    })
}

#[pyfunction]
fn lease_files_in_graph(
    py: Python,
    py_scheduler: &Bound<'_, PyScheduler>,
    py_session: &Bound<'_, PySession>,
) -> PyO3Result<()> {
    let core = py_scheduler.borrow().0.core.clone();
    let scheduler = &py_scheduler.borrow().0;
    let session = &py_session.borrow().0;

    core.executor.enter(|| {
        py.detach(|| {
            let digests = scheduler.all_digests(session);
            core.executor
                .block_on(core.store().lease_all_recursively(digests.iter()))
        })
        .map_err(possible_store_missing_digest)
    })
}

#[pyfunction]
fn capture_snapshots(
    py: Python<'_>,
    py_scheduler: &Bound<'_, PyScheduler>,
    py_session: &Bound<'_, PySession>,
    path_globs_and_root_tuple_wrapper: &Bound<'_, PyAny>,
) -> PyO3Result<Vec<externs::fs::PySnapshot>> {
    let core = &py_scheduler.borrow().0.core;
    let session = &py_session.borrow().0;
    core.executor.enter(|| {
        // TODO: A parent_id should be an explicit argument.
        session.workunit_store().init_thread_state(None);

        let values = externs::collect_iterable(path_globs_and_root_tuple_wrapper).unwrap();
        let path_globs_and_roots = values
            .into_iter()
            .map(|value| {
                let root: PathBuf = externs::getattr(&value, "root")?;
                let path_globs = {
                    let path_globs_py_value =
                        externs::getattr::<Bound<'_, PyAny>>(&value, "path_globs")?;
                    nodes::Snapshot::lift_prepared_path_globs(&path_globs_py_value)
                };
                let digest_hint = {
                    let maybe_digest: Bound<'_, PyAny> = externs::getattr(&value, "digest_hint")?;
                    if maybe_digest.is_none() {
                        None
                    } else {
                        Some(nodes::lift_directory_digest(&maybe_digest)?)
                    }
                };
                path_globs.map(|path_globs| (path_globs, root, digest_hint))
            })
            .collect::<Result<Vec<_>, _>>()
            .map_err(PyValueError::new_err)?;

        py.detach(|| {
            let snapshot_futures = path_globs_and_roots
                .into_iter()
                .map(|(path_globs, root, digest_hint)| {
                    store::Snapshot::capture_snapshot_from_arbitrary_root(
                        core.store(),
                        core.executor.clone(),
                        root,
                        path_globs,
                        digest_hint,
                    )
                })
                .collect::<Vec<_>>();

            Ok(core
                .executor
                .block_on(future::try_join_all(snapshot_futures))
                .map_err(PyException::new_err)?
                .into_iter()
                .map(externs::fs::PySnapshot)
                .collect())
        })
    })
}

#[pyfunction]
fn ensure_remote_has_recursive(
    py: Python<'_>,
    py_scheduler: &Bound<'_, PyScheduler>,
    py_digests: &Bound<'_, PyList>,
) -> PyO3Result<()> {
    let core = &py_scheduler.borrow().0.core;
    core.executor.enter(|| {
        // NB: Supports either a PyFileDigest or PyDigest as input.
        let digests: Vec<Digest> = py_digests
            .iter()
            .map(|value| {
                crate::nodes::lift_directory_digest(&value)
                    .map(|dd| dd.as_digest())
                    .or_else(|_| crate::nodes::lift_file_digest(&value))
            })
            .collect::<Result<Vec<Digest>, _>>()
            .map_err(PyException::new_err)?;

        py.detach(|| {
            core.executor
                .block_on(core.store().ensure_remote_has_recursive(digests))
        })
        .map_err(possible_store_missing_digest)?;
        Ok(())
    })
}

#[pyfunction]
fn ensure_directory_digest_persisted(
    py: Python<'_>,
    py_scheduler: &Bound<'_, PyScheduler>,
    py_digest: &Bound<'_, PyAny>,
) -> PyO3Result<()> {
    let core = &py_scheduler.borrow().0.core;
    core.executor.enter(|| {
        let digest =
            crate::nodes::lift_directory_digest(py_digest).map_err(PyException::new_err)?;

        py.detach(|| {
            core.executor
                .block_on(core.store().ensure_directory_digest_persisted(digest))
        })
        .map_err(possible_store_missing_digest)?;
        Ok(())
    })
}

#[pyfunction]
fn single_file_digests_to_bytes<'py>(
    py: Python<'py>,
    py_scheduler: &Bound<'py, PyScheduler>,
    py_file_digests: Vec<PyFileDigest>,
) -> PyO3Result<Bound<'py, PyList>> {
    let core = &py_scheduler.borrow().0.core;
    core.executor.enter(|| {
        let digest_futures = py_file_digests.into_iter().map(|py_file_digest| {
            let store = core.store();
            async move {
                store
                    .load_file_bytes_with(py_file_digest.0, |bytes| {
                        Python::attach(|py| externs::store_bytes(py, bytes))
                    })
                    .await
            }
        });

        let bytes_values: Vec<Py<PyAny>> = py
            .detach(|| core.executor.block_on(future::try_join_all(digest_futures)))
            .map(|values| values.into_iter().map(|val| val.into()).collect())
            .map_err(possible_store_missing_digest)?;

        let output_list = PyList::new(py, &bytes_values)?;
        Ok(output_list)
    })
}

fn ensure_path_doesnt_exist(path: &Path) -> io::Result<()> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
        // Always fall through to remove_dir_all unless the path definitely doesn't exist, because
        // std::io::ErrorKind::IsADirectory is unstable https://github.com/rust-lang/rust/issues/86442
        //
        // NB. we don't need to check this returning NotFound because remove_file will identify that
        // above (except if there's a concurrent removal, which is out of scope)
        Err(_) => std::fs::remove_dir_all(path),
    }
}

static GLOBAL_WORKSPACE_WRITE_LOCK: LazyLock<Mutex<()>> = LazyLock::new(|| Mutex::new(()));

#[pyfunction]
fn write_digest(
    py: Python<'_>,
    py_scheduler: &Bound<'_, PyScheduler>,
    py_session: &Bound<'_, PySession>,
    digest: &Bound<'_, PyAny>,
    path_prefix: String,
    clear_paths: Vec<String>,
) -> PyO3Result<()> {
    let scheduler = &py_scheduler.borrow().0;
    let session = &py_session.borrow().0;
    let store = scheduler.core.store();

    scheduler.core.executor.enter(|| {
        // TODO: A parent_id should be an explicit argument.
        session.workunit_store().init_thread_state(None);

        let lifted_digest = nodes::lift_directory_digest(digest).map_err(PyValueError::new_err)?;

        // Python will have already validated that path_prefix is a relative path.
        let path_prefix = Path::new(&path_prefix);
        let mut destination = PathBuf::new();
        destination.push(&scheduler.core.build_root);
        destination.push(path_prefix);

        for subpath in &clear_paths {
            let resolved = destination.join(subpath);
            ensure_path_doesnt_exist(&resolved).map_err(|e| {
                PyIOError::new_err(format!(
                    "Failed to clear {} when writing digest: {e}",
                    resolved.display()
                ))
            })?;
        }

        block_in_place_and_wait(py, || async move {
            {
                // Although Workspace.write_digest() is typically used in @goal_rules, and so is not
                // invoked concurrently, there are a handful of cases where we might need to write
                // deeper inside the rule graph, and therefore may run into concurrency issues.
                // One example is the bsp server, which may attempt to write build byproducts into
                // the workspace for the IDE to consume, and in some cases may try and write the
                // same files concurrently. Therefore we force all workspace writes to run in
                // a critical section.
                //
                // Side note: When using Workspace.write_digest() outside a @goal_rule, you must
                // take care to ensure that it always runs, and is not short-circuited by rule
                // memoization, so that you can rely on the side effect always taking effect.
                // This is typically done via an @_uncacheable_rule.
                // This lock makes Workspace safe to use outside a @goal_rule, but does nothing to
                // guarantee that it will run when you expect it to.
                let _locked = GLOBAL_WORKSPACE_WRITE_LOCK.lock().await;
                store
                    .materialize_directory(
                        destination.clone(),
                        &scheduler.core.build_root,
                        lifted_digest.clone(),
                        true, // Force everything we write to be mutable
                        &BTreeSet::new(),
                        fs::Permissions::Writable,
                    )
                    .await?;
            } // _locked released here.

            // Invalidate all the paths we've changed within `path_prefix`: both the paths we cleared and
            // the files we've just written to.
            let snapshot = store::Snapshot::from_digest(store, lifted_digest).await?;
            let written_paths = snapshot.tree.leaf_paths();
            let written_paths = written_paths.iter().map(|p| p as &Path);

            let cleared_paths = clear_paths.iter().map(Path::new);

            let changed_paths = written_paths
                .chain(cleared_paths)
                .map(|p| path_prefix.join(p))
                .collect();

            scheduler.invalidate_paths(&changed_paths);

            Ok(())
        })
        .map_err(possible_store_missing_digest)
    })
}

#[pyfunction]
fn stdio_initialize(
    level: u64,
    show_rust_3rdparty_logs: bool,
    show_target: bool,
    log_levels_by_target: HashMap<String, u64>,
    literal_filters: Vec<String>,
    regex_filters: Vec<String>,
    log_file_path: PathBuf,
) -> PyO3Result<(
    externs::stdio::PyStdioRead,
    externs::stdio::PyStdioWrite,
    externs::stdio::PyStdioWrite,
)> {
    let regex_filters = regex_filters
    .iter()
    .map(|re| {
      Regex::new(re).map_err(|e| {
        PyException::new_err(
          format!(
            "Failed to parse warning filter. Please check the global option `--ignore-warnings`.\n\n{e}",
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
        log_file_path,
    )
    .map_err(|s| PyException::new_err(format!("Could not initialize logging: {s}")))?;

    Ok((
        externs::stdio::PyStdioRead,
        externs::stdio::PyStdioWrite { is_stdout: true },
        externs::stdio::PyStdioWrite { is_stdout: false },
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

// TODO: Deprecated, but without easy access to the decorator. Use
// `PyThreadLocals::get_for_current_thread` instead. Remove in Pants 2.17.0.dev0.
#[pyfunction]
fn stdio_thread_get_destination() -> PyStdioDestination {
    PyStdioDestination(PyThreadLocals::get())
}

// TODO: Deprecated, but without easy access to the decorator. Use
// `PyThreadLocals::set_for_current_thread` instead. Remove in Pants 2.17.0.dev0.
#[pyfunction]
fn stdio_thread_set_destination(stdio_destination: &Bound<'_, PyStdioDestination>) {
    stdio_destination.borrow().0.set_for_current_thread();
}

// TODO: Needs to be thread-local / associated with the Console.
#[pyfunction]
#[pyo3(signature = (log_path))]
fn set_per_run_log_path(py: Python, log_path: Option<PathBuf>) {
    py.detach(|| {
        PANTS_LOGGER.set_per_run_logs(log_path);
    })
}

#[pyfunction]
fn write_log(py: Python, msg: String, level: u64, target: String) {
    py.detach(|| {
        Logger::log_from_python(&msg, level, &target).expect("Error logging message");
    })
}

#[pyfunction]
fn task_side_effected() -> PyO3Result<()> {
    nodes::task_side_effected().map_err(PyException::new_err)
}

#[pyfunction]
fn teardown_dynamic_ui<'py>(
    py: Python<'py>,
    py_scheduler: &Bound<'py, PyScheduler>,
    py_session: &Bound<'py, PySession>,
) {
    let core = &py_scheduler.borrow().0.core;
    let session = &py_session.borrow().0;
    core.executor.enter(|| {
        let _ = block_in_place_and_wait(py, || {
            session.maybe_display_teardown().unit_error().boxed_local()
        });
    })
}

#[pyfunction]
fn flush_log(py: Python) {
    py.detach(|| {
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
    py.detach(|| {
        let future = f();
        tokio::task::block_in_place(|| futures::executor::block_on(future))
    })
}
