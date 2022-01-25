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

use std::cell::RefCell;
use std::collections::hash_map::Entry;
use std::collections::{BinaryHeap, HashMap};
use std::future::Future;
use std::sync::atomic::{self, AtomicBool};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::time::{Duration, SystemTime};

use bytes::{BufMut, Bytes, BytesMut};
use concrete_time::TimeSpan;
use hdrhistogram::serialization::Serializer;
use log::log;
pub use log::Level;
pub use metrics::{Metric, ObservationMetric};
use parking_lot::Mutex;
use petgraph::stable_graph::{NodeIndex, StableDiGraph};
use rand::thread_rng;
use rand::Rng;
use tokio::task_local;

mod metrics;

///
/// A unique id for a single run or `--loop` iteration of Pants within a single Scheduler.
///
/// RunIds are not comparable across Scheduler instances, and only equality is meaningful, not
/// ordering.
///
/// NB: This type is defined here to make it easily accessible to both the `process_execution`
/// and `engine` crates: it's not actually used by the WorkunitStore.
///
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RunId(pub u32);

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Ord, PartialOrd)]
pub struct SpanId(u64);

impl SpanId {
  pub fn new() -> SpanId {
    let mut rng = thread_rng();
    SpanId(rng.gen())
  }
}

impl std::fmt::Display for SpanId {
  fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
    write!(f, "{:016.x}", self.0)
  }
}

type RunningWorkunitGraph = StableDiGraph<SpanId, (), u32>;

///
/// Workunits form a tree of running, blocked, and completed work, with parent ids propagated via
/// thread-local state.
///
/// While running (the Started state), a copy of a Workunit is generally kept on the stack by the
/// `in_workunit!` macro, while another copy of the same Workunit is recorded in the WorkunitStore.
/// Most of the fields of the Workunit are immutable, but an atomic "blocked" flag can be set to
/// temporarily mark the running Workunit as being in a blocked state.
///
/// When the `in_workunit!` macro exits, the Workunit on the stack is completed by storing any
/// local mutated values as the final value of the Workunit.
///
#[derive(Clone, Debug)]
pub struct Workunit {
  pub name: String,
  pub span_id: SpanId,
  pub parent_id: Option<SpanId>,
  pub state: WorkunitState,
  pub metadata: WorkunitMetadata,
  pub counters: HashMap<Metric, u64>,
}

