// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

mod context;
mod core;
mod externs;
mod graph;
mod handles;
mod nodes;
mod rule_graph;
mod scheduler;
mod selectors;
mod tasks;
mod types;

extern crate boxfuture;
extern crate fnv;
extern crate fs;
extern crate futures;
extern crate hashing;
#[macro_use]
extern crate lazy_static;
extern crate ordermap;
extern crate petgraph;
extern crate process_execution;

use std::ffi::CStr;
use std::fs::File;
use std::io;
use std::mem;
use std::os::raw;
use std::panic;
use std::path::{Path, PathBuf};


use context::Core;
use core::{Failure, Function, Key, TypeConstraint, TypeId, Value};
use externs::{Buffer, BufferBuffer, CloneValExtern, DropHandlesExtern, CreateExceptionExtern,
              ExternContext, Externs, IdToStrExtern, InvokeRunnable, LogExtern, KeyForExtern,
              ProjectExtern, ProjectMultiExtern, ProjectIgnoringTypeExtern, SatisfiedByExtern,
              StoreI32Extern, SatisfiedByTypeExtern, StoreListExtern, StoreBytesExtern,
              TypeIdBuffer, ValForExtern, ValToStrExtern};
use rule_graph::{GraphMaker, RuleGraph};
use scheduler::{ExecutionRequest, RootResult, Scheduler};
use tasks::Tasks;
use types::Types;

#[repr(C)]
enum RawStateTag {
  Return = 1,
  Throw = 2,
  Noop = 3,
  Invalidated = 4,
}

#[repr(C)]
pub struct RawNode {
  subject: Key,
  product: TypeConstraint,
  // The Value represents a union tagged with RawStateTag.
  state_tag: u8,
  state_value: Value,
}

impl RawNode {
  fn create(subject: &Key, product: &TypeConstraint, state: RootResult) -> RawNode {
    let (state_tag, state_value) = match state {
      Ok(v) => (RawStateTag::Return as u8, v),
      Err(Failure::Throw(exc, _)) => (RawStateTag::Throw as u8, exc),
      Err(Failure::Noop(noop)) => (
        RawStateTag::Noop as u8,
        externs::create_exception(&format!("{:?}", noop)),
      ),
      Err(Failure::Invalidated) => (
        RawStateTag::Invalidated as u8,
        externs::create_exception(
          "Exhausted retries due to changed files.",
        ),
      ),
    };

    RawNode {
      subject: subject.clone(),
      product: product.clone(),
      state_tag: state_tag,
      state_value: state_value,
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
      .map(|(subject, product, state)| {
        RawNode::create(subject, product, state)
      })
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
  ext_context: *const ExternContext,
  log: LogExtern,
  key_for: KeyForExtern,
  val_for: ValForExtern,
  clone_val: CloneValExtern,
  drop_handles: DropHandlesExtern,
  id_to_str: IdToStrExtern,
  val_to_str: ValToStrExtern,
  satisfied_by: SatisfiedByExtern,
  satisfied_by_type: SatisfiedByTypeExtern,
  store_list: StoreListExtern,
  store_bytes: StoreBytesExtern,
  store_i32: StoreI32Extern,
  project: ProjectExtern,
  project_ignoring_type: ProjectIgnoringTypeExtern,
  project_multi: ProjectMultiExtern,
  create_exception: CreateExceptionExtern,
  invoke_runnable: InvokeRunnable,
  py_str_type: TypeId,
) {
  externs::set_externs(Externs::new(
    ext_context,
    log,
    key_for,
    val_for,
    clone_val,
    drop_handles,
    id_to_str,
    val_to_str,
    satisfied_by,
    satisfied_by_type,
    store_list,
    store_bytes,
    store_i32,
    project,
    project_ignoring_type,
    project_multi,
    create_exception,
    invoke_runnable,
    py_str_type,
  ));
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
  construct_snapshot: Function,
  construct_snapshots: Function,
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
  type_snapshot: TypeConstraint,
  type_snapshots: TypeConstraint,
  type_files_content: TypeConstraint,
  type_dir: TypeConstraint,
  type_file: TypeConstraint,
  type_link: TypeConstraint,
  type_process_request: TypeConstraint,
  type_process_result: TypeConstraint,
  type_string: TypeId,
  type_bytes: TypeId,
  build_root_buf: Buffer,
  work_dir_buf: Buffer,
  ignore_patterns_buf: BufferBuffer,
  root_type_ids: TypeIdBuffer,
) -> *const Scheduler {
  let root_type_ids = root_type_ids.to_vec();
  let ignore_patterns = ignore_patterns_buf.to_strings().unwrap_or_else(|e| {
    panic!("Failed to decode ignore patterns as UTF8: {:?}", e)
  });
  let tasks = with_tasks(tasks_ptr, |tasks| tasks.clone());
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  Box::into_raw(Box::new(Scheduler::new(Core::new(
    root_type_ids.clone(),
    tasks,
    Types {
      construct_snapshot: construct_snapshot,
      construct_snapshots: construct_snapshots,
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
      snapshot: type_snapshot,
      snapshots: type_snapshots,
      files_content: type_files_content,
      dir: type_dir,
      file: type_file,
      link: type_link,
      process_request: type_process_request,
      process_result: type_process_result,
      string: type_string,
      bytes: type_bytes,
    },
    build_root_buf.to_os_string().as_ref(),
    ignore_patterns,
    work_dir_buf.to_os_string().as_ref(),
  ))))
}

#[no_mangle]
pub extern "C" fn scheduler_pre_fork(scheduler_ptr: *mut Scheduler) {
  with_scheduler(scheduler_ptr, |scheduler| { scheduler.core.pre_fork(); })
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
) {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_execution_request(execution_request_ptr, |execution_request| {
      scheduler.add_root_select(execution_request, subject, product);
    })
  })
}

