// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
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
  clippy::used_underscore_binding
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
// We only use unsafe pointer dereferences in our no_mangle exposed API, but it is nicer to list
// just the one minor call as unsafe, than to mark the whole function as unsafe which may hide
// other unsafeness.
#![allow(clippy::not_unsafe_ptr_arg_deref)]
// This crate is a wrapper around the engine crate which exposes a C interface which we can access
// from Python using cffi.
//
// The engine crate contains some C interop which we use, notably externs which are functions and
// types from Python which we can read from our Rust. This particular wrapper crate is just for how
// we expose ourselves back to Python.
#![type_length_limit = "2066838"]

mod cffi_externs;

use engine::externs::*;
use engine::{
  externs, nodes, Core, ExecutionRequest, ExecutionTermination, Failure, Function, Handle,
  Intrinsics, Key, Params, Rule, Scheduler, Session, Tasks, TypeId, Types, Value,
};
use futures::future::{self as future03, TryFutureExt};
use futures01::{future, Future};
use hashing::{Digest, EMPTY_DIGEST};
use log::{error, warn, Log};
use logging::logger::LOGGER;
use logging::{Destination, Logger};
use rule_graph::RuleGraph;
use std::any::Any;
use std::borrow::Borrow;
use std::ffi::CStr;
use std::fs::File;
use std::io;
use std::mem;
use std::os::raw;
use std::os::unix::ffi::OsStrExt;
use std::panic;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tempfile::TempDir;
use tokio;
use workunit_store::{Workunit, WorkunitState};

#[cfg(test)]
mod tests;

///
/// A clone of ExecutionTermination with a "no error" case in order to handle the fact that
/// cbindgen cannot handle Options.
///
#[repr(u8)]
pub enum RawExecutionTermination {
  KeyboardInterrupt,
  Timeout,
  NoError,
}

impl From<ExecutionTermination> for RawExecutionTermination {
  fn from(et: ExecutionTermination) -> Self {
    match et {
      ExecutionTermination::KeyboardInterrupt => RawExecutionTermination::KeyboardInterrupt,
      ExecutionTermination::Timeout => RawExecutionTermination::Timeout,
    }
  }
}

// TODO: Consider renaming and making generic for collections of PyResults.
#[repr(C)]
pub struct RawNodes {
  err: RawExecutionTermination,
  nodes_ptr: *const PyResult,
  nodes_len: u64,
  nodes: Vec<PyResult>,
}

impl RawNodes {
  fn create(node_states: Vec<Result<Value, Failure>>) -> Box<RawNodes> {
    let nodes = node_states.into_iter().map(PyResult::from).collect();
    let mut raw_nodes = Box::new(RawNodes {
      err: RawExecutionTermination::NoError,
      nodes_ptr: Vec::new().as_ptr(),
      nodes_len: 0,
      nodes: nodes,
    });
    // Creates a pointer into the struct itself, which is not possible to do in safe rust.
    raw_nodes.nodes_ptr = raw_nodes.nodes.as_ptr();
    raw_nodes.nodes_len = raw_nodes.nodes.len() as u64;
    raw_nodes
  }

  fn create_for_error(err: ExecutionTermination) -> Box<RawNodes> {
    Box::new(RawNodes {
      err: err.into(),
      nodes_ptr: Vec::new().as_ptr(),
      nodes_len: 0,
      nodes: Vec::new(),
    })
  }
}

#[no_mangle]
pub extern "C" fn externs_set(
  context: *const ExternContext,
  log_level: u8,
  none: Handle,
  call: CallExtern,
  generator_send: GeneratorSendExtern,
  get_type_for: GetTypeForExtern,
  get_handle_from_type_id: GetHandleFromTypeIdExtern,
  is_union: IsUnionExtern,
  identify: IdentifyExtern,
  equals: EqualsExtern,
  clone_val: CloneValExtern,
  drop_handles: DropHandlesExtern,
  type_to_str: TypeToStrExtern,
  val_to_bytes: ValToBytesExtern,
  val_to_str: ValToStrExtern,
  store_tuple: StoreTupleExtern,
  store_set: StoreTupleExtern,
  store_dict: StoreTupleExtern,
  store_bytes: StoreBytesExtern,
  store_utf8: StoreUtf8Extern,
  store_u64: StoreU64Extern,
  store_i64: StoreI64Extern,
  store_f64: StoreF64Extern,
  store_bool: StoreBoolExtern,
  project_ignoring_type: ProjectIgnoringTypeExtern,
  project_multi: ProjectMultiExtern,
  val_to_bool: ValToBoolExtern,
  create_exception: CreateExceptionExtern,
) {
  externs::set_externs(Externs {
    context,
    log_level,
    none,
    call,
    generator_send,
    get_type_for,
    get_handle_from_type_id,
    is_union,
    identify,
    equals,
    clone_val,
    drop_handles,
    type_to_str,
    val_to_bytes,
    val_to_str,
    store_tuple,
    store_set,
    store_dict,
    store_bytes,
    store_utf8,
    store_u64,
    store_i64,
    store_f64,
    store_bool,
    project_ignoring_type,
    project_multi,
    val_to_bool,
    create_exception,
  });
}

#[no_mangle]
pub extern "C" fn key_for(value: Handle) -> Key {
  externs::key_for(value.into())
}

#[no_mangle]
pub extern "C" fn val_for(key: Key) -> Handle {
  externs::val_for(&key).into()
}

