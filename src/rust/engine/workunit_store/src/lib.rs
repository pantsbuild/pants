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
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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
pub use log::Level;
use log::{info, log};
use parking_lot::Mutex;
use petgraph::graph::{DiGraph, NodeIndex};
use rand::thread_rng;
use rand::Rng;
use std::collections::{BinaryHeap, HashMap};
use tokio::task_local;

use std::cell::RefCell;
use std::future::Future;
use std::sync::Arc;
use std::time::{Duration, SystemTime};

pub type SpanId = String;

type WorkunitGraph = DiGraph<SpanId, (), u32>;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Workunit {
  pub name: String,
  pub span_id: SpanId,
  pub parent_id: Option<String>,
  pub state: WorkunitState,
  pub metadata: WorkunitMetadata,
}

impl Workunit {
  fn log_workunit_state(&self) {
    let state = match self.state {
      WorkunitState::Started { .. } => "Starting:",
      WorkunitState::Completed { .. } => "Completed:",
    };

    let level = self.metadata.level;
    let identifier = if let Some(ref s) = self.metadata.desc {
      s.as_str()
    } else {
      self.name.as_str()
    };

    /* This length calculation doesn't treat multi-byte unicode charcters identically
     * to single-byte ones for the purpose of figuring out where to truncate the string. But that's
     * ok, since we just want to truncate the log string if it's roughly "too long", we don't care
     * exactly what the max_len is or whether it effectively changes slightly if there are
     * multibyte unicode characters in the string
     */
    let max_len = 200;
    if identifier.len() > max_len {
      let truncated_identifier: String = identifier.chars().take(max_len).collect();
      let trunc = identifier.len() - max_len;
      log!(
        level,
        "{} {}... ({} characters truncated)",
        state,
        truncated_identifier,
        trunc
      );
    } else {
      log!(level, "{} {}", state, identifier);
    }
  }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum WorkunitState {
  Started { start_time: SystemTime },
  Completed { time_span: TimeSpan },
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct WorkunitMetadata {
  pub desc: Option<String>,
  pub level: Level,
  pub blocked: bool,
  pub stdout: Option<hashing::Digest>,
  pub stderr: Option<hashing::Digest>,
}

impl WorkunitMetadata {
  pub fn new() -> Self {
    WorkunitMetadata::default()
  }

  pub fn with_level(level: Level) -> Self {
    let mut metadata = WorkunitMetadata::default();
    metadata.level = level;
    metadata
  }
}

impl Default for WorkunitMetadata {
  fn default() -> Self {
    Self {
      level: Level::Info,
      desc: None,
      blocked: false,
      stdout: None,
      stderr: None,
    }
  }
}

#[derive(Clone, Default)]
pub struct WorkunitStore {
  rendering_dynamic_ui: bool,
  inner: Arc<Mutex<WorkUnitInnerStore>>,
}

#[derive(Default)]
pub struct WorkUnitInnerStore {
  graph: WorkunitGraph,
  span_id_to_graph: HashMap<SpanId, NodeIndex<u32>>,
  workunit_records: HashMap<SpanId, Workunit>,
  started_ids: Vec<SpanId>,
  completed_ids: Vec<SpanId>,
  last_seen_started_idx: usize,
  last_seen_completed_idx: usize,
}

impl WorkUnitInnerStore {
  fn first_matched_parent(
    &self,
    mut span_id: Option<SpanId>,
    is_visible: impl Fn(&Workunit) -> bool,
  ) -> Option<SpanId> {
    while let Some(current_span_id) = span_id {
      let workunit = self.workunit_records.get(&current_span_id);

      // Is the current workunit visible?
      if let Some(ref workunit) = workunit {
        if is_visible(workunit) {
          return Some(current_span_id);
        }
      }

      // If not, try its parent.
      span_id = workunit.and_then(|workunit| workunit.parent_id.clone());
    }
    None
  }
}

impl WorkunitStore {
  pub fn new(rendering_dynamic_ui: bool) -> WorkunitStore {
    WorkunitStore {
      rendering_dynamic_ui,
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

  pub fn get_workunits(&self) -> Vec<Workunit> {
    let mut inner_guard = (*self.inner).lock();
    let inner_store: &mut WorkUnitInnerStore = &mut *inner_guard;
    let workunit_records = &inner_store.workunit_records;
    inner_store
      .completed_ids
      .iter()
      .flat_map(|id| workunit_records.get(id))
      .flat_map(|workunit| match workunit.state {
        WorkunitState::Started { .. } => None,
        WorkunitState::Completed { .. } => Some(workunit.clone()),
      })
      .collect()
  }

  ///
  /// Find the longest running leaf workunits, and render their first visible parents.
  ///
  pub fn heavy_hitters(&self, k: usize) -> HashMap<String, Option<Duration>> {
    use petgraph::Direction;

    let now = SystemTime::now();
    let inner = self.inner.lock();
    let workunit_graph = &inner.graph;

    let duration_for = |workunit: &Workunit| -> Option<Duration> {
      match workunit.state {
        WorkunitState::Started { ref start_time, .. } => now.duration_since(*start_time).ok(),
        _ => None,
      }
    };

    let is_visible = |workunit: &Workunit| -> bool {
      workunit.metadata.level >= Level::Info && workunit.metadata.desc.is_some()
    };

    // Initialize the heap with the leaves of the workunit graph.
    let mut queue: BinaryHeap<(Duration, SpanId)> = workunit_graph
      .externals(Direction::Outgoing)
      .map(|entry| workunit_graph[entry].clone())
      .flat_map(|span_id: SpanId| {
        let workunit: Option<&Workunit> = inner.workunit_records.get(&span_id);
        match workunit {
          Some(workunit) if !workunit.metadata.blocked => {
            duration_for(workunit).map(|d| (d, span_id.clone()))
          }
          _ => None,
        }
      })
      .collect();

    // Output the visible parents of the longest running leaves.
    let mut res = HashMap::new();
    while let Some((_dur, span_id)) = queue.pop() {
      // If the leaf is visible or has a visible parent, emit it.
      if let Some(span_id) = inner.first_matched_parent(Some(span_id), is_visible) {
        let workunit = inner.workunit_records.get(&span_id).unwrap();
        if let Some(effective_name) = workunit.metadata.desc.as_ref() {
          let maybe_duration = duration_for(&workunit);

          res.insert(effective_name.to_string(), maybe_duration);
          if res.len() >= k {
            break;
          }
        }
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
    let started = Workunit {
      name,
      span_id: span_id.clone(),
      parent_id: parent_id.clone(),
      state: WorkunitState::Started {
        start_time: std::time::SystemTime::now(),
      },
      metadata,
    };
    let mut inner = self.inner.lock();
    if !self.rendering_dynamic_ui {
      started.log_workunit_state()
    }

    inner.workunit_records.insert(span_id.clone(), started);
    inner.started_ids.push(span_id.clone());
    let child = inner.graph.add_node(span_id.clone());
    inner.span_id_to_graph.insert(span_id.clone(), child);
    if let Some(parent_id) = parent_id {
      if let Some(parent) = inner.span_id_to_graph.get(&parent_id).cloned() {
        inner.graph.add_edge(parent, child, ());
      }
    }

    span_id
  }

  pub fn complete_workunit_with_new_metadata(
    &self,
    span_id: SpanId,
    metadata: WorkunitMetadata,
  ) -> Result<(), String> {
    self.complete_workunit_impl(span_id, Some(metadata))
  }

  pub fn complete_workunit(&self, span_id: SpanId) -> Result<(), String> {
    self.complete_workunit_impl(span_id, None)
  }

  fn complete_workunit_impl(
    &self,
    span_id: SpanId,
    new_metadata: Option<WorkunitMetadata>,
  ) -> Result<(), String> {
    use std::collections::hash_map::Entry;
    let inner = &mut self.inner.lock();
    match inner.workunit_records.entry(span_id.clone()) {
      Entry::Vacant(_) => Err(format!(
        "No previously-started workunit found for id: {}",
        span_id
      )),
      Entry::Occupied(o) => {
        let (span_id, mut workunit) = o.remove_entry();
        let time_span = match workunit.state {
          WorkunitState::Completed { .. } => {
            return Err(format!("Workunit {} was already completed", span_id))
          }
          WorkunitState::Started { start_time } => TimeSpan::since(&start_time),
        };
        let new_state = WorkunitState::Completed { time_span };
        workunit.state = new_state;
        if let Some(metadata) = new_metadata {
          workunit.metadata = metadata;
        }
        workunit.log_workunit_state();
        inner.workunit_records.insert(span_id.clone(), workunit);
        inner.completed_ids.push(span_id);
        Ok(())
      }
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
    let workunit = Workunit {
      name,
      span_id: span_id.clone(),
      parent_id,
      state: WorkunitState::Completed { time_span },
      metadata,
    };

    inner.workunit_records.insert(span_id.clone(), workunit);
    inner.completed_ids.push(span_id);
  }

  pub fn with_latest_workunits<F, T>(&mut self, max_verbosity: log::Level, f: F) -> T
  where
    F: FnOnce(&[Workunit], &[Workunit]) -> T,
  {
    let mut inner_store = self.inner.lock();

    let should_emit = |workunit: &Workunit| -> bool { workunit.metadata.level <= max_verbosity };

    let cur_len = inner_store.started_ids.len();
    let latest: usize = inner_store.last_seen_started_idx;
    let started_workunits: Vec<Workunit> = inner_store.started_ids[latest..cur_len]
      .iter()
      .flat_map(|id| inner_store.workunit_records.get(id))
      .flat_map(|workunit| match workunit.state {
        WorkunitState::Started { .. } if should_emit(&workunit) => Some(workunit.clone()),
        WorkunitState::Started { .. } => None,
        WorkunitState::Completed { .. } => None,
      })
      .map(|mut w| {
        w.parent_id = inner_store.first_matched_parent(w.parent_id, should_emit);
        w
      })
      .collect();
    inner_store.last_seen_started_idx = cur_len;

    let completed_ids = &inner_store.completed_ids;
    let cur_len = completed_ids.len();
    let latest: usize = inner_store.last_seen_completed_idx;
    let completed_workunits: Vec<Workunit> = inner_store.completed_ids[latest..cur_len]
      .iter()
      .flat_map(|id| inner_store.workunit_records.get(id))
      .flat_map(|workunit| match workunit.state {
        WorkunitState::Completed { .. } if should_emit(&workunit) => Some(workunit.clone()),
        WorkunitState::Completed { .. } => None,
        WorkunitState::Started { .. } => None,
      })
      .map(|mut w| {
        w.parent_id = inner_store.first_matched_parent(w.parent_id, should_emit);
        w
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
  pub store: WorkunitStore,
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
  get_workunit_state().expect("A WorkunitStore has not been set for this thread.")
}

pub async fn with_workunit<F, M>(
  workunit_store: WorkunitStore,
  name: String,
  initial_metadata: WorkunitMetadata,
  f: F,
  final_metadata_fn: M,
) -> F::Output
where
  F: Future,
  M: for<'a> FnOnce(&'a F::Output, WorkunitMetadata) -> WorkunitMetadata,
{
  let mut workunit_state = expect_workunit_state();
  let span_id = new_span_id();
  let parent_id = std::mem::replace(&mut workunit_state.parent_id, Some(span_id.clone()));
  let started_id =
    workunit_store.start_workunit(span_id, name, parent_id, initial_metadata.clone());
  scope_task_workunit_state(Some(workunit_state), async move {
    let result = f.await;
    let final_metadata = final_metadata_fn(&result, initial_metadata);
    if let Err(e) = workunit_store.complete_workunit_with_new_metadata(started_id, final_metadata) {
      info!("{}", e);
    }
    result
  })
  .await
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
