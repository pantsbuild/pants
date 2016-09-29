mod core;
mod externs;
mod graph;
mod nodes;
mod scheduler;
mod selectors;
mod tasks;

extern crate libc;
extern crate fnv;

use std::ffi::CStr;
use std::mem;
use std::path::Path;

use core::{Field, Function, Key, TypeId, Value};
use externs::{
  ExternContext,
  Externs,
  IdToStrExtern,
  IsSubClassExtern,
  KeyForExtern,
  ProjectExtern,
  ProjectMultiExtern,
  StoreListExtern,
  ValToStrExtern,
  with_vec,
};
use graph::{Graph, EntryId};
use nodes::{Complete, Staged, StagedArg};
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
  runnables: Vec<Staged<EntryId>>,
  runnable_args: Vec<Vec<RawArg>>,
  raw_runnables: Vec<RawRunnable>,
}

impl RawExecution {
  fn new() -> RawExecution {
    let mut execution =
      RawExecution {
        runnables_ptr: Vec::new().as_ptr(),
        runnables_len: 0,
        runnables: Vec::new(),
        runnable_args: Vec::new(),
        raw_runnables: Vec::new(),
      };
    // Update immediately to make the pointers above (likely dangling!) valid.
    execution.update(Vec::new());
    execution
  }

  fn update(&mut self, ready_entries: Vec<(EntryId, Staged<EntryId>)>) {
    let (ids, runnables): (Vec<_>, Vec<_>) = ready_entries.into_iter().unzip();
    self.runnables = runnables;

    self.runnable_args =
      self.runnables.iter()
        .map(|runnable| runnable.args.iter().map(RawArg::from).collect())
        .collect();

    self.raw_runnables =
      ids.into_iter().zip(self.runnables.iter().zip(self.runnable_args.iter()))
        .map(|(id, (runnable, raw_args))| {
          RawRunnable {
            id: id,
            func: &runnable.func as *const Function,
            args_ptr: raw_args.as_ptr(),
            args_len: raw_args.len() as u64,
            cacheable: runnable.cacheable,
          }
        })
        .collect();

    self.runnables_ptr = self.raw_runnables.as_mut_ptr();
    self.runnables_len = self.raw_runnables.len() as u64;
  }
}

#[repr(C)]
enum RawArgTag {
  Value = 0,
  Promise = 1,
}

#[repr(C)]
pub struct RawArg {
  // A union of either a Value to represent a value, or an EntryId to represent the return
  // value of another Runnable within this batch.
  tag: u8,
  value: Value,
  promise: EntryId,
}

impl RawArg {
  fn from(arg: &StagedArg<EntryId>) -> RawArg {
    match arg {
      &StagedArg::Value(v) =>
        RawArg {
          tag: RawArgTag::Value as u8,
          value: v,
          promise: 0,
        },
      &StagedArg::Promise(id) =>
        RawArg {
          tag: RawArgTag::Promise as u8,
          value: Value::empty(),
          promise: id,
        },
    }
  }
}

#[repr(C)]
pub struct RawRunnable {
  id: EntryId,
  // Single Key.
  func: *const Function,
  // Array of args.
  args_ptr: *const RawArg,
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
  product: TypeId,
  // The following values represent a union.
  // TODO: switch to https://github.com/rust-lang/rfcs/pull/1444 when it is available in
  // a stable release.
  state_tag: u8,
  state_return: Value,
  // TODO: expose as cstrings.
  state_throw: bool,
  state_noop: bool,
}