// Like PyResult, but for values that aren't Python values.
// throw_handle will be set iff is_throw, otherwise accessing it will likely segfault.
// raw_pointer will be set iff !is_throw, otherwise accessing it will likely segfault.
#[repr(C)]
pub struct RawResult {
  is_throw: bool,
  throw_handle: Handle,
  raw_pointer: *const raw::c_void,
}

impl RawResult {
  fn new<T>(res: Result<T, String>) -> RawResult {
    match res {
      Ok(t) => RawResult {
        is_throw: false,
        raw_pointer: Box::into_raw(Box::new(t)) as *const raw::c_void,
        throw_handle: Handle(std::ptr::null()),
      },
      Err(err) => RawResult {
        is_throw: true,
        throw_handle: externs::create_exception(&err).into(),
        raw_pointer: std::ptr::null(),
      },
    }
  }
}

#[no_mangle]
pub extern "C" fn nailgun_server_create(
  scheduler_ptr: *mut Scheduler,
  port: u16,
  runner: Function,
) -> RawResult {
  with_scheduler(scheduler_ptr, |scheduler| {
    let runner = externs::val_for(&runner.0);
    let executor = scheduler.core.executor.clone();
    let server_future =
      nailgun::Server::new(executor, port, move |exe: nailgun::RawFdExecution| {
        let command = externs::store_utf8(&exe.cmd.command);
        let args = externs::store_tuple(&{
          exe
            .cmd
            .args
            .iter()
            .map(|s| externs::store_utf8(s))
            .collect::<Vec<_>>()
        });
        let env = externs::store_dict(&{
          exe
            .cmd
            .env
            .iter()
            .map(|(k, v)| (externs::store_utf8(k), externs::store_utf8(v)))
            .collect::<Vec<_>>()
        });
        let working_dir = externs::store_bytes(exe.cmd.working_dir.as_os_str().as_bytes());
        let stdin_fd = externs::store_i64(exe.stdin_fd.into());
        let stdout_fd = externs::store_i64(exe.stdout_fd.into());
        let stderr_fd = externs::store_i64(exe.stderr_fd.into());
        let runner_args = vec![
          command,
          args,
          env,
          working_dir,
          stdin_fd,
          stdout_fd,
          stderr_fd,
        ];
        match externs::call(&runner, &runner_args) {
          Ok(exit_code_val) => {
            // TODO: We don't currently expose a "project_i32", but it will not be necessary with
            // https://github.com/pantsbuild/pants/pull/9593.
            nailgun::ExitCode(externs::val_to_str(&exit_code_val).parse().unwrap())
          }
          Err(e) => {
            error!("Uncaught exception in nailgun handler: {:#?}", e);
            nailgun::ExitCode(1)
          }
        }
      });
    RawResult::new(scheduler.core.executor.block_on(server_future))
  })
}

#[no_mangle]
pub extern "C" fn nailgun_server_await_bound(
  scheduler_ptr: *mut Scheduler,
  nailgun_server_ptr: *mut nailgun::Server,
) -> PyResult {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_nailgun_server(nailgun_server_ptr, |nailgun_server| {
      scheduler
        .core
        .executor
        .block_on(nailgun_server.await_bound())
        .map(|port| externs::store_u64(port as u64))
        .into()
    })
  })
}

#[no_mangle]
pub extern "C" fn nailgun_server_destroy(nailgun_server_ptr: *mut nailgun::Server) {
  let server = unsafe { Box::from_raw(nailgun_server_ptr) };
  // NB: We do not wait for the server to have exited.
  server.shutdown();
}

///
/// Given a set of Tasks and type information, creates a Scheduler.
///
/// The given Tasks struct will be cloned, so no additional mutation of the reference will
/// affect the created Scheduler.
///
#[no_mangle]
pub extern "C" fn scheduler_create(
  tasks_ptr: *mut Tasks,
  types: Types,
  build_root_buf: Buffer,
  local_store_dir_buf: Buffer,
  local_execution_root_dir_buf: Buffer,
  ignore_patterns_buf: BufferBuffer,
  use_gitignore: bool,
  root_type_ids: TypeIdBuffer,
  remote_execution: bool,
  remote_store_servers_buf: BufferBuffer,
  remote_execution_server: Buffer,
  remote_execution_process_cache_namespace: Buffer,
  remote_instance_name: Buffer,
  remote_root_ca_certs_path_buffer: Buffer,
  remote_oauth_bearer_token_path_buffer: Buffer,
  remote_store_thread_count: u64,
  remote_store_chunk_bytes: u64,
  remote_store_connection_limit: u64,
  remote_store_chunk_upload_timeout_seconds: u64,
  remote_store_rpc_retries: u64,
  remote_execution_extra_platform_properties_buf: BufferBuffer,
  process_execution_local_parallelism: u64,
  process_execution_remote_parallelism: u64,
  process_execution_cleanup_local_dirs: bool,
  process_execution_speculation_delay: f64,
  process_execution_speculation_strategy_buf: Buffer,
  process_execution_use_local_cache: bool,
  remote_execution_headers_buf: BufferBuffer,
  process_execution_local_enable_nailgun: bool,
) -> RawResult {
  let core_res = make_core(
    tasks_ptr,
    types,
    build_root_buf,
    local_store_dir_buf,
    local_execution_root_dir_buf,
    ignore_patterns_buf,
    use_gitignore,
    root_type_ids,
    remote_execution,
    remote_store_servers_buf,
    remote_execution_server,
    remote_execution_process_cache_namespace,
    remote_instance_name,
    remote_root_ca_certs_path_buffer,
    remote_oauth_bearer_token_path_buffer,
    remote_store_thread_count,
    remote_store_chunk_bytes,
    remote_store_connection_limit,
    remote_store_chunk_upload_timeout_seconds,
    remote_store_rpc_retries,
    remote_execution_extra_platform_properties_buf,
    process_execution_local_parallelism,
    process_execution_remote_parallelism,
    process_execution_cleanup_local_dirs,
    process_execution_speculation_delay,
    process_execution_speculation_strategy_buf,
    process_execution_use_local_cache,
    remote_execution_headers_buf,
    process_execution_local_enable_nailgun,
  );
  RawResult::new(core_res.map(Scheduler::new))
}

