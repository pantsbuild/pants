mod core;
mod externs;
mod graph;
mod nodes;
mod scheduler;
mod selectors;
mod tasks;

extern crate fnv;

use std::ffi::CStr;
use std::mem;
use std::os::raw;
use std::path::Path;

use core::{Field, Function, Key, RunnableComplete, TypeConstraint, TypeId, Value};
use externs::{
  CreateExceptionExtern,
  ExternContext,
  Externs,
  IdToStrExtern,
  InvokeRunnable,
  KeyForExtern,
  ProjectExtern,
  ProjectMultiExtern,
  SatisfiedByExtern,
  StoreListExtern,
  UTF8Buffer,
  ValToStrExtern,
  with_vec,
};
use graph::{Graph, EntryId};
use nodes::{Complete, Runnable};
use scheduler::Scheduler;
use tasks::Tasks;

pub struct RawScheduler {
  execution: RawExecution,
  scheduler: Scheduler,
}

impl RawScheduler {
  fn next(&mut self, completed: Vec<(EntryId, Complete)>) {
    self.execution.update(self.scheduler.next(completed));
  }

  fn reset(&mut self) {
    self.scheduler.reset();
    self.execution.update(Vec::new());
  }
}

/**
 * An unzipped, raw-pointer form of the return value of Scheduler.next().
 */
pub struct RawExecution {
  runnables_ptr: *const RawRunnable,
  runnables_len: u64,
  runnables: Vec<(EntryId, Runnable)>,
  raw_runnables: Vec<RawRunnable>,
}

impl RawExecution {
  fn new() -> RawExecution {
    let mut execution =
      RawExecution {
        runnables_ptr: Vec::new().as_ptr(),
        runnables_len: 0,
        runnables: Vec::new(),
        raw_runnables: Vec::new(),
      };
    // NB: Unsafe: because we need a raw pointer to a value in the struct, we started by
    // initializing it to a meaningless value above (since we don't know where it will be
    // in memory during struct construction), and then here we update it to be valid.
    execution.update(Vec::new());
    execution
  }

  fn update(&mut self, ready_entries: Vec<(EntryId, Runnable)>) {
    self.runnables = ready_entries;

    self.raw_runnables =
      self.runnables.iter()
        .map(|&(id, ref runnable)| {
          RawRunnable {
            id: id,
            func: runnable.func() as *const Function,
            args_ptr: runnable.args().as_ptr(),
            args_len: runnable.args().len() as u64,
            cacheable: runnable.cacheable(),
          }
        })
        .collect();

    self.runnables_ptr = self.raw_runnables.as_mut_ptr();
    self.runnables_len = self.raw_runnables.len() as u64;
  }
}

#[repr(C)]
pub struct RawRunnable {
  id: EntryId,
  // Single Key.
  func: *const Function,
  // Array of args.
  args_ptr: *const Value,
  args_len: u64,
  // Boolean value indicating whether the runnable is cacheable.
  cacheable: bool,
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
  // The following values represent a union.
  // TODO: switch to https://github.com/rust-lang/rfcs/pull/1444 when it is available in
  // a stable release.
  state_tag: u8,
  state_return: Value,
  state_throw: Value,
  state_noop: bool,
}

impl RawNode {
  fn new(subject: &Key, product: &TypeConstraint, state: Option<&Complete>) -> RawNode {
    RawNode {
      subject: subject.clone(),
      product: product.clone(),
      state_tag:
        match state {
          None => RawStateTag::Empty as u8,
          Some(&Complete::Return(_)) => RawStateTag::Return as u8,
          Some(&Complete::Throw(_)) => RawStateTag::Throw as u8,
          Some(&Complete::Noop(_, _)) => RawStateTag::Noop as u8,
        },
      state_return: match state {
        Some(&Complete::Return(ref v)) => v.clone(),
        _ => Default::default(),
      },
      state_throw: match state {
        Some(&Complete::Throw(ref v)) => v.clone(),
        _ => Default::default(),
      },
      state_noop: match state {
        Some(&Complete::Noop(_, _)) => true,
        _ => false,
      },
    }
  }
}

pub struct RawNodes {
  nodes_ptr: *const RawNode,
  nodes_len: u64,
  nodes: Vec<RawNode>,
}

impl RawNodes {
  fn new(node_states: Vec<(&Key, &TypeConstraint, Option<&Complete>)>) -> Box<RawNodes> {
    let nodes =
      node_states.iter()
        .map(|&(subject, product, state)|
          RawNode::new(subject, product, state)
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
  key_for: KeyForExtern,
  id_to_str: IdToStrExtern,
  val_to_str: ValToStrExtern,
  satisfied_by: SatisfiedByExtern,
  store_list: StoreListExtern,
  project: ProjectExtern,
  project_multi: ProjectMultiExtern,
  create_exception: CreateExceptionExtern,
  invoke_runnable: InvokeRunnable,
  field_name: Field,
  field_products: Field,
  field_variants: Field,
  type_address: TypeConstraint,
  type_has_products: TypeConstraint,
  type_has_variants: TypeConstraint,
) -> *const RawScheduler {
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  let externs =
    Externs::new(
      ext_context,
      key_for,
      id_to_str,
      val_to_str,
      satisfied_by,
      store_list,
      project,
      project_multi,
      create_exception,
      invoke_runnable,
    );
  Box::into_raw(
    Box::new(
      RawScheduler {
        execution: RawExecution::new(),
        scheduler: Scheduler::new(
          Graph::new(),
          Tasks::new(
            externs,
            field_name,
            field_products,
            field_variants,
            type_address,
            type_has_products,
            type_has_variants,
          ),
        ),
      }
    )
  )
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
  transitive: bool,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.add_root_select_dependencies(
      subject,
      product,
      dep_product,
      field,
      transitive,
    );
  })
}

