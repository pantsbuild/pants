mod core;
mod scheduler;
mod graph;
mod nodes;
mod selectors;
mod tasks;

use core::{Field, Key, TypeId};
use nodes::{Complete, Runnable};
use graph::{Graph, EntryId};
use tasks::Tasks;
use scheduler::Scheduler;

pub struct RawScheduler {
  execution: RawExecution,
  scheduler: Scheduler,
}

impl RawScheduler {
  fn next(&mut self, completed: Vec<(&EntryId, &Complete)>) {
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
            func: runnable.func() as *const Key,
            args_ptr: runnable.args().as_ptr(),
            args_len: runnable.args().len() as u64,
          }
        })
        .collect();

    self.ready_ptr = self.ready.as_mut_ptr();
    self.runnables_ptr = self.raw_runnables.as_mut_ptr();
    self.len = self.ready.len() as u64;
  }
}

pub struct RawRunnable {
  // Single Key.
  func: *const Key,
  // Array of args.
  args_ptr: *const Key,
  args_len: u64,
}

#[no_mangle]
pub extern fn scheduler_create(
  key_none: *mut Key,
  field_name: *mut Field,
  field_products: *mut Field,
  field_variants: *mut Field,
  type_address: TypeId,
  type_has_products: TypeId,
  type_has_variants: TypeId,
) -> *const RawScheduler {
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  Box::into_raw(
    Box::new(
      RawScheduler {
        execution: RawExecution::new(),
        scheduler: Scheduler::new(
          Graph::new(),
          Tasks::new(
            key_from_raw(key_none),
            key_from_raw(field_name),
            key_from_raw(field_products),
            key_from_raw(field_variants),
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
  subject: *mut Key,
  product: TypeId,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.add_root_select(key_from_raw(subject), product);
  })
}

#[no_mangle]
pub extern fn execution_next(
  scheduler_ptr: *mut RawScheduler,
  completed_ptr: *mut EntryId,
  completed_states_ptr: *mut Complete,
  completed_len: u64,
) {
  with_scheduler(scheduler_ptr, |raw| {
    with_vec(completed_ptr, completed_len as usize, |completed_ids| {
      with_vec(completed_states_ptr, completed_len as usize, |completed_states| {
        raw.next(completed_ids.iter().zip(completed_states.iter()).collect());
      })
    })
  })
}

#[no_mangle]
pub extern fn task_gen(
  scheduler_ptr: *mut RawScheduler,
  func: *mut Key,
  output_type: TypeId,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.task_gen(key_from_raw(func), output_type);
  })
}

#[no_mangle]
pub extern fn task_add_select_literal(
  scheduler_ptr: *mut RawScheduler,
  subject: *mut Key,
  product: TypeId,
) {
  with_scheduler(scheduler_ptr, |raw| {
    raw.scheduler.tasks.add_select_literal(key_from_raw(subject), product);
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

fn with_scheduler<F,T>(scheduler_ptr: *mut RawScheduler, mut f: F) -> T
    where F: FnMut(&mut RawScheduler)->T {
  let mut scheduler = unsafe { Box::from_raw(scheduler_ptr) };
  let t = f(&mut scheduler);
  std::mem::forget(scheduler);
  t
}

fn with_vec<F,C,T>(c_ptr: *mut C, c_len: usize, mut f: F) -> T
    where F: FnMut(&Vec<C>)->T {
  let cs = unsafe { Vec::from_raw_parts(c_ptr, c_len, c_len) };
  let output = f(&cs);
  std::mem::forget(cs);
  output
}

/**
 * Clones the given key from a raw pointer.
 */
fn key_from_raw(k_ptr: *mut Key) -> Key {
  let key = unsafe { Box::from_raw(k_ptr) };
  let owned_key = (*key).clone();
  // We don't own this heap allocation: forget about it.
  std::mem::forget(key);
  owned_key
}