fn make_core(
  tasks_ptr: *mut Tasks,
  types: Types,
  build_root_buf: Buffer,
  local_store_dir_buf: Buffer,
  local_execution_root_dir_buf: Buffer,
  ignore_patterns_buf: BufferBuffer,
  use_gitignore: bool,
  root_type_ids: TypeIdBuffer,
  remote_execution: bool,
  remote_store_servers_buf: BufferBuffer,
  remote_execution_server: Buffer,
  remote_execution_process_cache_namespace: Buffer,
  remote_instance_name: Buffer,
  remote_root_ca_certs_path_buffer: Buffer,
  remote_oauth_bearer_token_path_buffer: Buffer,
  remote_store_thread_count: u64,
  remote_store_chunk_bytes: u64,
  remote_store_connection_limit: u64,
  remote_store_chunk_upload_timeout_seconds: u64,
  remote_store_rpc_retries: u64,
  remote_execution_extra_platform_properties_buf: BufferBuffer,
  process_execution_local_parallelism: u64,
  process_execution_remote_parallelism: u64,
  process_execution_cleanup_local_dirs: bool,
  process_execution_speculation_delay: f64,
  process_execution_speculation_strategy_buf: Buffer,
  process_execution_use_local_cache: bool,
  remote_execution_headers_buf: BufferBuffer,
  process_execution_local_enable_nailgun: bool,
) -> Result<Core, String> {
  let root_type_ids = root_type_ids.to_vec();
  let ignore_patterns = ignore_patterns_buf
    .to_strings()
    .map_err(|err| format!("Failed to decode ignore patterns as UTF8: {:?}", err))?;
  let intrinsics = Intrinsics::new(&types);
  #[allow(clippy::redundant_closure)] // I couldn't find an easy way to remove this closure.
  let mut tasks = with_tasks(tasks_ptr, |tasks| tasks.clone());
  tasks.intrinsics_set(&intrinsics);
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  let remote_store_servers_vec = remote_store_servers_buf
    .to_strings()
    .map_err(|err| format!("Failed to decode remote_store_servers: {}", err))?;
  let remote_execution_server_string = remote_execution_server
    .to_string()
    .map_err(|err| format!("remote_execution_server was not valid UTF8: {}", err))?;
  let remote_execution_process_cache_namespace_string = remote_execution_process_cache_namespace
    .to_string()
    .map_err(|err| {
      format!(
        "remote_execution_process_cache_namespace was not valid UTF8: {}",
        err
      )
    })?;
  let remote_instance_name_string = remote_instance_name
    .to_string()
    .map_err(|err| format!("remote_instance_name was not valid UTF8: {}", err))?;
  let remote_execution_extra_platform_properties_list = remote_execution_extra_platform_properties_buf
      .to_strings()
      .map_err(|err| format!("Failed to decode remote_execution_extra_platform_properties: {}", err))?
      .into_iter()
      .map(|s| {
        let mut parts: Vec<_> = s.splitn(2, '=').collect();
        if parts.len() != 2 {
          return Err(format!("Got invalid remote_execution_extra_platform_properties - must be of format key=value but got {}", s));
        }
        let (value, key) = (parts.pop().unwrap().to_owned(), parts.pop().unwrap().to_owned());
        Ok((key, value))
      }).collect::<Result<Vec<_>, _>>()?;
  let remote_root_ca_certs_path = {
    let path = remote_root_ca_certs_path_buffer.to_os_string();
    if path.is_empty() {
      None
    } else {
      Some(PathBuf::from(path))
    }
  };

  let remote_oauth_bearer_token_path = {
    let path = remote_oauth_bearer_token_path_buffer.to_os_string();
    if path.is_empty() {
      None
    } else {
      Some(PathBuf::from(path))
    }
  };

  let process_execution_speculation_strategy = process_execution_speculation_strategy_buf
    .to_string()
    .map_err(|err| {
      format!(
        "process_execution_speculation_strategy was not valid UTF8: {}",
        err
      )
    })?;

  let remote_execution_headers = remote_execution_headers_buf.to_map("remote-execution-headers")?;
  Core::new(
    root_type_ids,
    tasks,
    types,
    intrinsics,
    PathBuf::from(build_root_buf.to_os_string()),
    ignore_patterns,
    use_gitignore,
    PathBuf::from(local_store_dir_buf.to_os_string()),
    PathBuf::from(local_execution_root_dir_buf.to_os_string()),
    remote_execution,
    remote_store_servers_vec,
    if remote_execution_server_string.is_empty() {
      None
    } else {
      Some(remote_execution_server_string)
    },
    if remote_execution_process_cache_namespace_string.is_empty() {
      None
    } else {
      Some(remote_execution_process_cache_namespace_string)
    },
    if remote_instance_name_string.is_empty() {
      None
    } else {
      Some(remote_instance_name_string)
    },
    remote_root_ca_certs_path,
    remote_oauth_bearer_token_path,
    remote_store_thread_count as usize,
    remote_store_chunk_bytes as usize,
    Duration::from_secs(remote_store_chunk_upload_timeout_seconds),
    remote_store_rpc_retries as usize,
    remote_store_connection_limit as usize,
    remote_execution_extra_platform_properties_list,
    process_execution_local_parallelism as usize,
    process_execution_remote_parallelism as usize,
    process_execution_cleanup_local_dirs,
    // convert delay from float to millisecond resolution. use from_secs_f64 when it is
    // off nightly. https://github.com/rust-lang/rust/issues/54361
    Duration::from_millis((process_execution_speculation_delay * 1000.0).round() as u64),
    process_execution_speculation_strategy,
    process_execution_use_local_cache,
    remote_execution_headers,
    process_execution_local_enable_nailgun,
  )
}

