// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

mod core;
mod context;
mod externs;
mod fs;
mod graph;
mod handles;
mod nodes;
mod rule_graph;
mod scheduler;
mod selectors;
mod tasks;
mod types;

extern crate crossbeam;
extern crate fnv;
extern crate futures;
extern crate futures_cpupool;
extern crate glob;
extern crate ignore;
#[macro_use]
extern crate lazy_static;
extern crate ordermap;
extern crate sha2;
extern crate tar;
extern crate tempdir;

use std::ffi::CStr;
use std::mem;
use std::os::raw;
use std::path::PathBuf;
use std::sync::Arc;

use context::Core;
use core::{Field, Function, Key, TypeConstraint, TypeId, Value};
use externs::{
  Buffer,
  CloneValExtern,
  DropHandlesExtern,
  CreateExceptionExtern,
  ExternContext,
  Externs,
  IdToStrExtern,
  InvokeRunnable,
  LiftBytesExtern,
  LogExtern,
  KeyForExtern,
  ProjectExtern,
  ProjectMultiExtern,
  SatisfiedByExtern,
  StoreListExtern,
  StoreBytesExtern,
  TypeIdBuffer,
  ValForExtern,
  ValToStrExtern,
  with_vec,
};
use nodes::{Failure, NodeResult};
use rule_graph::{GraphMaker, RootSubjectTypes};
use scheduler::{Scheduler, ExecutionStat};
use tasks::Tasks;
use types::Types;

pub struct RawScheduler {
  scheduler: Scheduler,
}

impl RawScheduler {
  fn reset(&mut self) {
    self.scheduler.reset();
  }
}

#[repr(C)]
enum RawStateTag {
  Empty = 0,
  Return = 1,
  Throw = 2,
  Noop = 3,
}

#[repr(C)]
pub struct RawNode {
  subject: Key,
  product: TypeConstraint,
  // The Value represents a union tagged with RawStateTag.
  state_tag: u8,
  state_value: Value
}

impl RawNode {
  fn create(
    externs: &Externs,
    subject: &Key,
    product: &TypeConstraint,
    state: Option<NodeResult>,
  ) -> RawNode {
    let (state_tag, state_value) =
      match state {
        None =>
          (RawStateTag::Empty as u8, externs.create_exception("No value")),
        Some(Ok(v)) =>
          (RawStateTag::Return as u8, v),
        Some(Err(Failure::Throw(msg))) =>
          (RawStateTag::Throw as u8, msg),
        Some(Err(Failure::Noop(msg, _))) =>
          (RawStateTag::Noop as u8, externs.create_exception(msg)),
      };

    RawNode {
      subject: subject.clone(),
      product: product.clone(),
      state_tag: state_tag,
      state_value: state_value,
    }
  }
}

pub struct RawNodes {
  nodes_ptr: *const RawNode,
  nodes_len: u64,
  nodes: Vec<RawNode>,
}

impl RawNodes {
  fn create(
    externs: &Externs,
    node_states: Vec<(&Key, &TypeConstraint, Option<NodeResult>)>
  ) -> Box<RawNodes> {
    let nodes =
      node_states.into_iter()
        .map(|(subject, product, state)|
          RawNode::create(externs, subject, product, state)
        )
        .collect();
    let mut raw_nodes =
      Box::new(
        RawNodes {
          nodes_ptr: Vec::new().as_ptr(),
          nodes_len: 0,
          nodes: nodes,
        }
      );
    // NB: Unsafe! See comment on similar pattern in RawExecution::new().
    raw_nodes.nodes_ptr = raw_nodes.nodes.as_ptr();
    raw_nodes.nodes_len = raw_nodes.nodes.len() as u64;
    raw_nodes
  }
}