impl RawNode {
  fn new(subject: &Key, product: &TypeId, state: Option<&Complete>) -> RawNode {
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
        _ => Value::empty(),
      },
      state_throw: match state {
        Some(&Complete::Throw(_)) => true,
        _ => false,
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
  fn new(node_states: Vec<(&Key,&TypeId,Option<&Complete>)>) -> Box<RawNodes> {
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
    // Update immediately to make the pointers above (likely dangling!) valid.
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
  issubclass: IsSubClassExtern,
  store_list: StoreListExtern,
  project: ProjectExtern,
  project_multi: ProjectMultiExtern,
  field_name: Field,
  field_products: Field,
  field_variants: Field,
  type_address: TypeId,
  type_has_products: TypeId,
  type_has_variants: TypeId,
) -> *const RawScheduler {
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  let externs = 
    Externs::new(
      ext_context,
      key_for,
      id_to_str,
      val_to_str,
      issubclass,
      store_list,
      project,
      project_multi,
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
  product: TypeId,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.add_root_select(subject, product);
  })
}

#[no_mangle]
pub extern fn execution_add_root_select_dependencies(
  scheduler_ptr: *mut RawScheduler,
  subject: Key,
  product: TypeId,
  dep_product: TypeId,
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
  returns_ptr: *mut EntryId,
  returns_states_ptr: *mut Value,
  returns_len: u64,
  throws_ptr: *mut EntryId,
  // TODO: empty strings at the moment.
  //throws_states_ptr: **mut CStr,
  throws_len: u64,
) {
  with_scheduler(scheduler_ptr, |raw| {
    with_vec(returns_ptr, returns_len as usize, |returns_ids| {
      with_vec(returns_states_ptr, returns_len as usize, |returns_states| {
        with_vec(throws_ptr, throws_len as usize, |throws_ids| {
          let returns =
            returns_ids.iter().zip(returns_states.iter())
              .map(|(&id, value)| (id, Complete::Return(value.clone())));
          let throws =
            throws_ids.iter()
              .map(|&id| (id, Complete::Throw(format!("{} failed!", id))));
          raw.next(returns.chain(throws).collect());
        })
      })
    })
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
  subject_type: TypeId,
  output_type: TypeId,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.intrinsic_add(func, subject_type, output_type);
  })
}

#[no_mangle]
pub extern fn task_add(
  scheduler_ptr: *mut RawScheduler,
  func: Function,
  output_type: TypeId,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.task_add(func, output_type);
  })
}

#[no_mangle]
pub extern fn task_add_select(
  scheduler_ptr: *mut RawScheduler,
  product: TypeId,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.add_select(product, None);
  })
}

#[no_mangle]
pub extern fn task_add_select_variant(
  scheduler_ptr: *mut RawScheduler,
  product: TypeId,
  variant_key: Key,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.add_select(product, Some(variant_key));
  })
}

#[no_mangle]
pub extern fn task_add_select_literal(
  scheduler_ptr: *mut RawScheduler,
  subject: Key,
  product: TypeId,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.add_select_literal(subject, product);
  })
}

#[no_mangle]
pub extern fn task_add_select_dependencies(
  scheduler_ptr: *mut RawScheduler,
  product: TypeId,
  dep_product: TypeId,
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
  product: TypeId,
  projected_subject: TypeId,
  field: Field,
  input_product: TypeId,
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
pub extern fn graph_len(scheduler_ptr: *mut RawScheduler) -> u64 {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.graph.len() as u64
  })
}

#[no_mangle]
pub extern fn graph_visualize(scheduler_ptr: *mut RawScheduler, path_ptr: *const libc::c_char) {
  with_scheduler(scheduler_ptr, |raw| {
    let path_str = unsafe { CStr::from_ptr(path_ptr).to_string_lossy().into_owned() };
    let path = Path::new(path_str.as_str());
    raw.scheduler.visualize(&path).unwrap_or_else(|e| {
      println!("Failed to visualize to {}: {:?}", path.display(), e);
    });
  })
}

#[no_mangle]
pub extern fn nodes_destroy(raw_nodes_ptr: *mut RawNodes) {
  // convert the raw pointer back to a Box (without `forget`ing it) in order to cause it
  // to be destroyed at the end of this function.
  let _ = unsafe { Box::from_raw(raw_nodes_ptr) };
}

fn with_scheduler<F,T>(scheduler_ptr: *mut RawScheduler, f: F) -> T
    where F: FnOnce(&mut RawScheduler)->T {
  let mut scheduler = unsafe { Box::from_raw(scheduler_ptr) };
  let t = f(&mut scheduler);
  mem::forget(scheduler);
  t
}