fn workunit_to_py_value(workunit: &Workunit) -> Option<Value> {
  use std::time::UNIX_EPOCH;

  let mut dict_entries = vec![
    (
      externs::store_utf8("name"),
      externs::store_utf8(&workunit.name),
    ),
    (
      externs::store_utf8("span_id"),
      externs::store_utf8(&workunit.span_id),
    ),
  ];
  if let Some(parent_id) = &workunit.parent_id {
    dict_entries.push((
      externs::store_utf8("parent_id"),
      externs::store_utf8(parent_id),
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

  Some(externs::store_dict(&dict_entries.as_slice()))
}

fn workunits_to_py_tuple_value<'a>(workunits: impl Iterator<Item = &'a Workunit>) -> Value {
  let workunit_values = workunits
    .flat_map(|workunit: &Workunit| workunit_to_py_value(workunit))
    .collect::<Vec<_>>();
  externs::store_tuple(&workunit_values)
}

#[no_mangle]
pub extern "C" fn poll_session_workunits(
  scheduler_ptr: *mut Scheduler,
  session_ptr: *mut Session,
) -> Handle {
  with_scheduler(scheduler_ptr, |_scheduler| {
    with_session(session_ptr, |session| {
      let value = session
        .workunit_store()
        .with_latest_workunits(|started, completed| {
          let mut started_iter = started.iter();
          let started = workunits_to_py_tuple_value(&mut started_iter);

          let mut completed_iter = completed.iter();
          let completed = workunits_to_py_tuple_value(&mut completed_iter);

          externs::store_tuple(&[started, completed])
        });
      value.into()
    })
  })
}

///
/// Returns a Handle representing a dictionary where key is metric name string and value is
/// metric value int.
///
#[no_mangle]
pub extern "C" fn scheduler_metrics(
  scheduler_ptr: *mut Scheduler,
  session_ptr: *mut Session,
) -> Handle {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      let mut values = scheduler
        .metrics(session)
        .into_iter()
        .map(|(metric, value)| (externs::store_utf8(metric), externs::store_i64(value)))
        .collect::<Vec<_>>();
      if session.should_record_zipkin_spans() {
        let workunits = session.workunit_store().get_workunits();
        let mut iter = workunits.iter();
        let value = workunits_to_py_tuple_value(&mut iter);
        values.push((externs::store_utf8("engine_workunits"), value));
      };
      externs::store_dict(values.as_slice()).into()
    })
  })
}

#[no_mangle]
pub extern "C" fn scheduler_execute(
  scheduler_ptr: *mut Scheduler,
  session_ptr: *mut Session,
  execution_request_ptr: *mut ExecutionRequest,
) -> *const RawNodes {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_execution_request(execution_request_ptr, |execution_request| {
      with_session(session_ptr, |session| {
        // TODO: A parent_id should be an explicit argument.
        session.workunit_store().init_thread_state(None);
        match scheduler.execute(execution_request, session) {
          Ok(raw_results) => Box::into_raw(RawNodes::create(raw_results)),
          Err(e) => Box::into_raw(RawNodes::create_for_error(e)),
        }
      })
    })
  })
}

#[no_mangle]
pub extern "C" fn scheduler_destroy(scheduler_ptr: *mut Scheduler) {
  // convert the raw pointer back to a Box (without `forget`ing it) in order to cause it
  // to be destroyed at the end of this function.
  let _ = unsafe { Box::from_raw(scheduler_ptr) };
}

#[no_mangle]
pub extern "C" fn execution_add_root_select(
  scheduler_ptr: *mut Scheduler,
  execution_request_ptr: *mut ExecutionRequest,
  param_vals: HandleBuffer,
  product: TypeId,
) -> PyResult {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_execution_request(execution_request_ptr, |execution_request| {
      Params::new(param_vals.to_vec().into_iter().map(externs::key_for))
        .and_then(|params| scheduler.add_root_select(execution_request, params, product))
        .into()
    })
  })
}

#[no_mangle]
pub extern "C" fn execution_set_poll(execution_request_ptr: *mut ExecutionRequest, poll: bool) {
  with_execution_request(execution_request_ptr, |execution_request| {
    execution_request.poll = poll;
  })
}

#[no_mangle]
pub extern "C" fn execution_set_poll_delay(
  execution_request_ptr: *mut ExecutionRequest,
  poll_delay_in_ms: u64,
) {
  with_execution_request(execution_request_ptr, |execution_request| {
    execution_request.poll_delay = Some(Duration::from_millis(poll_delay_in_ms));
  })
}

#[no_mangle]
pub extern "C" fn execution_set_timeout(
  execution_request_ptr: *mut ExecutionRequest,
  timeout_in_ms: u64,
) {
  with_execution_request(execution_request_ptr, |execution_request| {
    execution_request.timeout = Some(Duration::from_millis(timeout_in_ms));
  })
}

