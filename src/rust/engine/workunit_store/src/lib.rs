// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
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

use concrete_time::TimeSpan;
use parking_lot::Mutex;
use rand::thread_rng;
use rand::Rng;
use std::collections::{BinaryHeap, HashMap};
use tokio::task_local;
use graph::EntryId;
use petgraph::graph::{DiGraph, NodeIndex};

use std::cell::RefCell;
use std::future::Future;
use std::sync::Arc;
use std::time::{Duration, SystemTime};

pub type SpanId = String;

type WorkunitGraph = DiGraph<SpanId, (), u32>;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct WorkUnit {
  pub name: String,
  pub time_span: TimeSpan,
  pub span_id: SpanId,
  pub parent_id: Option<String>,
  pub metadata: WorkunitMetadata,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct StartedWorkUnit {
  pub name: String,
  pub start_time: SystemTime,
  pub span_id: SpanId,
  pub parent_id: Option<String>,
  pub metadata: WorkunitMetadata,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct WorkunitMetadata {
  pub desc: Option<String>,
  pub display: bool,
  pub entry_id: Option<EntryId>,
  pub waiting: bool
}

impl WorkunitMetadata {
  pub fn new() -> WorkunitMetadata {
    WorkunitMetadata {
      display: true,
      desc: None,
      entry_id: None,
      waiting: false,
    }
  }
}

impl StartedWorkUnit {
  fn finish(self) -> WorkUnit {
    WorkUnit {
      name: self.name,
      time_span: TimeSpan::since(&self.start_time),
      span_id: self.span_id,
      parent_id: self.parent_id,
      metadata: self.metadata,
    }
  }
}

impl WorkUnit {
  pub fn new(name: String, time_span: TimeSpan, parent_id: Option<String>) -> WorkUnit {
    let span_id = new_span_id();
    WorkUnit {
      name,
      time_span,
      span_id,
      parent_id,
      metadata: WorkunitMetadata::new(),
    }
  }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
enum WorkunitRecord {
  Started(StartedWorkUnit),
  Completed(WorkUnit),
}

#[derive(Clone, Default)]
pub struct WorkUnitStore {
  inner: Arc<Mutex<WorkUnitInnerStore>>,
}

#[derive(Default)]
pub struct WorkUnitInnerStore {
  graph: WorkunitGraph,
  span_id_to_graph: HashMap<SpanId, NodeIndex<u32>>,
  workunit_records: HashMap<SpanId, WorkunitRecord>,
  started_ids: Vec<SpanId>,
  completed_ids: Vec<SpanId>,
  last_seen_started_idx: usize,
  last_seen_completed_idx: usize,
}

impl WorkUnitStore {
  pub fn new() -> WorkUnitStore {
    WorkUnitStore {
      inner: Arc::new(Mutex::new(WorkUnitInnerStore {
        graph: DiGraph::new(),
        span_id_to_graph: HashMap::new(),
        workunit_records: HashMap::new(),
        started_ids: Vec::new(),
        last_seen_started_idx: 0,
        completed_ids: Vec::new(),
        last_seen_completed_idx: 0,
      })),
    }
  }

  pub fn init_thread_state(&self, parent_id: Option<String>) {
    set_thread_workunit_state(Some(WorkUnitState {
      store: self.clone(),
      parent_id,
    }))
  }

  pub fn get_workunits(&self) -> Vec<WorkUnit> {
    let mut inner_guard = (*self.inner).lock();
    let inner_store: &mut WorkUnitInnerStore = &mut *inner_guard;
    let workunit_records = &inner_store.workunit_records;
    inner_store
      .completed_ids
      .iter()
      .flat_map(|id| workunit_records.get(id))
      .flat_map(|record| match record {
        WorkunitRecord::Started(_) => None,
        WorkunitRecord::Completed(c) => Some(c.clone()),
      })
      .collect()
  }

  pub fn heavy_hitters(&self, k: usize) -> HashMap<String, Duration> {
    use petgraph::Direction;

    let now = SystemTime::now();
    let inner = self.inner.lock();
    let workunit_graph = &inner.graph;

    let mut queue: BinaryHeap<(Duration, SpanId)> = BinaryHeap::with_capacity(k);
    let edge_workunits = workunit_graph.externals(Direction::Outgoing);
    queue.extend(edge_workunits
      .map(|entry| workunit_graph[entry].clone())
      .flat_map(|span_id: SpanId| {
        let record = inner.workunit_records.get(&span_id);
        match record {
          Some(WorkunitRecord::Started(StartedWorkUnit { start_time, .. })) => {
            now.duration_since(*start_time).ok()
              .map(|duration| (duration, span_id))
          },
          _ => None
        }
      })
    );

    let mut res = HashMap::new();
    loop {
      if let Some((dur, span_id)) = queue.pop() {
        let record = inner.workunit_records.get(&span_id).unwrap();
        let name = match record {
          WorkunitRecord::Started(StartedWorkUnit { name, .. }) => name.clone(),
          WorkunitRecord::Completed(WorkUnit { name, .. }) => name.clone(),
        };
        res.insert(name, dur);
        if res.len() >= k {
          break;
        }
      } else {
        break;
      }
    }
    res
  }

  pub fn start_workunit(
    &self,
    span_id: SpanId,
    name: String,
    parent_id: Option<SpanId>,
    metadata: WorkunitMetadata,
  ) -> SpanId {
    let started = StartedWorkUnit {
      name,
      span_id: span_id.clone(),
      parent_id: parent_id.clone(),
      start_time: std::time::SystemTime::now(),
      metadata,
    };
    let mut inner = self.inner.lock();
    inner
      .workunit_records
      .insert(span_id.clone(), WorkunitRecord::Started(started));
    inner.started_ids.push(span_id.clone());
    let child = inner.graph.add_node(span_id.clone());
    inner.span_id_to_graph.insert(span_id.clone(), child.clone());
    if let Some(parent_id) = parent_id {
      let parent = inner.span_id_to_graph.get(&parent_id).unwrap().clone();
      inner.graph.add_edge(parent, child, ());
    }

    span_id
  }

  pub fn complete_workunit(&self, span_id: SpanId) -> Result<(), String> {
    use std::collections::hash_map::Entry;
    let inner = &mut self.inner.lock();
    match inner.workunit_records.entry(span_id.clone()) {
      Entry::Vacant(_) => Err(format!(
        "No previously-started workunit found for id: {}",
        span_id
      )),
      Entry::Occupied(o) => match o.remove_entry() {
        (span_id, WorkunitRecord::Started(started)) => {
          let finished = started.finish();
          inner
            .workunit_records
            .insert(span_id.clone(), WorkunitRecord::Completed(finished));
          inner.completed_ids.push(span_id);
          Ok(())
        }
        (span_id, WorkunitRecord::Completed(_)) => {
          Err(format!("Workunit {} was already completed.", span_id))
        }
      },
    }
  }

  pub fn add_completed_workunit(
    &self,
    name: String,
    time_span: TimeSpan,
    parent_id: Option<SpanId>,
    metadata: WorkunitMetadata,
  ) {
    let inner = &mut self.inner.lock();
    let span_id = new_span_id();
    let workunit = WorkunitRecord::Completed(WorkUnit {
      name,
      time_span,
      span_id: span_id.clone(),
      parent_id,
      metadata,
    });

    inner.workunit_records.insert(span_id.clone(), workunit);
    inner.completed_ids.push(span_id);
  }

  pub fn with_latest_workunits<F, T>(&mut self, f: F) -> T
  where
    F: FnOnce(&[StartedWorkUnit], &[WorkUnit]) -> T,
  {
    let mut inner_guard = (*self.inner).lock();
    let inner_store: &mut WorkUnitInnerStore = &mut *inner_guard;

    let workunit_records = &inner_store.workunit_records;

    let cur_len = inner_store.started_ids.len();
    let latest: usize = inner_store.last_seen_started_idx;
    let started_workunits: Vec<StartedWorkUnit> = inner_store.started_ids[latest..cur_len]
      .iter()
      .flat_map(|id| workunit_records.get(id))
      .flat_map(|record| match record {
        WorkunitRecord::Completed(_) => None,
        WorkunitRecord::Started(c) => Some(c.clone()),
      })
      .collect();
    inner_store.last_seen_started_idx = cur_len;

    let completed_ids = &inner_store.completed_ids;
    let cur_len = completed_ids.len();
    let latest: usize = inner_store.last_seen_completed_idx;
    let completed_workunits: Vec<WorkUnit> = inner_store.completed_ids[latest..cur_len]
      .iter()
      .flat_map(|id| workunit_records.get(id))
      .flat_map(|record| match record {
        WorkunitRecord::Started(_) => None,
        WorkunitRecord::Completed(c) => Some(c.clone()),
      })
      .collect();
    inner_store.last_seen_completed_idx = cur_len;

    f(&started_workunits, &completed_workunits)
  }
}

pub fn new_span_id() -> String {
  let mut rng = thread_rng();
  let random_u64: u64 = rng.gen();
  hex_16_digit_string(random_u64)
}

fn hex_16_digit_string(number: u64) -> String {
  format!("{:016.x}", number)
}

///
/// The per-thread/task state that tracks the current workunit store, and workunit parent id.
///
#[derive(Clone)]
pub struct WorkUnitState {
  pub store: WorkUnitStore,
  pub parent_id: Option<String>,
}

thread_local! {
  static THREAD_WORKUNIT_STATE: RefCell<Option<WorkUnitState>> = RefCell::new(None)
}

task_local! {
  static TASK_WORKUNIT_STATE: Option<WorkUnitState>;
}

///
/// Set the current parent_id for a Thread, but _not_ for a Task. Tasks must always be spawned
/// by callers using the `scope_task_workunit_state` helper (generally via task_executor::Executor.)
///
pub fn set_thread_workunit_state(workunit_state: Option<WorkUnitState>) {
  THREAD_WORKUNIT_STATE.with(|thread_workunit_state| {
    *thread_workunit_state.borrow_mut() = workunit_state;
  })
}

pub fn get_workunit_state() -> Option<WorkUnitState> {
  if let Ok(Some(workunit_state)) =
    TASK_WORKUNIT_STATE.try_with(|workunit_state| workunit_state.clone())
  {
    Some(workunit_state)
  } else {
    THREAD_WORKUNIT_STATE.with(|thread_workunit_state| (*thread_workunit_state.borrow()).clone())
  }
}

pub fn expect_workunit_state() -> WorkUnitState {
  get_workunit_state().expect("A WorkUnitStore has not been set for this thread.")
}

pub async fn with_workunit<F>(workunit_store: WorkUnitStore, name: String, metadata: WorkunitMetadata, f: F) -> F::Output
where F: Future {
  let mut workunit_state = expect_workunit_state();
  let span_id = new_span_id();
  let parent_id = std::mem::replace(&mut workunit_state.parent_id, Some(span_id.clone()));
  let started_id = workunit_store.start_workunit(span_id, name, parent_id, metadata);
  scope_task_workunit_state(Some(workunit_state), async move {
    let result = f.await;
    workunit_store
      .complete_workunit(started_id)
      .unwrap();
    result
  }).await
}

///
/// Propagate the given WorkUnitState to a Future representing a newly spawned Task.
///
pub async fn scope_task_workunit_state<F>(workunit_state: Option<WorkUnitState>, f: F) -> F::Output
where
  F: Future,
{
  TASK_WORKUNIT_STATE.scope(workunit_state, f).await
}

#[cfg(test)]
mod tests;