#[no_mangle]
pub extern fn execution_next(
  scheduler_ptr: *mut RawScheduler,
  states_ptr: *mut EntryId,
  states_values_ptr: *mut Value,
  states_are_throws_ptr: *mut bool,
  states_len: u64,
) {
  with_scheduler(scheduler_ptr, |raw| {
    with_vec(states_ptr, states_len as usize, |states_ids| {
      with_vec(states_values_ptr, states_len as usize, |states_values| {
        with_vec(states_are_throws_ptr, states_len as usize, |states_are_throws| {
          let states =
            states_ids.iter().zip(states_values.iter()).zip(states_are_throws.iter())
              .map(|((&id, value), &is_throw)| {
                if is_throw {
                  (id, Complete::Throw(value.clone()))
                } else {
                  (id, Complete::Return(value.clone()))
                }
              })
              .collect();
          raw.next(states);
        })
      })
    })
  })
}

#[no_mangle]
pub extern fn execution_execute(
  scheduler_ptr: *mut RawScheduler,
) {
  with_scheduler(scheduler_ptr, |raw| {
    let mut completed = Vec::new();
    loop {
      let runnable_batch = raw.scheduler.next(completed);
      if runnable_batch.len() == 0 {
        break;
      }
      completed =
        runnable_batch.iter()
          .map(|&(id, ref runnable)| {
            let result: RunnableComplete = raw.scheduler.tasks.externs.invoke_runnable(runnable);
            if result.is_throw() {
              (id, Complete::Throw(result.value().clone()))
            } else {
              (id, Complete::Return(result.value().clone()))
            }
          })
          .collect();
    }
  })
}

#[no_mangle]
pub extern fn execution_roots(
  scheduler_ptr: *mut RawScheduler,
) -> *const RawNodes {
  with_scheduler(scheduler_ptr, |raw| {
    Box::into_raw(RawNodes::new(raw.scheduler.root_states()))
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
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.intrinsic_add(func, input_type, input_constraint, output_constraint);
  })
}

#[no_mangle]
pub extern fn singleton_task_add(
  scheduler_ptr: *mut RawScheduler,
  func: Function,
  output_constraint: TypeConstraint,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.singleton_add(func, output_constraint);
  })
}

#[no_mangle]
pub extern fn task_add(
  scheduler_ptr: *mut RawScheduler,
  func: Function,
  output_type: TypeConstraint,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.task_add(func, output_type);
  })
}

#[no_mangle]
pub extern fn task_add_select(
  scheduler_ptr: *mut RawScheduler,
  product: TypeConstraint,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.add_select(product, None);
  })
}

#[no_mangle]
pub extern fn task_add_select_variant(
  scheduler_ptr: *mut RawScheduler,
  product: TypeConstraint,
  variant_key_buf: UTF8Buffer,
) {
  let variant_key =
    variant_key_buf.to_string().expect("Failed to decode key for select_variant");
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.add_select(product, Some(variant_key));
  })
}

#[no_mangle]
pub extern fn task_add_select_literal(
  scheduler_ptr: *mut RawScheduler,
  subject: Key,
  product: TypeConstraint,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.add_select_literal(subject, product);
  })
}

#[no_mangle]
pub extern fn task_add_select_dependencies(
  scheduler_ptr: *mut RawScheduler,
  product: TypeConstraint,
  dep_product: TypeConstraint,
  field: Field,
  transitive: bool,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.add_select_dependencies(product, dep_product, field, transitive);
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
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.add_select_projection(product, projected_subject, field, input_product);
  })
}

#[no_mangle]
pub extern fn task_end(scheduler_ptr: *mut RawScheduler) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.task_end();
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
      raw.scheduler.graph.invalidate(subjects_set) as u64
    })
  })
}

#[no_mangle]
pub extern fn graph_len(scheduler_ptr: *mut RawScheduler) -> u64 {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.graph.len() as u64
  })
}

#[no_mangle]
pub extern fn graph_visualize(scheduler_ptr: *mut RawScheduler, path_ptr: *const raw::c_char) {
  with_scheduler(scheduler_ptr, |raw| {
    let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
    let path = Path::new(path_str.as_str());
    // TODO: This should likely return an error condition to python.
    //   see https://github.com/pantsbuild/pants/issues/4025
    raw.scheduler.visualize(&path).unwrap_or_else(|e| {
      println!("Failed to visualize to {}: {:?}", path.display(), e);
    });
  })
}

#[no_mangle]
pub extern fn graph_trace(scheduler_ptr: *mut RawScheduler, path_ptr: *const raw::c_char) {
  let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
  let path = Path::new(path_str.as_str());
  with_scheduler(scheduler_ptr, |raw| {
     raw.scheduler.trace(path).unwrap_or_else(|e| {
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

fn with_scheduler<F, T>(scheduler_ptr: *mut RawScheduler, f: F) -> T
    where F: FnOnce(&mut RawScheduler)->T {
  let mut scheduler = unsafe { Box::from_raw(scheduler_ptr) };
  let t = f(&mut scheduler);
  mem::forget(scheduler);
  t
}