#[no_mangle]
pub extern "C" fn tasks_create() -> *const Tasks {
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  Box::into_raw(Box::new(Tasks::new()))
}

#[no_mangle]
pub extern "C" fn tasks_task_begin(
  tasks_ptr: *mut Tasks,
  func: Function,
  output_type: TypeId,
  cacheable: bool,
) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.task_begin(func, output_type, cacheable);
  })
}

#[no_mangle]
pub extern "C" fn tasks_add_get(tasks_ptr: *mut Tasks, product: TypeId, subject: TypeId) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.add_get(product, subject);
  })
}

#[no_mangle]
pub extern "C" fn tasks_add_select(tasks_ptr: *mut Tasks, product: TypeId) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.add_select(product);
  })
}

#[no_mangle]
pub extern "C" fn tasks_add_display_info(
  tasks_ptr: *mut Tasks,
  name_ptr: *const raw::c_char,
  desc_ptr: *const raw::c_char,
) {
  let name = unsafe { str_ptr_to_string(name_ptr) };
  let desc = unsafe { str_ptr_to_string(desc_ptr) };
  with_tasks(tasks_ptr, |tasks| {
    tasks.add_display_info(name, desc);
  })
}

#[no_mangle]
pub extern "C" fn tasks_task_end(tasks_ptr: *mut Tasks) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.task_end();
  })
}

#[no_mangle]
pub extern "C" fn tasks_destroy(tasks_ptr: *mut Tasks) {
  let _ = unsafe { Box::from_raw(tasks_ptr) };
}

#[no_mangle]
pub extern "C" fn graph_invalidate(scheduler_ptr: *mut Scheduler, paths_buf: BufferBuffer) -> u64 {
  with_scheduler(scheduler_ptr, |scheduler| {
    let paths = paths_buf
      .to_os_strings()
      .into_iter()
      .map(PathBuf::from)
      .collect();
    scheduler.invalidate(&paths) as u64
  })
}

#[no_mangle]
pub extern "C" fn graph_invalidate_all_paths(scheduler_ptr: *mut Scheduler) -> u64 {
  with_scheduler(scheduler_ptr, |scheduler| {
    scheduler.invalidate_all_paths() as u64
  })
}

#[no_mangle]
pub extern "C" fn check_invalidation_watcher_liveness(scheduler_ptr: *mut Scheduler) -> PyResult {
  with_scheduler(scheduler_ptr, |scheduler| scheduler.is_valid().into())
}

#[no_mangle]
pub extern "C" fn graph_len(scheduler_ptr: *mut Scheduler) -> u64 {
  with_scheduler(scheduler_ptr, |scheduler| scheduler.core.graph.len() as u64)
}

#[no_mangle]
pub extern "C" fn decompress_tarball(
  tar_path: *const raw::c_char,
  output_dir: *const raw::c_char,
) -> PyResult {
  let tar_path_str = PathBuf::from(
    unsafe { CStr::from_ptr(tar_path) }
      .to_string_lossy()
      .into_owned(),
  );
  let output_dir_str = PathBuf::from(
    unsafe { CStr::from_ptr(output_dir) }
      .to_string_lossy()
      .into_owned(),
  );

  tar_api::decompress_tgz(tar_path_str.as_path(), output_dir_str.as_path())
    .map_err(|e| {
      format!(
        "Failed to untar {:?} to {:?}:\n{:?}",
        tar_path_str.as_path(),
        output_dir_str.as_path(),
        e
      )
    })
    .into()
}

#[no_mangle]
pub extern "C" fn graph_visualize(
  scheduler_ptr: *mut Scheduler,
  session_ptr: *mut Session,
  path_ptr: *const raw::c_char,
) -> PyResult {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
      let path = PathBuf::from(path_str);
      scheduler
        .visualize(session, path.as_path())
        .map_err(|e| format!("Failed to visualize to {}: {:?}", path.display(), e))
        .into()
    })
  })
}

#[no_mangle]
pub extern "C" fn nodes_destroy(raw_nodes_ptr: *mut RawNodes) {
  let _ = unsafe { Box::from_raw(raw_nodes_ptr) };
}

#[no_mangle]
pub extern "C" fn session_create(
  scheduler_ptr: *mut Scheduler,
  should_record_zipkin_spans: bool,
  should_render_ui: bool,
  build_id: Buffer,
  should_report_workunits: bool,
) -> *const Session {
  let build_id = build_id
    .to_string()
    .expect("build_id was not a valid UTF-8 string");
  with_scheduler(scheduler_ptr, |scheduler| {
    Box::into_raw(Box::new(Session::new(
      scheduler,
      should_record_zipkin_spans,
      should_render_ui,
      build_id,
      should_report_workunits,
    )))
  })
}

#[no_mangle]
pub extern "C" fn session_new_run_id(session_ptr: *mut Session) {
  with_session(session_ptr, |session| session.new_run_id())
}

#[no_mangle]
pub extern "C" fn session_destroy(ptr: *mut Session) {
  let _ = unsafe { Box::from_raw(ptr) };
}

#[no_mangle]
pub extern "C" fn execution_request_create() -> *const ExecutionRequest {
  Box::into_raw(Box::new(ExecutionRequest::new()))
}

#[no_mangle]
pub extern "C" fn execution_request_destroy(ptr: *mut ExecutionRequest) {
  let _ = unsafe { Box::from_raw(ptr) };
}