#[no_mangle]
pub extern "C" fn execution_execute(
  scheduler_ptr: *mut Scheduler,
  execution_request_ptr: *mut ExecutionRequest,
) -> *const RawNodes {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_execution_request(execution_request_ptr, |execution_request| {
      Box::into_raw(RawNodes::create(scheduler.execute(execution_request)))
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
  value: Value,
  output_constraint: TypeConstraint,
) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.singleton_add(value, output_constraint);
  })
}

#[no_mangle]
pub extern "C" fn tasks_task_begin(
  tasks_ptr: *mut Tasks,
  func: Function,
  output_type: TypeConstraint,
) {
  with_tasks(tasks_ptr, |tasks| { tasks.task_begin(func, output_type); })
}

#[no_mangle]
pub extern "C" fn tasks_add_select(tasks_ptr: *mut Tasks, product: TypeConstraint) {
  with_tasks(tasks_ptr, |tasks| { tasks.add_select(product, None); })
}

#[no_mangle]
pub extern "C" fn tasks_add_select_variant(
  tasks_ptr: *mut Tasks,
  product: TypeConstraint,
  variant_key_buf: Buffer,
) {
  let variant_key = variant_key_buf.to_string().expect(
    "Failed to decode key for select_variant",
  );
  with_tasks(tasks_ptr, |tasks| {
    tasks.add_select(product, Some(variant_key));
  })
}

#[no_mangle]
pub extern "C" fn tasks_add_select_dependencies(
  tasks_ptr: *mut Tasks,
  product: TypeConstraint,
  dep_product: TypeConstraint,
  field: Buffer,
  field_types: TypeIdBuffer,
) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.add_select_dependencies(
      product,
      dep_product,
      field.to_string().expect("field to be a string"),
      field_types.to_vec(),
    );
  })
}

#[no_mangle]
pub extern "C" fn tasks_add_select_transitive(
  tasks_ptr: *mut Tasks,
  product: TypeConstraint,
  dep_product: TypeConstraint,
  field: Buffer,
  field_types: TypeIdBuffer,
) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.add_select_transitive(
      product,
      dep_product,
      field.to_string().expect("field to be a string"),
      field_types.to_vec(),
    );
  })
}

#[no_mangle]
pub extern "C" fn tasks_add_select_projection(
  tasks_ptr: *mut Tasks,
  product: TypeConstraint,
  projected_subject: TypeId,
  field: Buffer,
  input_product: TypeConstraint,
) {
  with_tasks(tasks_ptr, |tasks| {
    tasks.add_select_projection(
      product,
      projected_subject,
      field.to_string().expect("field to be a string"),
      input_product,
    );
  })
}