#[no_mangle]
pub extern fn scheduler_create(
  ext_context: *const ExternContext,
  log: LogExtern,
  key_for: KeyForExtern,
  val_for: ValForExtern,
  clone_val: CloneValExtern,
  drop_handles: DropHandlesExtern,
  id_to_str: IdToStrExtern,
  val_to_str: ValToStrExtern,
  satisfied_by: SatisfiedByExtern,
  store_list: StoreListExtern,
  store_bytes: StoreBytesExtern,
  lift_bytes: LiftBytesExtern,
  project: ProjectExtern,
  project_multi: ProjectMultiExtern,
  create_exception: CreateExceptionExtern,
  invoke_runnable: InvokeRunnable,
  field_name: Field,
  field_products: Field,
  field_variants: Field,
  field_include: Field,
  field_exclude: Field,
  field_dependencies: Field,
  field_path: Field,
  field_fingerprint: Field,
  construct_snapshot: Function,
  construct_file_content: Function,
  construct_files_content: Function,
  construct_path_stat: Function,
  construct_dir: Function,
  construct_file: Function,
  construct_link: Function,
  type_address: TypeConstraint,
  type_has_products: TypeConstraint,
  type_has_variants: TypeConstraint,
  type_path_globs: TypeConstraint,
  type_snapshot: TypeConstraint,
  type_files_content: TypeConstraint,
  type_dir: TypeConstraint,
  type_file: TypeConstraint,
  type_link: TypeConstraint,
  type_string: TypeId,
  type_bytes: TypeId,
) -> *const RawScheduler {
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  Box::into_raw(
    Box::new(
      RawScheduler {
        scheduler: Scheduler::new(
          Core::new(
            Tasks::new(
              field_name,
              field_products,
              field_variants,
              field_include,
              field_exclude,
              field_dependencies,
              field_path,
              field_fingerprint,
            ),
            Types {
              construct_snapshot: construct_snapshot,
              construct_file_content: construct_file_content,
              construct_files_content: construct_files_content,
              construct_path_stat: construct_path_stat,
              construct_dir: construct_dir,
              construct_file: construct_file,
              construct_link: construct_link,
              address: type_address,
              has_products: type_has_products,
              has_variants: type_has_variants,
              path_globs: type_path_globs,
              snapshot: type_snapshot,
              files_content: type_files_content,
              dir: type_dir,
              file: type_file,
              link: type_link,
              string: type_string,
              bytes: type_bytes,
            },
            Externs::new(
              ext_context,
              log,
              key_for,
              val_for,
              clone_val,
              drop_handles,
              id_to_str,
              val_to_str,
              satisfied_by,
              store_list,
              store_bytes,
              lift_bytes,
              project,
              project_multi,
              create_exception,
              invoke_runnable,
            ),
            // TODO: Pass build_root and ignore patterns as argument.
            PathBuf::from("."),
            vec![
              ".*".to_string(),
              "/build-support/*.venv/".to_string(),
              "/dist/".to_string(),
            ],
          ),
        )
      }
    )
  )
}

#[no_mangle]
pub extern fn scheduler_post_fork(scheduler_ptr: *mut RawScheduler) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.core.post_fork();
  })
}

#[no_mangle]
pub extern fn scheduler_destroy(scheduler_ptr: *mut RawScheduler) {
  // convert the raw pointer back to a Box (without `forget`ing it) in order to cause it
  // to be destroyed at the end of this function.
  let _ = unsafe { Box::from_raw(scheduler_ptr) };
}

#[no_mangle]
pub extern fn execution_reset(scheduler_ptr: *mut RawScheduler) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.reset();
  })
}

#[no_mangle]
pub extern fn execution_add_root_select(
  scheduler_ptr: *mut RawScheduler,
  subject: Key,
  product: TypeConstraint,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.add_root_select(subject, product);
  })
}

#[no_mangle]
pub extern fn execution_add_root_select_dependencies(
  scheduler_ptr: *mut RawScheduler,
  subject: Key,
  product: TypeConstraint,
  dep_product: TypeConstraint,
  field: Field,
  field_types: TypeIdBuffer,
  transitive: bool,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.add_root_select_dependencies(
      subject,
      product,
      dep_product,
      field,
      field_types.to_vec(),
      transitive,
    );
  })
}

#[no_mangle]
pub extern fn execution_execute(
  scheduler_ptr: *mut RawScheduler,
) -> ExecutionStat {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.execute()
  })
}

#[no_mangle]
pub extern fn execution_roots(
  scheduler_ptr: *mut RawScheduler,
) -> *const RawNodes {
  with_scheduler(scheduler_ptr, |raw| {
    Box::into_raw(
      RawNodes::create(
        &raw.scheduler.core.externs,
        raw.scheduler.root_states()
      )
    )
  })
}

#[no_mangle]
pub extern fn intrinsic_task_add(
  scheduler_ptr: *mut RawScheduler,
  func: Function,
  input_type: TypeId,
  input_constraint: TypeConstraint,
  output_constraint: TypeConstraint,
) {
  with_core(scheduler_ptr, |core| {
    core.tasks.intrinsic_add(func, input_type, input_constraint, output_constraint);
  })
}

#[no_mangle]
pub extern fn singleton_task_add(
  scheduler_ptr: *mut RawScheduler,
  func: Function,
  output_constraint: TypeConstraint,
) {
  with_core(scheduler_ptr, |core| {
    core.tasks.singleton_add(func, output_constraint);
  })
}

#[no_mangle]
pub extern fn task_add(
  scheduler_ptr: *mut RawScheduler,
  func: Function,
  output_type: TypeConstraint,
) {
  with_core(scheduler_ptr, |core| {
    core.tasks.task_add(func, output_type);
  })
}

#[no_mangle]
pub extern fn task_add_select(
  scheduler_ptr: *mut RawScheduler,
  product: TypeConstraint,
) {
  with_core(scheduler_ptr, |core| {
    core.tasks.add_select(product, None);
  })
}

#[no_mangle]
pub extern fn task_add_select_variant(
  scheduler_ptr: *mut RawScheduler,
  product: TypeConstraint,
  variant_key_buf: Buffer,
) {
  let variant_key =
    variant_key_buf.to_string().expect("Failed to decode key for select_variant");
  with_core(scheduler_ptr, |core| {
    core.tasks.add_select(product, Some(variant_key));
  })
}

