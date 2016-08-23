mod core;
mod externs;
mod graph;
mod nodes;
mod scheduler;
mod selectors;
mod tasks;

extern crate libc;

use core::{Field, Function, Key, TypeId};
use externs::{IsInstanceExtern, IsInstanceFunction, StorageExtern, StoreListExtern, StoreListFunction};
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
  ready_ptr: *const EntryId,
  runnables_ptr: *const RawRunnable,
  len: u64,
  ready: Vec<EntryId>,
  runnables: Vec<Runnable>,
  raw_runnables: Vec<RawRunnable>,
}

impl RawExecution {
  fn new() -> RawExecution {
    let mut execution =
      RawExecution {
        ready_ptr: Vec::new().as_ptr(),
        runnables_ptr: Vec::new().as_ptr(),
        len: 0,
        ready: Vec::new(),
        runnables: Vec::new(),
        raw_runnables: Vec::new(),
      };
    // Update immediately to make the pointers above (likely dangling!) valid.
    execution.update(Vec::new());
    execution
  }

  fn update(&mut self, ready_entries: Vec<(EntryId, Runnable)>) {
    let (ready, runnables) = ready_entries.into_iter().unzip();
    self.ready = ready;
    self.runnables = runnables;

    self.raw_runnables =
      self.runnables.iter()
        .map(|runnable| {
          RawRunnable {
            func: runnable.func() as *const Function,
            args_ptr: runnable.args().as_ptr(),
            args_len: runnable.args().len() as u64,
            cacheable: runnable.cacheable(),
          }
        })
        .collect();

    self.ready_ptr = self.ready.as_mut_ptr();
    self.runnables_ptr = self.raw_runnables.as_mut_ptr();
    self.len = self.ready.len() as u64;

    println!(">>> rust has {} ready entries", self.len);
  }
}

pub struct RawRunnable {
  // Single Key.
  func: *const Function,
  // Array of args.
  args_ptr: *const Key,
  args_len: u64,
  // Boolean value indicating whether the runnable is cacheable.
  cacheable: bool,
}

enum RawState {
  Empty = 0,
  Return = 1,
  Throw = 2,
  Noop = 3,
}

pub struct RawNode {
  subject: Key,
  product: TypeId,
  // The following values represent a union.
  // TODO: switch to https://github.com/rust-lang/rfcs/pull/1444 when it is available in
  // a stable release.
  union_tag: u8,
  union_return: Option<Key>,
  // TODO: expose as cstrings.
  union_throw: bool,
  union_noop: bool,
}

impl RawNode {
  fn new(subject: &Key, product: &TypeId, state: Option<&Complete>) -> RawNode {
    RawNode {
      subject: subject.clone(),
      product: product.clone(),
      union_tag: match state {
        None => RawState::Empty as u8,
        Some(&Complete::Return(_)) => RawState::Return as u8,
        Some(&Complete::Throw(_)) => RawState::Throw as u8,
        Some(&Complete::Noop(_)) => RawState::Noop as u8,
      },
      union_return: match state {
        Some(&Complete::Return(ref r)) => Some(r.clone()),
        _ => None,
      },
      union_throw: match state {
        Some(&Complete::Throw(_)) => true,
        _ => false,
      },
      union_noop: match state {
        Some(&Complete::Noop(_)) => true,
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
  storage: *const StorageExtern,
  isinstance: IsInstanceExtern,
  store_list: StoreListExtern,
  field_name: Field,
  field_products: Field,
  field_variants: Field,
  type_address: TypeId,
  type_has_products: TypeId,
  type_has_variants: TypeId,
) -> *const RawScheduler {
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  println!(">>> rust creating scheduler.");
  Box::into_raw(
    Box::new(
      RawScheduler {
        execution: RawExecution::new(),
        scheduler: Scheduler::new(
          Graph::new(),
          Tasks::new(
            IsInstanceFunction::new(isinstance, storage),
            StoreListFunction::new(store_list, storage),
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
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.add_root_select_dependencies(
      subject,
      product,
      dep_product,
      field,
    );
  })
}

#[no_mangle]
pub extern fn execution_next(
  scheduler_ptr: *mut RawScheduler,
  returns_ptr: *mut EntryId,
  returns_states_ptr: *mut Key,
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
              .map(|(&id, key)| (id, Complete::Return(key.clone())));
          let throws =
            throws_ids.iter()
              .map(|&id| (id, Complete::Throw(format!("{} failed!", id))));
          println!(">>> rust continuing execution for {:?} and {:?}", returns_ids, throws_ids);
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
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.add_select_dependencies(product, dep_product, field);
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
pub extern fn nodes_destroy(raw_nodes_ptr: *mut RawNodes) {
  // convert the raw pointer back to a Box (without `forget`ing it) in order to cause it
  // to be destroyed at the end of this function.
  let _ = unsafe { Box::from_raw(raw_nodes_ptr) };
}

fn with_scheduler<F,T>(scheduler_ptr: *mut RawScheduler, f: F) -> T
    where F: FnOnce(&mut RawScheduler)->T {
  let mut scheduler = unsafe { Box::from_raw(scheduler_ptr) };
  let t = f(&mut scheduler);
  std::mem::forget(scheduler);
  t
}

fn with_vec<F,C,T>(c_ptr: *mut C, c_len: usize, f: F) -> T
    where F: FnOnce(&Vec<C>)->T {
  let cs = unsafe { Vec::from_raw_parts(c_ptr, c_len, c_len) };
  let output = f(&cs);
  std::mem::forget(cs);
  output
}