#[no_mangle]
pub extern "C" fn tasks_task_end(tasks_ptr: *mut Tasks) {
  with_tasks(tasks_ptr, |tasks| { tasks.task_end(); })
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
      .map(|os_str| PathBuf::from(os_str))
      .collect();
    scheduler.core.graph.invalidate(paths) as u64
  })
}

#[no_mangle]
pub extern "C" fn graph_len(scheduler_ptr: *mut Scheduler) -> u64 {
  with_scheduler(scheduler_ptr, |scheduler| scheduler.core.graph.len() as u64)
}

#[no_mangle]
pub extern "C" fn graph_visualize(
  scheduler_ptr: *mut Scheduler,
  execution_request_ptr: *mut ExecutionRequest,
  path_ptr: *const raw::c_char,
) {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_execution_request(execution_request_ptr, |execution_request| {
      let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
      let path = PathBuf::from(path_str);
      // TODO: This should likely return an error condition to python.
      //   see https://github.com/pantsbuild/pants/issues/4025
      scheduler
        .visualize(execution_request, path.as_path())
        .unwrap_or_else(|e| {
          println!("Failed to visualize to {}: {:?}", path.display(), e);
        });
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
pub extern "C" fn execution_request_create() -> *const ExecutionRequest {
  Box::into_raw(Box::new(ExecutionRequest::new()))
}

#[no_mangle]
pub extern "C" fn execution_request_destroy(ptr: *mut ExecutionRequest) {
  let _ = unsafe { Box::from_raw(ptr) };
}

#[no_mangle]
pub extern "C" fn validator_run(scheduler_ptr: *mut Scheduler) -> Value {
  with_scheduler(scheduler_ptr, |scheduler| match scheduler
    .core
    .rule_graph
    .validate() {
    Result::Ok(_) => externs::store_list(vec![], false),
    Result::Err(msg) => externs::create_exception(&msg),
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

    externs::log(externs::LogLevel::Critical, &panic_str);

    let panic_file_bug_str = "Please file a bug at https://github.com/pantsbuild/pants/issues.";
    externs::log(externs::LogLevel::Critical, &panic_file_bug_str);
  }));
}

fn graph_full(scheduler: &mut Scheduler, subject_types: Vec<TypeId>) -> RuleGraph {
  let graph_maker = GraphMaker::new(&scheduler.core.tasks, subject_types);
  graph_maker.full_graph()
}

fn graph_sub(
  scheduler: &mut Scheduler,
  subject_type: TypeId,
  product_type: TypeConstraint,
) -> RuleGraph {
  let graph_maker = GraphMaker::new(&scheduler.core.tasks, vec![subject_type.clone()]);
  graph_maker.sub_graph(&subject_type, &product_type)
}

fn write_to_file(path: &Path, graph: &RuleGraph) -> io::Result<()> {
  let file = File::create(path)?;
  let mut f = io::BufWriter::new(file);
  graph.visualize(&mut f)
}

fn with_scheduler<F, T>(scheduler_ptr: *mut Scheduler, f: F) -> T
where
  F: FnOnce(&mut Scheduler) -> T,
{
  let mut scheduler = unsafe { Box::from_raw(scheduler_ptr) };
  let t = f(&mut scheduler);
  mem::forget(scheduler);
  t
}

fn with_execution_request<F, T>(execution_request_ptr: *mut ExecutionRequest, f: F) -> T
where
  F: FnOnce(&mut ExecutionRequest) -> T,
{
  let mut execution_request = unsafe { Box::from_raw(execution_request_ptr) };
  let t = f(&mut execution_request);
  mem::forget(execution_request);
  t
}

fn with_tasks<F, T>(tasks_ptr: *mut Tasks, f: F) -> T
where
  F: FnOnce(&mut Tasks) -> T,
{
  let mut tasks = unsafe { Box::from_raw(tasks_ptr) };
  let t = f(&mut tasks);
  mem::forget(tasks);
  t
}
