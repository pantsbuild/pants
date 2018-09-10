// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![cfg_attr(
  feature = "cargo-clippy",
  deny(
    clippy, default_trait_access, expl_impl_clone_on_copy, if_not_else, needless_continue,
    single_match_else, unseparated_literal_suffix, used_underscore_binding
  )
)]
// It is often more clear to show that nothing is being moved.
#![cfg_attr(feature = "cargo-clippy", allow(match_ref_pats))]
// Subjective style.
#![cfg_attr(feature = "cargo-clippy", allow(len_without_is_empty, redundant_field_names))]
// Default isn't as big a deal as people seem to think it is.
#![cfg_attr(feature = "cargo-clippy", allow(new_without_default, new_without_default_derive))]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![cfg_attr(feature = "cargo-clippy", allow(mutex_atomic))]
// We only use unsafe pointer derefrences in our no_mangle exposed API, but it is nicer to list
// just the one minor call as unsafe, than to mark the whole function as unsafe which may hide
// other unsafeness.
#![cfg_attr(feature = "cargo-clippy", allow(not_unsafe_ptr_arg_deref))]

pub mod cffi_externs;
mod context;
mod core;
mod externs;
mod handles;
mod interning;
mod nodes;
mod rule_graph;
mod scheduler;
mod selectors;
mod tasks;
mod types;

#[macro_use]
extern crate boxfuture;
#[macro_use]
extern crate enum_primitive;
extern crate fnv;
extern crate fs;
extern crate futures;
extern crate graph;
extern crate hashing;
extern crate itertools;
#[macro_use]
extern crate lazy_static;
#[macro_use]
extern crate log;
extern crate process_execution;
extern crate resettable;
extern crate tokio;

use std::ffi::CStr;
use std::fs::File;
use std::io;
use std::mem;
use std::os::raw;
use std::panic;
use std::path::{Path, PathBuf};
use std::time::Duration;

use context::Core;
use core::{Failure, Function, Key, TypeConstraint, TypeId, Value};
use externs::{
  Buffer, BufferBuffer, CallExtern, CloneValExtern, CreateExceptionExtern, DropHandlesExtern,
  EqualsExtern, EvalExtern, ExternContext, Externs, GeneratorSendExtern, IdentifyExtern, LogExtern,
  ProjectIgnoringTypeExtern, ProjectMultiExtern, PyResult, SatisfiedByExtern,
  SatisfiedByTypeExtern, StoreBytesExtern, StoreI64Extern, StoreTupleExtern, StoreUtf8Extern,
  TypeIdBuffer, TypeToStrExtern, ValToStrExtern,
};
use futures::Future;
use handles::Handle;
use hashing::Digest;
use rule_graph::{GraphMaker, RuleGraph};
use scheduler::{ExecutionRequest, RootResult, Scheduler, Session};
use tasks::Tasks;
use types::Types;

#[repr(C)]
enum RawStateTag {
  Return = 1,
  Throw = 2,
  Invalidated = 3,
}

#[repr(C)]
pub struct RawNode {
  subject: Key,
  product: TypeConstraint,
  // The Handle represents a union tagged with RawStateTag.
  state_tag: u8,
  state_handle: Handle,
}

impl RawNode {
  fn create(subject: &Key, product: &TypeConstraint, state: RootResult) -> RawNode {
    let (state_tag, state_value) = match state {
      Ok(v) => (RawStateTag::Return as u8, v),
      Err(Failure::Throw(exc, _)) => (RawStateTag::Throw as u8, exc),
      Err(Failure::Invalidated) => (
        RawStateTag::Invalidated as u8,
        externs::create_exception("Exhausted retries due to changed files."),
      ),
    };

    RawNode {
      subject: *subject,
      product: *product,
      state_tag: state_tag,
      state_handle: state_value.into(),
    }
  }
}

#[repr(C)]
pub struct RawNodes {
  nodes_ptr: *const RawNode,
  nodes_len: u64,
  nodes: Vec<RawNode>,
}