#[no_mangle]
pub extern fn task_add_select_literal(
  scheduler_ptr: *mut RawScheduler,
  subject: Key,
  product: TypeConstraint,
) {
  with_core(scheduler_ptr, |core| {
    core.tasks.add_select_literal(subject, product);
  })
}

#[no_mangle]
pub extern fn task_add_select_dependencies(
  scheduler_ptr: *mut RawScheduler,
  product: TypeConstraint,
  dep_product: TypeConstraint,
  field: Field,
  field_types: TypeIdBuffer,
  transitive: bool,
) {
  with_core(scheduler_ptr, |core| {
    core.tasks.add_select_dependencies(product, dep_product, field, field_types.to_vec(), transitive);
  })
}

#[no_mangle]
pub extern fn task_add_select_projection(
  scheduler_ptr: *mut RawScheduler,
  product: TypeConstraint,
  projected_subject: TypeId,
  field: Field,
  input_product: TypeConstraint,
) {
  with_core(scheduler_ptr, |core| {
    core.tasks.add_select_projection(product, projected_subject, field, input_product);
  })
}

#[no_mangle]
pub extern fn task_end(scheduler_ptr: *mut RawScheduler) {
  with_core(scheduler_ptr, |core| {
    core.tasks.task_end();
  })
}

#[no_mangle]
pub extern fn graph_invalidate(
  scheduler_ptr: *mut RawScheduler,
  subjects_ptr: *mut Key,
  subjects_len: u64,
) -> u64 {
  with_scheduler(scheduler_ptr, |raw| {
   with_vec(subjects_ptr, subjects_len as usize, |subjects| {
      let subjects_set = subjects.iter().collect();
      raw.scheduler.core.graph.invalidate(subjects_set) as u64
    })
  })
}

#[no_mangle]
pub extern fn graph_len(scheduler_ptr: *mut RawScheduler) -> u64 {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.core.graph.len() as u64
  })
}

#[no_mangle]
pub extern fn graph_visualize(scheduler_ptr: *mut RawScheduler, path_ptr: *const raw::c_char) {
  with_scheduler(scheduler_ptr, |raw| {
    let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
    let path = PathBuf::from(path_str);
    // TODO: This should likely return an error condition to python.
    //   see https://github.com/pantsbuild/pants/issues/4025
    raw.scheduler.visualize(path.as_path()).unwrap_or_else(|e| {
      println!("Failed to visualize to {}: {:?}", path.display(), e);
    });
  })
}

#[no_mangle]
pub extern fn graph_trace(scheduler_ptr: *mut RawScheduler, path_ptr: *const raw::c_char) {
  let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
  let path = PathBuf::from(path_str);
  with_scheduler(scheduler_ptr, |raw| {
     raw.scheduler.trace(path.as_path()).unwrap_or_else(|e| {
       println!("Failed to write trace to {}: {:?}", path.display(), e);
     });
  });
}


#[no_mangle]
pub extern fn nodes_destroy(raw_nodes_ptr: *mut RawNodes) {
  // convert the raw pointer back to a Box (without `forget`ing it) in order to cause it
  // to be destroyed at the end of this function.
  let _ = unsafe { Box::from_raw(raw_nodes_ptr) };
}

#[no_mangle]
pub extern fn validator_run(
  scheduler_ptr: *mut RawScheduler,
  subject_types_ptr: *mut TypeId,
  subject_types_len: u64
) {
  with_scheduler(scheduler_ptr, |raw| {
    with_vec(subject_types_ptr, subject_types_len as usize, |subject_types| {
      let graph_maker = GraphMaker::new(&raw.scheduler.core.tasks,
                                        &raw.scheduler.core.externs,
                                        RootSubjectTypes { subject_types: subject_types.clone() });
      let graph = graph_maker.full_graph();

      match graph.validate(&raw.scheduler.core.externs) {
        Result::Ok(_) => {},
        Result::Err(msg) => {
          println!("had errors!\n{}", msg)
        }
      }
    })
  })
}

fn with_scheduler<F, T>(scheduler_ptr: *mut RawScheduler, f: F) -> T
    where F: FnOnce(&mut RawScheduler)->T {
  let mut scheduler = unsafe { Box::from_raw(scheduler_ptr) };
  let t = f(&mut scheduler);
  mem::forget(scheduler);
  t
}

/**
 * A helper to allow for mutation of the Tasks struct. This method is unsafe because
 * it must only be called while the Scheduler is not executing any work (usually during
 * initialization).
 *
 * TODO: An alternative to this method would be to move construction of the Tasks struct
 * before construction of the Scheduler, which would allow it to be mutated before it
 * needed to become atomic for usage in the Scheduler.
 */
fn with_core<F, T>(scheduler_ptr: *mut RawScheduler, f: F) -> T
    where F: FnOnce(&mut Core)->T {
  with_scheduler(scheduler_ptr, |raw| {
    let core =
      Arc::get_mut(&mut raw.scheduler.core)
        .expect("The Core may not be mutated once the Scheduler has started.");
    f(core)
  })
}
