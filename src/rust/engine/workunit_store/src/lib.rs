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
use log::log;
pub use log::Level;
use parking_lot::Mutex;
use petgraph::graph::{DiGraph, NodeIndex};
use rand::thread_rng;
use rand::Rng;
use std::collections::{BinaryHeap, HashMap};
use std::sync::mpsc::{channel, Receiver, Sender};
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
    let effective_identifier = if identifier.len() > max_len {
      let truncated_identifier: String = identifier.chars().take(max_len).collect();
      let trunc = identifier.len() - max_len;
      format!(
        "{}... ({} characters truncated)",
        truncated_identifier, trunc
      )
    } else {
      identifier.to_string()
    };

    let message = if let Some(ref s) = self.metadata.message {
      format!(" - {}", s)
    } else {
      "".to_string()
    };

    log!(level, "{} {}{}", state, effective_identifier, message);
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
  pub message: Option<String>,
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
      message: None,
      blocked: false,
      stdout: None,
      stderr: None,
    }
  }
}

type CompletedWorkunitReceiver =
  Arc<Mutex<Receiver<(SpanId, Option<WorkunitMetadata>, SystemTime)>>>;
type CompletedWorkunitSender = Arc<Mutex<Sender<(SpanId, Option<WorkunitMetadata>, SystemTime)>>>;

#[derive(Clone)]
pub struct WorkunitStore {
  rendering_dynamic_ui: bool,
  streaming_workunit_data: StreamingWorkunitData,
  heavy_hitters_data: HeavyHittersData,
}

#[derive(Clone)]
struct StreamingWorkunitData {
  started_workunits_rx: Arc<Mutex<Receiver<Workunit>>>,
  started_workunits_tx: Arc<Mutex<Sender<Workunit>>>,
  completed_workunits_rx: CompletedWorkunitReceiver,
  completed_workunits_tx: CompletedWorkunitSender,
  workunit_records: Arc<Mutex<HashMap<SpanId, Workunit>>>,
}

impl StreamingWorkunitData {
  fn new() -> StreamingWorkunitData {
    let (started_workunits_tx, started_workunits_rx) = channel();
    let (completed_workunits_tx, completed_workunits_rx) = channel();
    StreamingWorkunitData {
      started_workunits_tx: Arc::new(Mutex::new(started_workunits_tx)),
      started_workunits_rx: Arc::new(Mutex::new(started_workunits_rx)),
      completed_workunits_tx: Arc::new(Mutex::new(completed_workunits_tx)),
      completed_workunits_rx: Arc::new(Mutex::new(completed_workunits_rx)),
      workunit_records: Arc::new(Mutex::new(HashMap::new())),
    }
  }
}

#[derive(Clone)]
struct HeavyHittersData {
  inner: Arc<Mutex<WorkUnitInnerStore>>,
  started_workunits_rx: Arc<Mutex<Receiver<Workunit>>>,
  started_workunits_tx: Arc<Mutex<Sender<Workunit>>>,
  completed_workunits_rx: CompletedWorkunitReceiver,
  completed_workunits_tx: CompletedWorkunitSender,
}

impl HeavyHittersData {
  fn new() -> HeavyHittersData {
    let (started_workunits_tx, started_workunits_rx) = channel();
    let (completed_workunits_tx, completed_workunits_rx) = channel();
    HeavyHittersData {
      inner: Arc::new(Mutex::new(WorkUnitInnerStore {
        graph: DiGraph::new(),
        span_id_to_graph: HashMap::new(),
        workunit_records: HashMap::new(),
      })),
      started_workunits_rx: Arc::new(Mutex::new(started_workunits_rx)),
      started_workunits_tx: Arc::new(Mutex::new(started_workunits_tx)),
      completed_workunits_rx: Arc::new(Mutex::new(completed_workunits_rx)),
      completed_workunits_tx: Arc::new(Mutex::new(completed_workunits_tx)),
    }
  }
}