impl RawNodes {
  fn create(node_states: Vec<(&Key, &TypeConstraint, RootResult)>) -> Box<RawNodes> {
    let nodes = node_states
      .into_iter()
      .map(|(subject, product, state)| RawNode::create(subject, product, state))
      .collect();
    let mut raw_nodes = Box::new(RawNodes {
      nodes_ptr: Vec::new().as_ptr(),
      nodes_len: 0,
      nodes: nodes,
    });
    // Creates a pointer into the struct itself, which is not possible to do in safe rust.
    raw_nodes.nodes_ptr = raw_nodes.nodes.as_ptr();
    raw_nodes.nodes_len = raw_nodes.nodes.len() as u64;
    raw_nodes
  }
}

#[no_mangle]
pub extern "C" fn externs_set(
  context: *const ExternContext,
  log: LogExtern,
  log_level: u8,
  call: CallExtern,
  generator_send: GeneratorSendExtern,
  eval: EvalExtern,
  identify: IdentifyExtern,
  equals: EqualsExtern,
  clone_val: CloneValExtern,
  drop_handles: DropHandlesExtern,
  type_to_str: TypeToStrExtern,
  val_to_str: ValToStrExtern,
  satisfied_by: SatisfiedByExtern,
  satisfied_by_type: SatisfiedByTypeExtern,
  store_tuple: StoreTupleExtern,
  store_bytes: StoreBytesExtern,
  store_utf8: StoreUtf8Extern,
  store_i64: StoreI64Extern,
  project_ignoring_type: ProjectIgnoringTypeExtern,
  project_multi: ProjectMultiExtern,
  create_exception: CreateExceptionExtern,
  py_str_type: TypeId,
) {
  externs::set_externs(Externs {
    context,
    log,
    log_level,
    call,
    generator_send,
    eval,
    identify,
    equals,
    clone_val,
    drop_handles,
    type_to_str,
    val_to_str,
    satisfied_by,
    satisfied_by_type,
    store_tuple,
    store_bytes,
    store_utf8,
    store_i64,
    project_ignoring_type,
    project_multi,
    create_exception,
    py_str_type,
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

///
/// Given a set of Tasks and type information, creates a Scheduler.
///
/// The given Tasks struct will be cloned, so no additional mutation of the reference will
/// affect the created Scheduler.
///
#[no_mangle]
pub extern "C" fn scheduler_create(
  tasks_ptr: *mut Tasks,
  construct_directory_digest: Function,
  construct_snapshot: Function,
  construct_file_content: Function,
  construct_files_content: Function,
  construct_path_stat: Function,
  construct_dir: Function,
  construct_file: Function,
  construct_link: Function,
  construct_process_result: Function,
  type_address: TypeConstraint,
  type_has_products: TypeConstraint,
  type_has_variants: TypeConstraint,
  type_path_globs: TypeConstraint,
  type_directory_digest: TypeConstraint,
  type_snapshot: TypeConstraint,
  type_files_content: TypeConstraint,
  type_dir: TypeConstraint,
  type_file: TypeConstraint,
  type_link: TypeConstraint,
  type_process_request: TypeConstraint,
  type_process_result: TypeConstraint,
  type_generator: TypeConstraint,
  type_string: TypeId,
  type_bytes: TypeId,
  build_root_buf: Buffer,
  work_dir_buf: Buffer,
  ignore_patterns_buf: BufferBuffer,
  root_type_ids: TypeIdBuffer,
  remote_store_server: Buffer,
  remote_execution_server: Buffer,
  remote_store_thread_count: u64,
  remote_store_chunk_bytes: u64,
  remote_store_chunk_upload_timeout_seconds: u64,
  process_execution_parallelism: u64,
  process_execution_cleanup_local_dirs: bool,
) -> *const Scheduler {
  let root_type_ids = root_type_ids.to_vec();
  let ignore_patterns = ignore_patterns_buf
    .to_strings()
    .unwrap_or_else(|e| panic!("Failed to decode ignore patterns as UTF8: {:?}", e));
  let types = Types {
    construct_directory_digest: construct_directory_digest,
    construct_snapshot: construct_snapshot,
    construct_file_content: construct_file_content,
    construct_files_content: construct_files_content,
    construct_path_stat: construct_path_stat,
    construct_dir: construct_dir,
    construct_file: construct_file,
    construct_link: construct_link,
    construct_process_result: construct_process_result,
    address: type_address,
    has_products: type_has_products,
    has_variants: type_has_variants,
    path_globs: type_path_globs,
    directory_digest: type_directory_digest,
    snapshot: type_snapshot,
    files_content: type_files_content,
    dir: type_dir,
    file: type_file,
    link: type_link,
    process_request: type_process_request,
    process_result: type_process_result,
    generator: type_generator,
    string: type_string,
    bytes: type_bytes,
  };
  let mut tasks = with_tasks(tasks_ptr, |tasks| tasks.clone());
  tasks.intrinsics_set(&types);
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  let remote_store_server_string = remote_store_server
    .to_string()
    .expect("remote_store_server was not valid UTF8");
  let remote_execution_server_string = remote_execution_server
    .to_string()
    .expect("remote_execution_server was not valid UTF8");
  Box::into_raw(Box::new(Scheduler::new(Core::new(
    root_type_ids.clone(),
    tasks,
    types,
    build_root_buf.to_os_string().as_ref(),
    &ignore_patterns,
    PathBuf::from(work_dir_buf.to_os_string()),
    if remote_store_server_string.is_empty() {
      None
    } else {
      Some(remote_store_server_string)
    },
    if remote_execution_server_string.is_empty() {
      None
    } else {
      Some(remote_execution_server_string)
    },
    remote_store_thread_count as usize,
    remote_store_chunk_bytes as usize,
    Duration::from_secs(remote_store_chunk_upload_timeout_seconds),
    process_execution_parallelism as usize,
    process_execution_cleanup_local_dirs as bool,
  ))))
}

///
/// Returns a Handle representing a tuple of tuples of metric name string and metric value int.
///
#[no_mangle]
pub extern "C" fn scheduler_metrics(
  scheduler_ptr: *mut Scheduler,
  session_ptr: *mut Session,
) -> Handle {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_session(session_ptr, |session| {
      let values = scheduler
        .metrics(session)
        .into_iter()
        .map(|(metric, value)| {
          externs::store_tuple(&[
            externs::store_bytes(metric.as_bytes()),
            externs::store_i64(value),
          ])
        })
        .collect::<Vec<_>>();
      externs::store_tuple(&values).into()
    })
  })
}

///
/// Prepares to fork by shutting down any background threads used for execution, and then
/// calling the given callback function (which should execute the fork) while holding exclusive
/// access to all relevant locks.
///
#[no_mangle]
pub extern "C" fn scheduler_fork_context(
  scheduler_ptr: *mut Scheduler,
  func: Function,
) -> PyResult {
  with_scheduler(scheduler_ptr, |scheduler| {
    scheduler.core.fork_context(|| {
      externs::exclusive_call(&func.0)
        .map_err(|f| format!("{:?}", f))
        .into()
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
        Box::into_raw(RawNodes::create(
          scheduler.execute(execution_request, session),
        ))
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
  subject: Key,
  product: TypeConstraint,
) -> PyResult {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_execution_request(execution_request_ptr, |execution_request| {
      scheduler
        .add_root_select(execution_request, subject, product)
        .into()
    })
  })
}

#[no_mangle]
pub extern "C" fn tasks_create() -> *const Tasks {
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  Box::into_raw(Box::new(Tasks::new()))
}

#[no_mangle]
pub extern "C" fn tasks_singleton_add(
  tasks_ptr: *mut Tasks,
  handle: Handle,
  output_constraint: TypeConstraint,
) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.singleton_add(handle.into(), output_constraint);
  })
}