#[no_mangle]
pub extern "C" fn validator_run(scheduler_ptr: *mut Scheduler) -> PyResult {
  with_scheduler(scheduler_ptr, |scheduler| {
    scheduler.core.rule_graph.validate().into()
  })
}

#[no_mangle]
pub extern "C" fn rule_graph_visualize(
  scheduler_ptr: *mut Scheduler,
  path_ptr: *const raw::c_char,
) -> PyResult {
  with_scheduler(scheduler_ptr, |scheduler| {
    let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
    let path = PathBuf::from(path_str);

    // TODO(#7117): we want to represent union types in the graph visualizer somehow!!!
    write_to_file(path.as_path(), &scheduler.core.rule_graph)
      .map_err(|e| format!("Failed to visualize to {}: {:?}", path.display(), e))
      .into()
  })
}

#[no_mangle]
pub extern "C" fn rule_subgraph_visualize(
  scheduler_ptr: *mut Scheduler,
  param_types: TypeIdBuffer,
  product_type: TypeId,
  path_ptr: *const raw::c_char,
) -> PyResult {
  with_scheduler(scheduler_ptr, |scheduler| {
    let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
    let path = PathBuf::from(path_str);

    // TODO(#7117): we want to represent union types in the graph visualizer somehow!!!
    match scheduler
      .core
      .rule_graph
      .subgraph(param_types.to_vec(), product_type)
    {
      Ok(subgraph) => write_to_file(path.as_path(), &subgraph)
        .map_err(|e| format!("Failed to visualize to {}: {:?}", path.display(), e))
        .into(),
      e @ Err(_) => e.map(|_| ()).into(),
    }
  })
}

fn generate_panic_string(payload: &(dyn Any + Send)) -> String {
  match payload
    .downcast_ref::<String>()
    .cloned()
    .or_else(|| payload.downcast_ref::<&str>().map(|&s| s.to_string()))
  {
    Some(ref s) => format!("panic at '{}'", s),
    None => format!("Non-string panic payload at {:p}", payload),
  }
}

#[no_mangle]
pub extern "C" fn set_panic_handler() {
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

#[no_mangle]
pub extern "C" fn garbage_collect_store(scheduler_ptr: *mut Scheduler) {
  with_scheduler(scheduler_ptr, |scheduler| {
    match scheduler.core.store().garbage_collect(
      store::DEFAULT_LOCAL_STORE_GC_TARGET_BYTES,
      store::ShrinkBehavior::Fast,
    ) {
      Ok(_) => {}
      Err(err) => error!("{}", err),
    }
  });
}

#[no_mangle]
pub extern "C" fn lease_files_in_graph(scheduler_ptr: *mut Scheduler, session_ptr: *mut Session) {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      let digests = scheduler.all_digests(session);
      match scheduler.core.store().lease_all(digests.iter()) {
        Ok(_) => {}
        Err(err) => error!("{}", &err),
      }
    })
  });
}

#[no_mangle]
pub extern "C" fn match_path_globs(path_globs: Handle, paths_buf: BufferBuffer) -> PyResult {
  let path_globs = match nodes::Snapshot::lift_path_globs(&path_globs.into()) {
    Ok(path_globs) => path_globs,
    Err(msg) => {
      let e: Result<(), _> = Err(msg);
      return e.into();
    }
  };

  let matched = paths_buf
    .to_os_strings()
    .into_iter()
    .any(|s| path_globs.matches(s.as_ref()));
  externs::store_bool(matched).into()
}

#[no_mangle]
pub extern "C" fn capture_snapshots(
  scheduler_ptr: *mut Scheduler,
  session_ptr: *mut Session,
  path_globs_and_root_tuple_wrapper: Handle,
) -> PyResult {
  let values = externs::project_multi(&path_globs_and_root_tuple_wrapper.into(), "dependencies");
  let path_globs_and_roots_result = values
    .iter()
    .map(|value| {
      let root = PathBuf::from(externs::project_str(&value, "root"));
      let path_globs =
        nodes::Snapshot::lift_path_globs(&externs::project_ignoring_type(&value, "path_globs"));
      let digest_hint = {
        let maybe_digest = externs::project_ignoring_type(&value, "digest_hint");
        if maybe_digest == Value::from(externs::none()) {
          None
        } else {
          Some(nodes::lift_digest(&maybe_digest)?)
        }
      };
      path_globs.map(|path_globs| (path_globs, root, digest_hint))
    })
    .collect::<Result<Vec<_>, _>>();

  let path_globs_and_roots = match path_globs_and_roots_result {
    Ok(v) => v,
    Err(err) => {
      let e: Result<Value, String> = Err(err);
      return e.into();
    }
  };

  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      // TODO: A parent_id should be an explicit argument.
      session.workunit_store().init_thread_state(None);
      let core = scheduler.core.clone();
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
            let res: Result<_, String> = Ok(nodes::Snapshot::store_snapshot(&core, &snapshot));
            res
          }
        })
        .collect::<Vec<_>>();
      core.executor.block_on(
        future03::try_join_all(snapshot_futures).map_ok(|values| externs::store_tuple(&values)),
      )
    })
  })
  .into()
}

