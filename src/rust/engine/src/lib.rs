mod core;
mod scheduler;
mod graph;
mod nodes;
mod selectors;
mod tasks;

use std::ops::{Deref, DerefMut};

use core::{Field, Key, TypeId};
use nodes::{Complete, Runnable};
use graph::{Graph, EntryId};
use tasks::Tasks;
use scheduler::Scheduler;

pub struct RawScheduler {
  raw: RawExecution,
  scheduler: Scheduler,
}

pub struct RawExecution {
  ready_ptr: *mut EntryId,
  ready_runnables_ptr: *mut Runnable,
  ready_len: u64,
  ready: Vec<EntryId>,
  ready_runnables: Vec<Runnable>,
}

impl RawExecution {
  fn new() -> RawExecution {
    let mut raw =
      RawExecution {
        ready_ptr: Vec::new().as_mut_ptr(),
        ready_runnables_ptr: Vec::new().as_mut_ptr(),
        ready_len: 0,
        ready: Vec::new(),
        ready_runnables: Vec::new(),
      };

    // Yay, raw pointers! These would immediately be dangling if we didn't update them.
    raw.ready_ptr = raw.ready.as_mut_ptr();
    raw.ready_runnables_ptr = raw.ready_runnables.as_mut_ptr();
    raw
  }
}

#[no_mangle]
pub extern fn scheduler_create<'e>(
  key_none: *mut Key,
  field_name: *mut Field,
  field_products: *mut Field,
  field_variants: *mut Field,
  type_address: TypeId,
  type_has_products: TypeId,
  type_has_variants: TypeId,
) -> *const Scheduler {
  // Allocate on the heap via `Box` and return a raw pointer to the boxed value.
  Box::into_raw(
    Box::new(
      Scheduler {
        raw: RawExecution::new(),
        execution: None,
        graph: Graph::new(),
        tasks: Tasks::new(
          key_from_raw(key_none),
          key_from_raw(field_name),
          key_from_raw(field_products),
          key_from_raw(field_variants),
          type_address,
          type_has_products,
          type_has_variants,
        ),
      }
    )
  )
}

#[no_mangle]
pub extern fn scheduler_destroy(scheduler_ptr: *mut Scheduler) {
  // convert the raw pointer back to a Box (without `forget`ing it) in order to cause it
  // to be destroyed at the end of this function.
  let _ = unsafe { Box::from_raw(scheduler_ptr) };
}

#[no_mangle]
pub extern fn graph_len(scheduler_ptr: *mut Scheduler) -> u64 {
  with_scheduler(scheduler_ptr, |scheduler| {
    scheduler.graph.len() as u64
  })
}

#[no_mangle]
pub extern fn execution_next(
  scheduler_ptr: *mut Scheduler,
  completed_ptr: *mut EntryId,
  completed_states_ptr: *mut Complete,
  completed_len: u64,
) {
  with_scheduler(scheduler_ptr, |scheduler| {
    with_vec(completed_ptr, completed_len as usize, |completed_ids| {
      with_vec(completed_states_ptr, completed_len as usize, |completed_states| {
        // Execute steps and collect ready values.
        let completed = completed_ids.iter().zip(completed_states.iter()).collect();
        let (ready, ready_runnables) =
          scheduler.execution.as_mut().map(|execution|{
            execution.next(completed)
          })
          .unwrap_or(Vec::new())
          .into_iter()
          .unzip();

        // Store vectors of ready entries, and raw pointers to them.
        scheduler.raw.ready = ready;
        scheduler.raw.ready_runnables = ready_runnables;
        scheduler.raw.ready_ptr = scheduler.raw.ready.as_mut_ptr();
        scheduler.raw.ready_runnables_ptr = scheduler.raw.ready_runnables.as_mut_ptr();
        scheduler.raw.ready_len = scheduler.raw.ready.len() as u64;
      })
    })
  })
}

fn with_scheduler<F,T>(scheduler_ptr: *mut Scheduler, mut f: F) -> T
    where F: FnMut(&mut Scheduler)->T {
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