#[no_mangle]
pub extern "C" fn tasks_task_begin(
  tasks_ptr: *mut Tasks,
  func: Function,
  output_type: TypeConstraint,
) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.task_begin(func, output_type);
  })
}

#[no_mangle]
pub extern "C" fn tasks_add_get(tasks_ptr: *mut Tasks, product: TypeConstraint, subject: TypeId) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.add_get(product, subject);
  })
}

#[no_mangle]
pub extern "C" fn tasks_add_select(tasks_ptr: *mut Tasks, product: TypeConstraint) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.add_select(product);
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
pub extern "C" fn graph_len(scheduler_ptr: *mut Scheduler) -> u64 {
  with_scheduler(scheduler_ptr, |scheduler| scheduler.core.graph.len() as u64)
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
pub extern "C" fn graph_trace(
  scheduler_ptr: *mut Scheduler,
  execution_request_ptr: *mut ExecutionRequest,
  path_ptr: *const raw::c_char,
) {
  let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
  let path = PathBuf::from(path_str);
  with_scheduler(scheduler_ptr, |scheduler| {
    with_execution_request(execution_request_ptr, |execution_request| {
      scheduler
        .trace(execution_request, path.as_path())
        .unwrap_or_else(|e| {
          println!("Failed to write trace to {}: {:?}", path.display(), e);
        });
    });
  });
}

#[no_mangle]
pub extern "C" fn nodes_destroy(raw_nodes_ptr: *mut RawNodes) {
  let _ = unsafe { Box::from_raw(raw_nodes_ptr) };
}

#[no_mangle]
pub extern "C" fn session_create(scheduler_ptr: *mut Scheduler) -> *const Session {
  with_scheduler(scheduler_ptr, |scheduler| {
    Box::into_raw(Box::new(Session::new(scheduler)))
  })
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
  subject_types: TypeIdBuffer,
  path_ptr: *const raw::c_char,
) {
  with_scheduler(scheduler_ptr, |scheduler| {
    let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
    let path = PathBuf::from(path_str);

    let graph = graph_full(scheduler, subject_types.to_vec());
    write_to_file(path.as_path(), &graph).unwrap_or_else(|e| {
      println!("Failed to visualize to {}: {:?}", path.display(), e);
    });
  })
}

#[no_mangle]
pub extern "C" fn rule_subgraph_visualize(
  scheduler_ptr: *mut Scheduler,
  subject_type: TypeId,
  product_type: TypeConstraint,
  path_ptr: *const raw::c_char,
) {
  with_scheduler(scheduler_ptr, |scheduler| {
    let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
    let path = PathBuf::from(path_str);

    let graph = graph_sub(scheduler, subject_type, product_type);
    write_to_file(path.as_path(), &graph).unwrap_or_else(|e| {
      println!("Failed to visualize to {}: {:?}", path.display(), e);
    });
  })
}

#[no_mangle]
pub extern "C" fn set_panic_handler() {
  panic::set_hook(Box::new(|panic_info| {
    let mut panic_str = format!(
      "panic at '{}'",
      panic_info.payload().downcast_ref::<&str>().unwrap()
    );

    if let Some(location) = panic_info.location() {
      let panic_location_str = format!(", {}:{}", location.file(), location.line());
      panic_str.push_str(&panic_location_str);
    }

    error!("{}", panic_str);

    let panic_file_bug_str = "Please file a bug at https://github.com/pantsbuild/pants/issues.";
    error!("{}", panic_file_bug_str);
  }));
}

#[no_mangle]
pub extern "C" fn garbage_collect_store(scheduler_ptr: *mut Scheduler) {
  with_scheduler(scheduler_ptr, |scheduler| {
    match scheduler.core.store.garbage_collect() {
      Ok(_) => {}
      Err(err) => error!("{}", err),
    }
  });
}

#[no_mangle]
pub extern "C" fn lease_files_in_graph(scheduler_ptr: *mut Scheduler) {
  with_scheduler(scheduler_ptr, |scheduler| {
    let digests = scheduler.core.graph.all_digests();
    match scheduler.core.store.lease_all(digests.iter()) {
      Ok(_) => {}
      Err(err) => error!("{}", &err),
    }
  });
}

#[no_mangle]
pub extern "C" fn capture_snapshots(
  scheduler_ptr: *mut Scheduler,
  path_globs_and_root_tuple_wrapper: Handle,
) -> PyResult {
  let values = externs::project_multi(&path_globs_and_root_tuple_wrapper.into(), "dependencies");
  let path_globs_and_roots_result: Result<Vec<(fs::PathGlobs, PathBuf)>, String> = values
    .iter()
    .map(|value| {
      let root = PathBuf::from(externs::project_str(&value, "root"));
      let path_globs =
        nodes::Snapshot::lift_path_globs(&externs::project_ignoring_type(&value, "path_globs"));
      path_globs.map(|path_globs| (path_globs, root))
    })
    .collect();

  let path_globs_and_roots = match path_globs_and_roots_result {
    Ok(v) => v,
    Err(err) => {
      let e: Result<Value, String> = Err(err);
      return e.into();
    }
  };

  with_scheduler(scheduler_ptr, |scheduler| {
    let core = scheduler.core.clone();
    futures::future::join_all(
      path_globs_and_roots
        .into_iter()
        .map(|(path_globs, root)| {
          let core = core.clone();
          scheduler
            .capture_snapshot_from_arbitrary_root(root, path_globs)
            .map(move |snapshot| nodes::Snapshot::store_snapshot(&core, &snapshot))
        })
        .collect::<Vec<_>>(),
    )
  }).map(|values| externs::store_tuple(&values))
    .wait()
    .into()
}

#[no_mangle]
pub extern "C" fn merge_directories(
  scheduler_ptr: *mut Scheduler,
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
    fs::Snapshot::merge_directories(scheduler.core.store.clone(), digests)
      .wait()
      .map(|dir| nodes::Snapshot::store_directory(&scheduler.core, &dir))
      .into()
  })
}