#[no_mangle]
pub extern "C" fn merge_directories(
  scheduler_ptr: *mut Scheduler,
  session_ptr: *mut Session,
  directories_value: Handle,
) -> PyResult {
  let digests_result: Result<Vec<hashing::Digest>, String> =
    externs::project_multi(&directories_value.into(), "dependencies")
      .iter()
      .map(|v| nodes::lift_digest(v))
      .collect();
  let digests = match digests_result {
    Ok(d) => d,
    Err(err) => {
      let e: Result<Value, String> = Err(err);
      return e.into();
    }
  };

  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      // TODO: A parent_id should be an explicit argument.
      session.workunit_store().init_thread_state(None);
      scheduler
        .core
        .executor
        .block_on(store::Snapshot::merge_directories(
          scheduler.core.store(),
          digests,
        ))
        .map(|dir| nodes::Snapshot::store_directory(&scheduler.core, &dir))
    })
  })
  .into()
}

#[no_mangle]
pub extern "C" fn run_local_interactive_process(
  scheduler_ptr: *mut Scheduler,
  session_ptr: *mut Session,
  request: Handle,
) -> PyResult {
  use std::process;

  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      session.with_console_ui_disabled(|| {
        let types = &scheduler.core.types;
        let construct_interactive_process_result = types.construct_interactive_process_result;

        let value: Value = request.into();

        let argv: Vec<String> = externs::project_multi_strs(&value, "argv");
        if argv.is_empty() {
          return Err("Empty argv list not permitted".to_string());
        }

        let run_in_workspace = externs::project_bool(&value, "run_in_workspace");
        let maybe_tempdir = if run_in_workspace {
          None
        } else {
          Some(TempDir::new().map_err(|err| format!("Error creating tempdir: {}", err))?)
        };

        let input_digest_value = externs::project_ignoring_type(&value, "input_digest");
        let digest: Digest = nodes::lift_digest(&input_digest_value)?;
        if digest != EMPTY_DIGEST {
          if run_in_workspace {
            warn!("Local interactive process should not attempt to materialize files when run in workspace");
          } else {
            let destination = match maybe_tempdir {
              Some(ref dir) => dir.path().to_path_buf(),
              None => unreachable!()
            };

            block_in_place_and_wait(
              scheduler.core.store().materialize_directory(
                destination,
                digest,
              )
            )?;
          }
        }

        let p = Path::new(&argv[0]);
        let program_name = match maybe_tempdir {
          Some(ref tempdir) if p.is_relative() =>  {
            let mut buf = PathBuf::new();
            buf.push(tempdir);
            buf.push(p);
            buf
          },
          _ => p.to_path_buf()
        };

        let mut command = process::Command::new(program_name);
        for arg in argv[1..].iter() {
          command.arg(arg);
        }

        if let Some(ref tempdir) = maybe_tempdir {
          command.current_dir(tempdir.path());
        }

        let env = externs::project_tuple_encoded_map(&value, "env")?;
        for (key, value) in env.iter() {
          command.env(key, value);
        }

        let mut subprocess = command.spawn().map_err(|e| format!("Error executing interactive process: {}", e.to_string()))?;
        let exit_status = subprocess.wait().map_err(|e| e.to_string())?;
        let code = exit_status.code().unwrap_or(-1);

        let output: Result<Value, String> = Ok(externs::unsafe_call(
          &construct_interactive_process_result,
          &[externs::store_i64(i64::from(code))],
        ));
        output
      })
    })
  })
  .into()
}

#[no_mangle]
pub extern "C" fn materialize_directories(
  scheduler_ptr: *mut Scheduler,
  session_ptr: *mut Session,
  directories_digests_and_path_prefixes_value: Handle,
) -> PyResult {
  let values = externs::project_multi(
    &directories_digests_and_path_prefixes_value.into(),
    "dependencies",
  );
  let directories_digests_and_path_prefixes_results: Result<Vec<(Digest, PathBuf)>, String> =
    values
      .iter()
      .map(|value| {
        let dir_digest = nodes::lift_digest(&externs::project_ignoring_type(&value, "digest"));
        let path_prefix = PathBuf::from(externs::project_str(&value, "path_prefix"));
        dir_digest.map(|dir_digest| (dir_digest, path_prefix))
      })
      .collect();

  let digests_and_path_prefixes = match directories_digests_and_path_prefixes_results {
    Ok(d) => d,
    Err(err) => {
      let e: Result<Value, String> = Err(err);
      return e.into();
    }
  };
  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      // TODO: A parent_id should be an explicit argument.
      session.workunit_store().init_thread_state(None);
      let types = &scheduler.core.types;
      let construct_materialize_directories_results =
        types.construct_materialize_directories_results;
      let construct_materialize_directory_result = types.construct_materialize_directory_result;
      block_in_place_and_wait(
        future::join_all(
          digests_and_path_prefixes
            .into_iter()
            .map(|(digest, path_prefix)| {
              // NB: all DirectoryToMaterialize paths are validated in Python to be relative paths.
              // Here, we join them with the build root.
              let mut destination = PathBuf::new();
              destination.push(scheduler.core.build_root.clone());
              destination.push(path_prefix);
              let metadata = scheduler
                .core
                .store()
                .materialize_directory(destination.clone(), digest);
              metadata.map(|m| (destination, m))
            })
            .collect::<Vec<_>>(),
        )
        .map(move |metadata_list| {
          let entries: Vec<Value> = metadata_list
            .iter()
            .map(
              |(output_dir, metadata): &(PathBuf, store::DirectoryMaterializeMetadata)| {
                let path_list = metadata.to_path_list();
                let path_values: Vec<Value> = path_list
                  .into_iter()
                  .map(|rel_path: String| {
                    let mut path = PathBuf::new();
                    path.push(output_dir);
                    path.push(rel_path);
                    externs::store_utf8(&path.to_string_lossy())
                  })
                  .collect();

                externs::unsafe_call(
                  &construct_materialize_directory_result,
                  &[externs::store_tuple(&path_values)],
                )
              },
            )
            .collect();

          let output: Value = externs::unsafe_call(
            &construct_materialize_directories_results,
            &[externs::store_tuple(&entries)],
          );
          output
        }),
      )
    })
  })
  .into()
}