#[derive(Default)]
pub struct WorkUnitInnerStore {
  graph: WorkunitGraph,
  span_id_to_graph: HashMap<SpanId, NodeIndex<u32>>,
  workunit_records: HashMap<SpanId, Workunit>,
}

fn first_matched_parent(
  workunit_records: &HashMap<SpanId, Workunit>,
  mut span_id: Option<SpanId>,
  is_visible: impl Fn(&Workunit) -> bool,
) -> Option<SpanId> {
  while let Some(current_span_id) = span_id {
    let workunit = workunit_records.get(&current_span_id);

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
      streaming_workunit_data: StreamingWorkunitData::new(),
      heavy_hitters_data: HeavyHittersData::new(),
      rendering_dynamic_ui,
    }
  }

  pub fn init_thread_state(&self, parent_id: Option<String>) {
    set_thread_workunit_state(Some(WorkUnitState {
      store: self.clone(),
      parent_id,
    }))
  }

  ///
  /// Find the longest running leaf workunits, and render their first visible parents.
  ///
  pub fn heavy_hitters(&self, k: usize) -> HashMap<String, Option<Duration>> {
    use petgraph::Direction;
    let now = SystemTime::now();
    let mut inner = self.heavy_hitters_data.inner.lock();

    let receiver = self.heavy_hitters_data.started_workunits_rx.lock();

    while let Ok(started) = receiver.try_recv() {
      Self::add_started_workunit_to_store(started, &mut inner);
    }

    let receiver = self.heavy_hitters_data.completed_workunits_rx.lock();
    while let Ok((span_id, new_metadata, time)) = receiver.try_recv() {
      Self::add_completed_workunit_to_store(span_id, new_metadata, time, &mut inner);
    }

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
      parent_id,
      state: WorkunitState::Started {
        start_time: std::time::SystemTime::now(),
      },
      metadata,
    };
    if !self.rendering_dynamic_ui {
      started.log_workunit_state()
    }
    let sender = self.heavy_hitters_data.started_workunits_tx.lock();
    sender.send(started.clone()).unwrap();
    let sender = self.streaming_workunit_data.started_workunits_tx.lock();
    sender.send(started).unwrap();
    span_id
  }

  fn add_started_workunit_to_store(started: Workunit, inner_store: &mut WorkUnitInnerStore) {
    let span_id = started.span_id.clone();
    let parent_id = started.parent_id.clone();

    inner_store
      .workunit_records
      .insert(span_id.clone(), started);

    let child = inner_store.graph.add_node(span_id.clone());
    inner_store.span_id_to_graph.insert(span_id, child);
    if let Some(parent_id) = parent_id {
      if let Some(parent) = inner_store.span_id_to_graph.get(&parent_id).cloned() {
        inner_store.graph.add_edge(parent, child, ());
      }
    }
  }

  pub fn complete_workunit_with_new_metadata(&self, span_id: SpanId, metadata: WorkunitMetadata) {
    self.complete_workunit_impl(span_id, Some(metadata))
  }

  pub fn complete_workunit(&self, span_id: SpanId) {
    self.complete_workunit_impl(span_id, None)
  }

  fn complete_workunit_impl(&self, span_id: SpanId, new_metadata: Option<WorkunitMetadata>) {
    let time = std::time::SystemTime::now();
    let tx = self.heavy_hitters_data.completed_workunits_tx.lock();
    tx.send((span_id.clone(), new_metadata.clone(), time))
      .unwrap();

    let tx = self.streaming_workunit_data.completed_workunits_tx.lock();
    tx.send((span_id, new_metadata, time)).unwrap();
  }

  fn add_completed_workunit_to_store(
    span_id: SpanId,
    new_metadata: Option<WorkunitMetadata>,
    end_time: SystemTime,
    inner_store: &mut WorkUnitInnerStore,
  ) {
    use std::collections::hash_map::Entry;

    match inner_store.workunit_records.entry(span_id.clone()) {
      Entry::Vacant(_) => {
        log::warn!("No previously-started workunit found for id: {}", span_id);
      }
      Entry::Occupied(o) => {
        let (span_id, mut workunit) = o.remove_entry();
        let time_span = match workunit.state {
          WorkunitState::Completed { .. } => {
            log::warn!("Workunit {} was already completed", span_id);
            return;
          }
          WorkunitState::Started { start_time } => {
            TimeSpan::from_start_and_end_systemtime(&start_time, &end_time)
          }
        };
        let new_state = WorkunitState::Completed { time_span };
        workunit.state = new_state;
        if let Some(metadata) = new_metadata {
          workunit.metadata = metadata;
        }
        workunit.log_workunit_state();
        inner_store.workunit_records.insert(span_id, workunit);
      }
    }
  }

  pub fn add_completed_workunit(
    &self,
    name: String,
    start_time: SystemTime,
    end_time: SystemTime,
    parent_id: Option<SpanId>,
    metadata: WorkunitMetadata,
  ) {
    let span_id = new_span_id();

    let workunit = Workunit {
      name,
      span_id: span_id.clone(),
      parent_id,
      state: WorkunitState::Started { start_time },
      metadata,
    };

    let sender = self.heavy_hitters_data.started_workunits_tx.lock();
    sender.send(workunit.clone()).unwrap();
    let sender = self.streaming_workunit_data.started_workunits_tx.lock();
    sender.send(workunit).unwrap();

    let sender = self.heavy_hitters_data.completed_workunits_tx.lock();
    sender.send((span_id.clone(), None, end_time)).unwrap();
    let sender = self.streaming_workunit_data.completed_workunits_tx.lock();
    sender.send((span_id, None, end_time)).unwrap();
  }

  pub fn with_latest_workunits<F, T>(&mut self, max_verbosity: log::Level, f: F) -> T
  where
    F: FnOnce(&[Workunit], &[Workunit]) -> T,
  {
    use std::collections::hash_map::Entry;

    let should_emit = |workunit: &Workunit| -> bool { workunit.metadata.level <= max_verbosity };

    let (started_workunits, completed_workunits) = {
      let mut workunit_records = self.streaming_workunit_data.workunit_records.lock();

      let receiver = self.streaming_workunit_data.started_workunits_rx.lock();
      let mut started_workunits: Vec<Workunit> = vec![];
      while let Ok(mut started) = receiver.try_recv() {
        let span_id = started.span_id.clone();
        workunit_records.insert(span_id.clone(), started.clone());

        if should_emit(&started) {
          started.parent_id =
            first_matched_parent(&workunit_records, started.parent_id, should_emit);
          started_workunits.push(started);
        }
      }

      let receiver = self.streaming_workunit_data.completed_workunits_rx.lock();
      let mut completed_workunits: Vec<Workunit> = vec![];
      while let Ok((span_id, new_metadata, end_time)) = receiver.try_recv() {
        match workunit_records.entry(span_id.clone()) {
          Entry::Vacant(_) => {
            log::warn!("No previously-started workunit found for id: {}", span_id);
            continue;
          }
          Entry::Occupied(o) => {
            let (span_id, mut workunit) = o.remove_entry();
            let time_span = match workunit.state {
              WorkunitState::Completed { .. } => {
                log::warn!("Workunit {} was already completed", span_id);
                continue;
              }
              WorkunitState::Started { start_time } => {
                TimeSpan::from_start_and_end_systemtime(&start_time, &end_time)
              }
            };
            let new_state = WorkunitState::Completed { time_span };
            workunit.state = new_state;
            if let Some(metadata) = new_metadata {
              workunit.metadata = metadata;
            }
            workunit.log_workunit_state();
            workunit_records.insert(span_id.clone(), workunit.clone());

            if should_emit(&workunit) {
              workunit.parent_id =
                first_matched_parent(&workunit_records, workunit.parent_id, should_emit);
              completed_workunits.push(workunit);
            }
          }
        }
      }
      (started_workunits, completed_workunits)
    };

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
    workunit_store.complete_workunit_with_new_metadata(started_id, final_metadata);
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