impl Workunit {
  fn log_workunit_state(&self, canceled: bool) {
    if !log::log_enabled!(self.metadata.level) {
      return;
    }
    let state = match (&self.state, canceled) {
      (_, true) => "Canceled:",
      (WorkunitState::Started { .. }, _) => "Starting:",
      (WorkunitState::Completed { .. }, _) => "Completed:",
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

#[derive(Clone, Debug)]
pub enum WorkunitState {
  Started {
    start_time: SystemTime,
    blocked: Arc<AtomicBool>,
  },
  Completed {
    time_span: TimeSpan,
  },
}

impl WorkunitState {
  fn completed(&self) -> bool {
    match self {
      WorkunitState::Completed { .. } => true,
      WorkunitState::Started { .. } => false,
    }
  }

  fn blocked(&self) -> bool {
    match self {
      WorkunitState::Started { blocked, .. } => blocked.load(atomic::Ordering::Relaxed),
      WorkunitState::Completed { .. } => false,
    }
  }
}

#[derive(Clone, Debug)]
pub enum ArtifactOutput {
  FileDigest(hashing::Digest),
  Snapshot(hashing::Digest),
}

#[derive(Clone, Debug)]
pub struct WorkunitMetadata {
  pub desc: Option<String>,
  pub message: Option<String>,
  pub level: Level,
  pub stdout: Option<hashing::Digest>,
  pub stderr: Option<hashing::Digest>,
  pub artifacts: Vec<(String, ArtifactOutput)>,
  pub user_metadata: Vec<(String, UserMetadataItem)>,
}

impl Default for WorkunitMetadata {
  fn default() -> WorkunitMetadata {
    WorkunitMetadata {
      level: Level::Info,
      desc: None,
      message: None,
      stdout: None,
      stderr: None,
      artifacts: Vec::new(),
      user_metadata: Vec::new(),
    }
  }
}

/// Abstract id for passing user metadata items around
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum UserMetadataItem {
  PyValue(UserMetadataPyValue),
  ImmediateInt(i64),
  ImmediateString(String),
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct UserMetadataPyValue(uuid::Uuid);

impl UserMetadataPyValue {
  pub fn new() -> UserMetadataPyValue {
    UserMetadataPyValue(uuid::Uuid::new_v4())
  }
}

enum StoreMsg {
  Started(Workunit),
  Completed(
    SpanId,
    Option<WorkunitMetadata>,
    SystemTime,
    HashMap<Metric, u64>,
  ),
  Canceled(SpanId),
}

#[derive(Clone)]
pub struct WorkunitStore {
  log_starting_workunits: bool,
  streaming_workunit_data: StreamingWorkunitData,
  heavy_hitters_data: HeavyHittersData,
  observation_data: ObservationsData,
}

#[derive(Clone)]
struct StreamingWorkunitData {
  msg_rx: Arc<Mutex<Receiver<StoreMsg>>>,
  msg_tx: Arc<Mutex<Sender<StoreMsg>>>,
  workunit_records: Arc<Mutex<HashMap<SpanId, Workunit>>>,
}

impl StreamingWorkunitData {
  fn new() -> StreamingWorkunitData {
    let (msg_tx, msg_rx) = channel();
    StreamingWorkunitData {
      msg_tx: Arc::new(Mutex::new(msg_tx)),
      msg_rx: Arc::new(Mutex::new(msg_rx)),
      workunit_records: Arc::new(Mutex::new(HashMap::new())),
    }
  }

  pub fn latest_workunits(&mut self, max_verbosity: log::Level) -> (Vec<Workunit>, Vec<Workunit>) {
    let should_emit = |workunit: &Workunit| -> bool { workunit.metadata.level <= max_verbosity };
    let mut started_messages = vec![];
    let mut completed_messages = vec![];

    {
      let receiver = self.msg_rx.lock();
      while let Ok(msg) = receiver.try_recv() {
        match msg {
          StoreMsg::Started(started) => started_messages.push(started),
          StoreMsg::Completed(span, metadata, time, new_counters) => {
            completed_messages.push((span, metadata, time, new_counters))
          }
          StoreMsg::Canceled(..) => (),
        }
      }
    }

    let mut workunit_records = self.workunit_records.lock();
    let mut started_workunits: Vec<Workunit> = vec![];
    for mut started in started_messages.into_iter() {
      let span_id = started.span_id;
      workunit_records.insert(span_id, started.clone());

      if should_emit(&started) {
        started.parent_id =
          first_matched_parent(&workunit_records, started.parent_id, |_| false, should_emit);
        started_workunits.push(started);
      }
    }

    let mut completed_workunits: Vec<Workunit> = vec![];
    for (span_id, new_metadata, end_time, new_counters) in completed_messages.into_iter() {
      match workunit_records.entry(span_id) {
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
            WorkunitState::Started { start_time, .. } => {
              TimeSpan::from_start_and_end_systemtime(&start_time, &end_time)
            }
          };
          let new_state = WorkunitState::Completed { time_span };
          workunit.state = new_state;
          if let Some(metadata) = new_metadata {
            workunit.metadata = metadata;
          }
          workunit.counters = new_counters;
          workunit_records.insert(span_id, workunit.clone());

          if should_emit(&workunit) {
            workunit.parent_id = first_matched_parent(
              &workunit_records,
              workunit.parent_id,
              |_| false,
              should_emit,
            );
            completed_workunits.push(workunit);
          }
        }
      }
    }
    (started_workunits, completed_workunits)
  }
}

#[derive(Clone)]
struct HeavyHittersData {
  inner: Arc<Mutex<HeavyHittersInnerStore>>,
  msg_tx: Arc<Mutex<Sender<StoreMsg>>>,
  msg_rx: Arc<Mutex<Receiver<StoreMsg>>>,
}

impl HeavyHittersData {
  fn new() -> HeavyHittersData {
    let (msg_tx, msg_rx) = channel();
    HeavyHittersData {
      inner: Arc::new(Mutex::new(HeavyHittersInnerStore {
        running_graph: RunningWorkunitGraph::new(),
        span_id_to_graph: HashMap::new(),
        workunit_records: HashMap::new(),
      })),
      msg_rx: Arc::new(Mutex::new(msg_rx)),
      msg_tx: Arc::new(Mutex::new(msg_tx)),
    }
  }

  fn add_started_workunit_to_store(started: Workunit, inner_store: &mut HeavyHittersInnerStore) {
    let span_id = started.span_id;
    let parent_id = started.parent_id;

    inner_store.workunit_records.insert(span_id, started);

    let child = inner_store.running_graph.add_node(span_id);
    inner_store.span_id_to_graph.insert(span_id, child);
    if let Some(parent_id) = parent_id {
      if let Some(parent) = inner_store.span_id_to_graph.get(&parent_id) {
        inner_store.running_graph.add_edge(*parent, child, ());
      }
    }
  }

  fn add_completed_workunit_to_store(
    span_id: SpanId,
    new_metadata: Option<WorkunitMetadata>,
    end_time: SystemTime,
    new_counters: HashMap<Metric, u64>,
    inner_store: &mut HeavyHittersInnerStore,
  ) {
    if let Some(node) = inner_store.span_id_to_graph.remove(&span_id) {
      inner_store.running_graph.remove_node(node);
    }

    match inner_store.workunit_records.entry(span_id) {
      Entry::Vacant(_) => {
        log::warn!("No previously-started workunit found for id: {}", span_id);
      }
      Entry::Occupied(mut o) => {
        let workunit = o.get_mut();
        match workunit.state {
          WorkunitState::Completed { .. } => {
            log::warn!("Workunit {} was already completed", span_id);
          }
          WorkunitState::Started { start_time, .. } => {
            let time_span = TimeSpan::from_start_and_end_systemtime(&start_time, &end_time);
            workunit.state = WorkunitState::Completed { time_span };
          }
        };
        if let Some(metadata) = new_metadata {
          workunit.metadata = metadata;
        }
        workunit.counters = new_counters;
      }
    }
  }

  fn refresh_store(&self) {
    let mut inner = self.inner.lock();
    let receiver = self.msg_rx.lock();
    while let Ok(msg) = receiver.try_recv() {
      match msg {
        StoreMsg::Started(started) => Self::add_started_workunit_to_store(started, &mut inner),
        StoreMsg::Completed(span_id, new_metadata, time, new_counters) => {
          Self::add_completed_workunit_to_store(
            span_id,
            new_metadata,
            time,
            new_counters,
            &mut inner,
          )
        }
        StoreMsg::Canceled(span_id) => {
          inner.workunit_records.remove(&span_id);
          if let Some(node) = inner.span_id_to_graph.remove(&span_id) {
            inner.running_graph.remove_node(node);
          }
        }
      }
    }
  }

  fn heavy_hitters(&self, k: usize) -> HashMap<SpanId, (String, Option<String>, Option<Duration>)> {
    self.refresh_store();

    let now = SystemTime::now();
    let inner = self.inner.lock();

    // Initialize the heap with the leaves of the running workunit graph.
    let mut queue: BinaryHeap<(Duration, SpanId)> = inner
      .running_graph
      .externals(petgraph::Direction::Outgoing)
      .map(|entry| inner.running_graph[entry])
      .flat_map(|span_id: SpanId| {
        let workunit: Option<&Workunit> = inner.workunit_records.get(&span_id);
        match workunit {
          Some(workunit) if !workunit.state.blocked() => {
            Self::duration_for(now, workunit).map(|d| (d, span_id))
          }
          _ => None,
        }
      })
      .collect();

    // Output the visible parents of the longest running leaves.
    let mut res = HashMap::new();
    while let Some((_dur, span_id)) = queue.pop() {
      // If the leaf is visible or has a visible parent, emit it.
      if let Some(span_id) = first_matched_parent(
        &inner.workunit_records,
        Some(span_id),
        |wu| wu.state.completed(),
        Self::is_visible,
      ) {
        let workunit = inner.workunit_records.get(&span_id).unwrap();
        if let Some(effective_name) = workunit.metadata.desc.as_ref() {
          let maybe_duration = Self::duration_for(now, workunit);
          let maybe_goal_name = goal_parent_name(&inner.workunit_records, Some(span_id));
          res.insert(
            span_id,
            (effective_name.to_string(), maybe_goal_name, maybe_duration),
          );
          if res.len() >= k {
            break;
          }
        }
      }
    }
    res
  }

  fn straggling_workunits(&self, duration_threshold: Duration) -> Vec<(Duration, String)> {
    self.refresh_store();
    let now = SystemTime::now();
    let inner = self.inner.lock();

    let matching_visible_parents = inner
      .running_graph
      .externals(petgraph::Direction::Outgoing)
      .map(|entry| inner.running_graph[entry])
      .flat_map(|span_id: SpanId| inner.workunit_records.get(&span_id))
      .filter_map(|workunit| match Self::duration_for(now, workunit) {
        Some(duration) if !workunit.state.blocked() && duration >= duration_threshold => {
          first_matched_parent(
            &inner.workunit_records,
            Some(workunit.span_id),
            |wu| wu.state.completed(),
            Self::is_visible,
          )
          .and_then(|span_id| inner.workunit_records.get(&span_id))
          .and_then(|wu| wu.metadata.desc.as_ref())
          .map(|desc| (desc.clone(), duration))
        }
        _ => None,
      })
      .collect::<HashMap<_, _>>();

    if matching_visible_parents.is_empty() {
      return vec![];
    }

    let mut stragglers = matching_visible_parents
      .into_iter()
      .map(|(k, v)| (v, k))
      .collect::<Vec<_>>();
    // NB: Because the Duration is first in the tuple, we get ascending Duration order.
    stragglers.sort();
    stragglers
  }

  fn is_visible(workunit: &Workunit) -> bool {
    workunit.metadata.level <= Level::Debug
      && workunit.metadata.desc.is_some()
      && matches!(workunit.state, WorkunitState::Started { .. })
  }

  fn duration_for(now: SystemTime, workunit: &Workunit) -> Option<Duration> {
    match workunit.state {
      WorkunitState::Started { ref start_time, .. } => now.duration_since(*start_time).ok(),
      _ => None,
    }
  }
}

#[derive(Default)]
pub struct HeavyHittersInnerStore {
  running_graph: RunningWorkunitGraph,
  span_id_to_graph: HashMap<SpanId, NodeIndex<u32>>,
  workunit_records: HashMap<SpanId, Workunit>,
}

fn first_matched_parent(
  workunit_records: &HashMap<SpanId, Workunit>,
  mut span_id: Option<SpanId>,
  is_terminal: impl Fn(&Workunit) -> bool,
  is_visible: impl Fn(&Workunit) -> bool,
) -> Option<SpanId> {
  while let Some(current_span_id) = span_id {
    let workunit = workunit_records.get(&current_span_id);

    if let Some(workunit) = workunit {
      // Should we continue visiting parents?
      if is_terminal(workunit) {
        break;
      }

      // Is the current workunit visible?
      if is_visible(workunit) {
        return Some(current_span_id);
      }
    }

    // If not, try its parent.
    span_id = workunit.and_then(|workunit| workunit.parent_id);
  }
  None
}

fn goal_parent_name(
  workunit_records: &HashMap<SpanId, Workunit>,
  mut span_id: Option<SpanId>,
) -> Option<String> {
  let mut ret: Option<String> = None;
  let mut workunit: Option<&Workunit> = None;
  while let Some(current_span_id) = span_id {
    ret = workunit.map(|wu| wu.name.rsplit('.').next().unwrap().to_string());
    workunit = workunit_records.get(&current_span_id);
    span_id = workunit.and_then(|workunit| workunit.parent_id);
  }
  ret
}

impl WorkunitStore {
  pub fn new(log_starting_workunits: bool) -> WorkunitStore {
    WorkunitStore {
      log_starting_workunits,
      // TODO: Create one `StreamingWorkunitData` per subscriber, and zero if no subscribers are
      // installed.
      streaming_workunit_data: StreamingWorkunitData::new(),
      heavy_hitters_data: HeavyHittersData::new(),
      observation_data: ObservationsData::default(),
    }
  }

  pub fn init_thread_state(&self, parent_id: Option<SpanId>) {
    set_thread_workunit_store_handle(Some(WorkunitStoreHandle {
      store: self.clone(),
      parent_id,
    }))
  }

  ///
  /// Return visible workunits which have been running longer than the duration_threshold, sorted
  /// in ascending order by their duration.
  ///
  pub fn straggling_workunits(&self, threshold: Duration) -> Vec<(Duration, String)> {
    self.heavy_hitters_data.straggling_workunits(threshold)
  }

  ///
  /// Find the longest running leaf workunits, and return their first visible parents.
  ///
  pub fn heavy_hitters(
    &self,
    k: usize,
  ) -> HashMap<SpanId, (String, Option<String>, Option<Duration>)> {
    self.heavy_hitters_data.heavy_hitters(k)
  }

  fn start_workunit(
    &self,
    span_id: SpanId,
    name: String,
    parent_id: Option<SpanId>,
    metadata: WorkunitMetadata,
  ) -> Workunit {
    let started = Workunit {
      name,
      span_id,
      parent_id,
      state: WorkunitState::Started {
        start_time: std::time::SystemTime::now(),
        blocked: Arc::new(AtomicBool::new(false)),
      },
      metadata,
      counters: HashMap::new(),
    };

    self
      .heavy_hitters_data
      .msg_tx
      .lock()
      .send(StoreMsg::Started(started.clone()))
      .unwrap();
    self
      .streaming_workunit_data
      .msg_tx
      .lock()
      .send(StoreMsg::Started(started.clone()))
      .unwrap();

    if self.log_starting_workunits {
      started.log_workunit_state(false)
    }
    started
  }

  fn complete_workunit(&self, workunit: Workunit) {
    let time = std::time::SystemTime::now();
    self.complete_workunit_impl(workunit, time)
  }

  fn cancel_workunit(&self, workunit: Workunit) {
    workunit.log_workunit_state(true);
    self
      .heavy_hitters_data
      .msg_tx
      .lock()
      .send(StoreMsg::Canceled(workunit.span_id))
      .unwrap();
  }

  fn complete_workunit_impl(&self, mut workunit: Workunit, end_time: SystemTime) {
    let span_id = workunit.span_id;
    let new_metadata = Some(workunit.metadata.clone());

    let tx = self.streaming_workunit_data.msg_tx.lock();
    tx.send(StoreMsg::Completed(
      span_id,
      new_metadata.clone(),
      end_time,
      workunit.counters.clone(),
    ))
    .unwrap();

    self
      .heavy_hitters_data
      .msg_tx
      .lock()
      .send(StoreMsg::Completed(
        span_id,
        new_metadata,
        end_time,
        workunit.counters.clone(),
      ))
      .unwrap();

    let start_time = match workunit.state {
      WorkunitState::Started { start_time, .. } => start_time,
      _ => {
        log::warn!("Workunit {} was already completed", span_id);
        return;
      }
    };
    let time_span = TimeSpan::from_start_and_end_systemtime(&start_time, &end_time);
    let new_state = WorkunitState::Completed { time_span };
    workunit.state = new_state;
    workunit.log_workunit_state(false);
  }

  pub fn add_completed_workunit(
    &self,
    name: String,
    start_time: SystemTime,
    end_time: SystemTime,
    parent_id: Option<SpanId>,
    metadata: WorkunitMetadata,
  ) {
    let span_id = SpanId::new();

    let workunit = Workunit {
      name,
      span_id,
      parent_id,
      state: WorkunitState::Started {
        start_time,
        blocked: Arc::new(AtomicBool::new(false)),
      },
      metadata,
      counters: HashMap::new(),
    };

    self
      .heavy_hitters_data
      .msg_tx
      .lock()
      .send(StoreMsg::Started(workunit.clone()))
      .unwrap();
    self
      .streaming_workunit_data
      .msg_tx
      .lock()
      .send(StoreMsg::Started(workunit.clone()))
      .unwrap();

    self.complete_workunit_impl(workunit, end_time);
  }

  pub fn latest_workunits(&mut self, max_verbosity: log::Level) -> (Vec<Workunit>, Vec<Workunit>) {
    self.streaming_workunit_data.latest_workunits(max_verbosity)
  }

  ///
  /// Records an observation of a time-like metric into a histogram.
  ///
  pub fn record_observation(&self, metric: ObservationMetric, value: u64) {
    let mut histograms_by_metric = self.observation_data.observations.lock();
    histograms_by_metric
      .entry(metric)
      .and_modify(|h| {
        let _ = h.record(value);
      })
      .or_insert_with(|| {
        let mut h = hdrhistogram::Histogram::<u64>::new(3).expect("Failed to allocate histogram");
        let _ = h.record(value);
        h
      });
  }

  ///
  /// Return all observations in binary encoded format.
  ///
  pub fn encode_observations(&self) -> Result<HashMap<String, Bytes>, String> {
    use hdrhistogram::serialization::V2DeflateSerializer;

    let mut serializer = V2DeflateSerializer::new();

    let mut result = HashMap::new();

    let histograms_by_metric = self.observation_data.observations.lock();
    for (metric, histogram) in histograms_by_metric.iter() {
      let mut writer = BytesMut::new().writer();

      serializer
        .serialize(histogram, &mut writer)
        .map_err(|err| {
          format!(
            "Failed to encode histogram for key `{}`: {}",
            metric.as_ref(),
            err
          )
        })?;

      result.insert(metric.as_ref().to_owned(), writer.into_inner().freeze());
    }

    Ok(result)
  }

  pub fn setup_for_tests() -> (WorkunitStore, RunningWorkunit) {
    let store = WorkunitStore::new(false);
    store.init_thread_state(None);
    let workunit = store.start_workunit(
      SpanId(0),
      "testing".to_owned(),
      None,
      WorkunitMetadata::default(),
    );
    (store.clone(), RunningWorkunit::new(store, workunit))
  }
}

pub fn format_workunit_duration(duration: Duration) -> String {
  let duration_secs: f64 = (duration.as_millis() as f64) / 1000.0;
  format!("{:.2}s ", duration_secs)
}

///
/// The per-thread/task state that tracks the current workunit store, and workunit parent id.
///
#[derive(Clone)]
pub struct WorkunitStoreHandle {
  pub store: WorkunitStore,
  pub parent_id: Option<SpanId>,
}

thread_local! {
  static THREAD_WORKUNIT_STORE_HANDLE: RefCell<Option<WorkunitStoreHandle >> = RefCell::new(None)
}

task_local! {
  static TASK_WORKUNIT_STORE_HANDLE: Option<WorkunitStoreHandle>;
}

///
/// Set the current parent_id for a Thread, but _not_ for a Task. Tasks must always be spawned
/// by callers using the `scope_task_workunit_store_handle` helper (generally via
/// task_executor::Executor.)
///
pub fn set_thread_workunit_store_handle(workunit_store_handle: Option<WorkunitStoreHandle>) {
  THREAD_WORKUNIT_STORE_HANDLE.with(|thread_workunit_handle| {
    *thread_workunit_handle.borrow_mut() = workunit_store_handle;
  })
}

pub fn get_workunit_store_handle() -> Option<WorkunitStoreHandle> {
  if let Ok(Some(store_handle)) =
    TASK_WORKUNIT_STORE_HANDLE.try_with(|task_store_handle| task_store_handle.clone())
  {
    Some(store_handle)
  } else {
    THREAD_WORKUNIT_STORE_HANDLE.with(|thread_store_handle| (*thread_store_handle.borrow()).clone())
  }
}

pub fn expect_workunit_store_handle() -> WorkunitStoreHandle {
  get_workunit_store_handle().expect("A WorkunitStore has not been set for this thread.")
}

///
/// NB: Public for macro usage: use the `in_workunit!` macro.
///
pub fn _start_workunit(
  workunit_store: WorkunitStore,
  name: String,
  initial_metadata: WorkunitMetadata,
) -> (WorkunitStoreHandle, RunningWorkunit) {
  let mut store_handle = expect_workunit_store_handle();
  let span_id = SpanId::new();
  let parent_id = std::mem::replace(&mut store_handle.parent_id, Some(span_id));
  let workunit = workunit_store.start_workunit(span_id, name, parent_id, initial_metadata);
  (store_handle, RunningWorkunit::new(workunit_store, workunit))
}

#[macro_export]
macro_rules! in_workunit {
    ($workunit_store: expr, $workunit_name: expr, $workunit_metadata: expr, |$workunit: ident| async move { $( $body:tt )* $(,)? }) => (
      {
        let (store_handle, mut $workunit) = $crate::_start_workunit($workunit_store, $workunit_name, $workunit_metadata);
        $crate::scope_task_workunit_store_handle(Some(store_handle), async move {
          let result = {
            let $workunit = &mut $workunit;
            async move { $( $body )* }
          }.await;
          $workunit.complete();
          result
        })
      }
    );
  ($workunit_store: expr, $workunit_name: expr, $workunit_metadata: expr, |$workunit: ident| $f: expr $(,)?) => (
    {
      let (store_handle, mut $workunit) = $crate::_start_workunit($workunit_store, $workunit_name, $workunit_metadata);
      $crate::scope_task_workunit_store_handle(Some(store_handle), async move {
          let result = {
            let $workunit = &mut $workunit;
            $f
          }.await;
          $workunit.complete();
          result
        })
    }
  );
}

pub struct RunningWorkunit {
  store: WorkunitStore,
  workunit: Option<Workunit>,
}

impl RunningWorkunit {
  fn new(store: WorkunitStore, workunit: Workunit) -> RunningWorkunit {
    RunningWorkunit {
      store,
      workunit: Some(workunit),
    }
  }

  pub fn increment_counter(&mut self, counter_name: Metric, change: u64) {
    if let Some(ref mut workunit) = self.workunit {
      workunit
        .counters
        .entry(counter_name)
        .and_modify(|e| *e += change)
        .or_insert(change);
    }
  }

  pub fn update_metadata<F>(&mut self, f: F)
  where
    F: FnOnce(WorkunitMetadata) -> WorkunitMetadata,
  {
    if let Some(ref mut workunit) = self.workunit {
      workunit.metadata = f(workunit.metadata.clone())
    }
  }

  ///
  /// Marks the workunit as being blocked until the returned token is dropped.
  ///
  pub fn blocking(&mut self) -> BlockingWorkunitToken {
    let mut token = BlockingWorkunitToken(None);
    if let Some(ref mut workunit) = self.workunit {
      if let WorkunitState::Started { blocked, .. } = &mut workunit.state {
        blocked.store(true, atomic::Ordering::Relaxed);
        token.0 = Some(blocked.clone());
      }
    }
    token
  }

  pub fn complete(&mut self) {
    if let Some(workunit) = self.workunit.take() {
      self.store.complete_workunit(workunit);
    }
  }
}

impl Drop for RunningWorkunit {
  fn drop(&mut self) {
    if let Some(workunit) = self.workunit.take() {
      self.store.cancel_workunit(workunit);
    }
  }
}

pub struct BlockingWorkunitToken(Option<Arc<AtomicBool>>);

impl Drop for BlockingWorkunitToken {
  fn drop(&mut self) {
    if let Some(blocked) = self.0.take() {
      blocked.store(false, atomic::Ordering::Relaxed);
    }
  }
}

#[derive(Clone)]
struct ObservationsData {
  /// Histograms for supported observation metrics.
  observations: Arc<Mutex<HashMap<ObservationMetric, hdrhistogram::Histogram<u64>>>>,
}

impl Default for ObservationsData {
  fn default() -> Self {
    ObservationsData {
      observations: Arc::new(Mutex::new(HashMap::new())),
    }
  }
}

///
/// Propagate the given WorkunitStoreHandle to a Future representing a newly spawned Task.
///
pub async fn scope_task_workunit_store_handle<F>(
  workunit_store_handle: Option<WorkunitStoreHandle>,
  f: F,
) -> F::Output
where
  F: Future,
{
  TASK_WORKUNIT_STORE_HANDLE
    .scope(workunit_store_handle, f)
    .await
}

#[cfg(test)]
mod tests;