// This is called before externs are set up, so we cannot return a PyResult
#[no_mangle]
pub extern "C" fn init_logging(level: u64, show_rust_3rdparty_logs: bool) {
  Logger::init(level, show_rust_3rdparty_logs);
}

#[no_mangle]
pub extern "C" fn setup_pantsd_logger(log_file_ptr: *const raw::c_char, level: u64) -> PyResult {
  logging::set_thread_destination(Destination::Pantsd);

  let path_str = unsafe { CStr::from_ptr(log_file_ptr).to_string_lossy().into_owned() };
  let path = PathBuf::from(path_str);
  LOGGER
    .set_pantsd_logger(path, level)
    .map(i64::from)
    .map(externs::store_i64)
    .into()
}

// Might be called before externs are set, therefore can't return a PyResult
#[no_mangle]
pub extern "C" fn setup_stderr_logger(level: u64) {
  logging::set_thread_destination(Destination::Stderr);
  LOGGER
    .set_stderr_logger(level)
    .expect("Error setting up STDERR logger");
}

// Might be called before externs are set, therefore can't return a PyResult
#[no_mangle]
pub extern "C" fn write_log(msg: *const raw::c_char, level: u64, target: *const raw::c_char) {
  let message_str = unsafe { CStr::from_ptr(msg).to_string_lossy() };
  let target_str = unsafe { CStr::from_ptr(target).to_string_lossy() };
  Logger::log_from_python(message_str.borrow(), level, target_str.borrow())
    .expect("Error logging message");
}

#[no_mangle]
pub extern "C" fn write_stdout(session_ptr: *mut Session, msg: *const raw::c_char) {
  with_session(session_ptr, |session| {
    let message_str = unsafe { CStr::from_ptr(msg).to_string_lossy() };
    session.write_stdout(&message_str);
  });
}

#[no_mangle]
pub extern "C" fn write_stderr(session_ptr: *mut Session, msg: *const raw::c_char) {
  with_session(session_ptr, |session| {
    let message_str = unsafe { CStr::from_ptr(msg).to_string_lossy() };
    session.write_stderr(&message_str);
  });
}

#[no_mangle]
pub extern "C" fn flush_log() {
  LOGGER.flush();
}

#[no_mangle]
pub extern "C" fn override_thread_logging_destination(destination: Destination) {
  logging::set_thread_destination(destination);
}

fn write_to_file(path: &Path, graph: &RuleGraph<Rule>) -> io::Result<()> {
  let file = File::create(path)?;
  let mut f = io::BufWriter::new(file);
  graph.visualize(&mut f)
}

unsafe fn str_ptr_to_string(ptr: *const raw::c_char) -> String {
  CStr::from_ptr(ptr).to_string_lossy().into_owned()
}

///
/// Calling `wait()` in the context of a @goal_rule blocks a thread that is owned by the tokio
/// runtime. To do that safely, we need to relinquish it.
///   see https://github.com/pantsbuild/pants/issues/9476
///
/// TODO: The alternative to blocking the runtime would be to have the Python code `await` special
/// methods for things like `materialize_directories` and etc.
///
fn block_in_place_and_wait<T, E>(f: impl Future<Item = T, Error = E>) -> Result<T, E> {
  tokio::task::block_in_place(|| f.wait())
}

///
/// Scheduler, Session, and nailgun::Server are intended to be shared between threads, and so their
/// context methods provide immutable references. The remaining types are not intended to be shared
/// between threads, so mutable access is provided.
///
fn with_scheduler<F, T>(scheduler_ptr: *mut Scheduler, f: F) -> T
where
  F: FnOnce(&Scheduler) -> T,
{
  let scheduler = unsafe { Box::from_raw(scheduler_ptr) };
  let t = scheduler.core.runtime.enter(|| f(&scheduler));
  mem::forget(scheduler);
  t
}

///
/// See `with_scheduler`.
///
fn with_session<F, T>(session_ptr: *mut Session, f: F) -> T
where
  F: FnOnce(&Session) -> T,
{
  let session = unsafe { Box::from_raw(session_ptr) };
  let t = f(&session);
  mem::forget(session);
  t
}

///
/// See `with_scheduler`.
///
fn with_nailgun_server<F, T>(nailgun_server_ptr: *mut nailgun::Server, f: F) -> T
where
  F: FnOnce(&nailgun::Server) -> T,
{
  let nailgun_server = unsafe { Box::from_raw(nailgun_server_ptr) };
  let t = f(&nailgun_server);
  mem::forget(nailgun_server);
  t
}

///
/// See `with_scheduler`.
///
fn with_execution_request<F, T>(execution_request_ptr: *mut ExecutionRequest, f: F) -> T
where
  F: FnOnce(&mut ExecutionRequest) -> T,
{
  let mut execution_request = unsafe { Box::from_raw(execution_request_ptr) };
  let t = f(&mut execution_request);
  mem::forget(execution_request);
  t
}

///
/// See `with_scheduler`.
///
fn with_tasks<F, T>(tasks_ptr: *mut Tasks, f: F) -> T
where
  F: FnOnce(&mut Tasks) -> T,
{
  let mut tasks = unsafe { Box::from_raw(tasks_ptr) };
  let t = f(&mut tasks);
  mem::forget(tasks);
  t
}
