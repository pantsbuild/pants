mod core;
mod execution;
mod graph;
mod nodes;
mod selectors;
mod tasks;

use core::Key;
use nodes::{Complete, Runnable};
use graph::{Graph, EntryId};
use tasks::{Tasks, TasksBuilder};
use execution::Execution;

/**
 * A wrapper around Execution that exposes raw pointers for consumption by the caller.
 */
struct RawExecution<'e> {
  ready_ptr: *mut EntryId,
  ready_runnables_ptr: *mut Runnable,
  ready_len: u64,
  ready: Vec<EntryId>,
  ready_runnables: Vec<Runnable>,
  execution: Execution<'e, 'e>,
}

impl<'e,> RawExecution<'e> {
  fn new(execution: Execution<'e,'e>) -> RawExecution<'e> {
    let mut raw =
      RawExecution {
        ready_ptr: Vec::new().as_mut_ptr(),
        ready_runnables_ptr: Vec::new().as_mut_ptr(),
        ready_len: 0,
        ready: Vec::new(),
        ready_runnables: Vec::new(),
        execution: execution,
      };

    // Yay, raw pointers! These would immediately be dangling if we didn't update them.
    raw.ready_ptr = raw.ready.as_mut_ptr();
    raw.ready_runnables_ptr = raw.ready_runnables.as_mut_ptr();
    raw
  }
}

#[no_mangle]
pub extern fn graph_create() -> *const Graph {
  // allocate on the heap via `Box` and return a raw pointer to the boxed value.
  Box::into_raw(Box::new(Graph::new()))
}

#[no_mangle]
pub extern fn graph_destroy(graph_ptr: *mut Graph) {
  // convert the raw pointer back to a Box (without `forget`ing it) in order to cause it
  // to be destroyed at the end of this function.
  let _ = unsafe { Box::from_raw(graph_ptr) };
}

#[no_mangle]
pub extern fn len(graph_ptr: *mut Graph) -> u64 {
  with_graph(graph_ptr, |graph| {
    graph.len() as u64
  })
}

#[no_mangle]
pub extern fn execution_create<'e>(
  graph_ptr: *mut Graph,
  tasks_ptr: *mut Tasks
) -> *const RawExecution<'e> {
  with_graph(graph_ptr, |graph| {
    with_tasks(tasks_ptr, |tasks| {
      let execution = Execution::new(graph, tasks);
      // create on the heap, and return a raw pointer to the boxed value.
      let boxed = Box::into_raw(Box::new(RawExecution::new(execution)));
      std::mem::forget(execution);
      boxed
    })
  })
}

#[no_mangle]
pub extern fn execution_next(
  execution_ptr: *mut RawExecution,
  completed_ptr: *mut EntryId,
  completed_states_ptr: *mut Complete,
  completed_len: u64,
) {
  with_execution(execution_ptr, |raw| {
    with_vec(completed_ptr, completed_len as usize, |completed_ids| {
      with_vec(completed_states_ptr, completed_len as usize, |completed_states| {
        let completed =
          completed_ids.iter().zip(completed_states.iter())
            .collect();

        // Execute steps and collect ready values.
        let (ready, ready_runnables) =
          raw.execution.next(completed).into_iter().unzip();

        // Store vectors of ready entries, and raw pointers to them.
        raw.ready = ready;
        raw.ready_runnables = ready_runnables;
        raw.ready_ptr = raw.ready.as_mut_ptr();
        raw.ready_runnables_ptr = raw.ready_runnables.as_mut_ptr();
        raw.ready_len = raw.ready.len() as u64;
      })
    })
  })
}

#[no_mangle]
pub extern fn execution_destroy(execution_ptr: *mut RawExecution) {
  // convert the raw pointers back to Boxes (without `forget`ing them) in order to cause them
  // to be destroyed at the end of this function.
  unsafe {
    let _ = Box::from_raw(execution_ptr);
  };
}

fn with_execution<F,T>(execution_ptr: *mut RawExecution, mut f: F) -> T
    where F: FnMut(&mut RawExecution)->T {
  let mut execution = unsafe { Box::from_raw(execution_ptr) };
  let t = f(&mut execution);
  std::mem::forget(execution);
  t
}

fn with_graph<F,T>(graph_ptr: *mut Graph, f: F) -> T
    where F: FnMut(&mut Graph)->T {
  let mut graph = unsafe { Box::from_raw(graph_ptr) };
  let t = f(&mut graph);
  std::mem::forget(graph);
  t
}

fn with_tasks<F,T>(tasks_ptr: *mut Tasks, f: F) -> T
    where F: FnMut(&mut Tasks)->T {
  let mut tasks = unsafe { Box::from_raw(tasks_ptr) };
  let t = f(&mut tasks);
  std::mem::forget(tasks);
  t
}

fn with_vec<F,C,T>(c_ptr: *mut C, c_len: usize, mut f: F) -> T
    where F: FnMut(&Vec<C>)->T {
  let cs = unsafe { Vec::from_raw_parts(c_ptr, c_len, c_len) };
  let output = f(&cs);
  std::mem::forget(cs);
  output
}