#[no_mangle]
pub extern "C" fn materialize_directories(
  scheduler_ptr: *mut Scheduler,
  directories_paths_and_digests_value: Handle,
) -> PyResult {
  let values = externs::project_multi(&directories_paths_and_digests_value.into(), "dependencies");
  let directories_paths_and_digests_results: Result<Vec<(PathBuf, Digest)>, String> = values
    .iter()
    .map(|value| {
      let dir = PathBuf::from(externs::project_str(&value, "path"));
      let dir_digest =
        nodes::lift_digest(&externs::project_ignoring_type(&value, "directory_digest"));
      dir_digest.map(|dir_digest| (dir, dir_digest))
    })
    .collect();

  let dir_and_digests = match directories_paths_and_digests_results {
    Ok(d) => d,
    Err(err) => {
      let e: Result<Value, String> = Err(err);
      return e.into();
    }
  };

  with_scheduler(scheduler_ptr, |scheduler| {
    futures::future::join_all(
      dir_and_digests
        .into_iter()
        .map(|(dir, digest)| scheduler.core.store.materialize_directory(dir, digest))
        .collect::<Vec<_>>(),
    )
  }).map(|_| ())
    .wait()
    .into()
}

fn graph_full(scheduler: &Scheduler, subject_types: Vec<TypeId>) -> RuleGraph {
  let graph_maker = GraphMaker::new(&scheduler.core.tasks, subject_types);
  graph_maker.full_graph()
}

fn graph_sub(
  scheduler: &Scheduler,
  subject_type: TypeId,
  product_type: TypeConstraint,
) -> RuleGraph {
  let graph_maker = GraphMaker::new(&scheduler.core.tasks, vec![subject_type]);
  graph_maker.sub_graph(&subject_type, &product_type)
}

fn write_to_file(path: &Path, graph: &RuleGraph) -> io::Result<()> {
  let file = File::create(path)?;
  let mut f = io::BufWriter::new(file);
  graph.visualize(&mut f)
}

///
/// Scheduler and Session are intended to be shared between threads, and so their context
/// methods provide immutable references. The remaining types are not intended to be shared
/// between threads, so mutable access is provided.
///
fn with_scheduler<F, T>(scheduler_ptr: *mut Scheduler, f: F) -> T
where
  F: FnOnce(&Scheduler) -> T,
{
  let scheduler = unsafe { Box::from_raw(scheduler_ptr) };
  let t = f(&scheduler);
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
