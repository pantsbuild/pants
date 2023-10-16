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

use std::any::Any;
use std::cell::RefCell;
use std::cmp::Reverse;
use std::collections::{hash_map, BinaryHeap, HashMap, HashSet};
use std::fmt::Debug;
use std::future::Future;
use std::sync::atomic::{self, AtomicBool};
use std::sync::Arc;
use std::time::{Duration, SystemTime};

use bytes::{BufMut, Bytes, BytesMut};
use concrete_time::TimeSpan;
use deepsize::DeepSizeOf;
use hdrhistogram::serialization::Serializer;
use log::log;
pub use log::Level;
pub use metrics::{Metric, ObservationMetric};
use parking_lot::Mutex;
use petgraph::stable_graph::{NodeIndex, StableDiGraph};
use petgraph::visit::{VisitMap, Visitable};
use rand::thread_rng;
use rand::Rng;
use smallvec::SmallVec;
use tokio::sync::mpsc::{self, UnboundedReceiver, UnboundedSender};
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
#[derive(Clone, Copy, Debug, DeepSizeOf, PartialEq, Eq, Hash)]
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

type ParentIds = SmallVec<[SpanId; 2]>;

/// Stores the content of running workunits, and tombstones for workunits which have completed,
/// but which still had children when they completed (in which case the stored Workunit will be
/// None, making them effectively invisible aside from their SpanId, Level, and ParentIds).
#[derive(Default)]
struct RunningWorkunitGraph {
    graph: StableDiGraph<SpanId, (), u32>,
    entries: HashMap<SpanId, (NodeIndex<u32>, Level, Option<Workunit>)>,
}

impl RunningWorkunitGraph {
    /// Get a reference to workunit for the given SpanId, if it is still running.
    fn get(&self, span_id: SpanId) -> Option<&Workunit> {
        self.entries
            .get(&span_id)
            .and_then(|(_, _, workunit)| workunit.as_ref())
    }

    /// Add a running workunit to the graph.
    fn add(&mut self, workunit: Workunit) {
        let parent_ids = workunit.parent_ids.clone();
        let child = self.graph.add_node(workunit.span_id);
        self.entries
            .insert(workunit.span_id, (child, workunit.level, Some(workunit)));
        for parent_id in parent_ids {
            if let Some((parent, _, _)) = self.entries.get(&parent_id) {
                self.graph.add_edge(*parent, child, ());
            }
        }
    }

    /// Complete a workunit, and remove it from the graph.
    ///
    /// We keep tombstone entries in the graph if they have children when they complete, in order
    /// to allow workunits to complete out of order/asynchronously while still tracking parent
    /// information.
    fn complete(
        &mut self,
        span_id: SpanId,
        new_metadata: Option<WorkunitMetadata>,
        end_time: SystemTime,
    ) -> Option<Workunit> {
        match self.entries.entry(span_id) {
            hash_map::Entry::Vacant(_) => {
                log::warn!("No previously-started workunit found for id: {}", span_id);
                None
            }
            hash_map::Entry::Occupied(mut entry) => {
                // If the entry is not a tombstone, take the workunit (which will make it a tombstone).
                let (node, _, workunit) = entry.get_mut();
                let mut workunit = workunit.take()?;

                workunit.parent_ids = self
                    .graph
                    .neighbors_directed(*node, petgraph::Direction::Incoming)
                    .map(|parent_node_id| self.graph[parent_node_id])
                    .collect();

                // If the workunit does not have children, remove it from the graph: otherwise, the entry
                // will be preserved as a tombstone.
                if self
                    .graph
                    .neighbors_directed(*node, petgraph::Direction::Outgoing)
                    .next()
                    .is_none()
                {
                    self.graph.remove_node(*node);
                    entry.remove();
                }

                match workunit.state {
                    WorkunitState::Completed { .. } => {
                        log::warn!("Workunit {} was already completed", span_id);
                    }
                    WorkunitState::Started { start_time, .. } => {
                        let time_span =
                            TimeSpan::from_start_and_end_systemtime(&start_time, &end_time);
                        workunit.state = WorkunitState::Completed { time_span };
                    }
                };
                workunit.metadata = new_metadata;
                Some(workunit)
            }
        }
    }

    /// Return the non-blocked leaves of the graph.
    fn running_leaves(&self) -> impl Iterator<Item = SpanId> + '_ {
        self.graph
            .externals(petgraph::Direction::Outgoing)
            .map(|entry| self.graph[entry])
            .flat_map(|span_id| self.get(span_id))
            .filter_map(|workunit| {
                if workunit.state.blocked() {
                    None
                } else {
                    Some(workunit.span_id)
                }
            })
    }

    /// Find the first parents matching the given conditions.
    ///
    /// Once a parent has been matched (or considered to be terminal) then none of its parents will
    /// be visited.
    fn first_matched_parents(
        &self,
        span_ids: impl IntoIterator<Item = SpanId>,
        is_visible: impl Fn(Level, Option<&Workunit>) -> bool,
    ) -> HashSet<SpanId> {
        let mut visited = self.graph.visit_map();
        let mut to_visit = span_ids.into_iter().collect::<Vec<_>>();
        let mut parent_ids = HashSet::new();
        while let Some(current_span_id) = to_visit.pop() {
            let (node, level, workunit) = if let Some(entry) = self.entries.get(&current_span_id) {
                entry
            } else {
                continue;
            };
            if !visited.visit(*node) {
                continue;
            }

            // Is the current workunit visible?
            if is_visible(*level, workunit.as_ref()) {
                parent_ids.insert(current_span_id);
                continue;
            }

            // If not, try its parents.
            to_visit.extend(
                self.graph
                    .neighbors_directed(*node, petgraph::Direction::Incoming)
                    .map(|parent_node_id| self.graph[parent_node_id]),
            );
        }
        parent_ids
    }
}

///
/// Workunits form a DAG of running, blocked, and completed work, with parent ids propagated via
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
/// NB: A Workunit which has too low a level for the WorkunitStore is called "disabled", but is
/// still recorded (without any metadata). This is for a few reasons:
///   1. It can be important to have accurate transitive parents when workunits are treated as a
///      DAG (see #14680): otherwise, adding an additional parent to an existing workunit is
///      tricky, because granularity is lost. For example: if `A -> B -> C` are workunits, and `B`
///      is disabled, an attempt to add a new parent to `B` would not have a record of the
///      relationship to `C`.
///   2. When a workunit completes, it is able to adjust its level (if it errored, for example),
///      and it is cleaner semantically to re-enable a disabled workunit when it completes than
///      to special case the creation of a the workunit at that point.
///
#[derive(Clone, Debug)]
pub struct Workunit {
    pub name: &'static str,
    pub level: Level,
    pub span_id: SpanId,
    // When a workunit starts, it (optionally) has a single parent. But as it runs, it
    // it may gain additional parents due to memoization.
    // TODO: Not yet implemented: see https://github.com/pantsbuild/pants/issues/14680.
    pub parent_ids: ParentIds,
    pub state: WorkunitState,
    pub metadata: Option<WorkunitMetadata>,
}

impl Workunit {
    // If the workunit has completed, its TimeSpan.
    pub fn time_span(&self) -> Option<TimeSpan> {
        match self.state {
            WorkunitState::Started { .. } => None,
            WorkunitState::Completed { time_span } => Some(time_span),
        }
    }

    fn log_workunit_state(&self, canceled: bool) {
        let metadata = match self.metadata.as_ref() {
            Some(metadata) if log::log_enabled!(self.level) => metadata,
            _ => return,
        };

        let state = match (&self.state, canceled) {
            (_, true) => "Canceled:",
            (WorkunitState::Started { .. }, _) => "Starting:",
            (WorkunitState::Completed { .. }, _) => "Completed:",
        };

        let identifier = if let Some(ref s) = metadata.desc {
            s.as_str()
        } else {
            self.name
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

        let message = if let Some(ref s) = metadata.message {
            format!(" - {}", s)
        } else {
            "".to_string()
        };

        log!(self.level, "{} {}{}", state, effective_identifier, message);
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
    fn blocked(&self) -> bool {
        match self {
            WorkunitState::Started { blocked, .. } => blocked.load(atomic::Ordering::Relaxed),
            WorkunitState::Completed { .. } => false,
        }
    }
}

// NB: Only implemented for `fs::DirectoryDigest`, but is boxed to avoid a cycle between this crate
// and the `fs` crate.
pub trait DirectoryDigest: Any + Debug + Send + Sync + 'static {
    // See https://vorner.github.io/2020/08/02/fights-with-downcasting.html.
    fn as_any(&self) -> &dyn Any;
}

// NB: Only implemented for `Value`, but is boxed to avoid a cycle between this crate and the
// `engine` crate.
pub trait Value: Any + Debug + Send + Sync + 'static {
    // See https://vorner.github.io/2020/08/02/fights-with-downcasting.html.
    fn as_any(&self) -> &dyn Any;
}

#[derive(Clone, Debug)]
pub enum ArtifactOutput {
    FileDigest(hashing::Digest),
    Snapshot(Arc<dyn DirectoryDigest>),
}

#[derive(Clone, Debug, Default)]
pub struct WorkunitMetadata {
    pub desc: Option<String>,
    pub message: Option<String>,
    pub stdout: Option<hashing::Digest>,
    pub stderr: Option<hashing::Digest>,
    pub artifacts: Vec<(String, ArtifactOutput)>,
    pub user_metadata: Vec<(String, UserMetadataItem)>,
}

/// Abstract id for passing user metadata items around
#[derive(Clone, Debug)]
pub enum UserMetadataItem {
    PyValue(Arc<dyn Value>),
    Int(i64),
    String(String),
}

#[derive(Clone)]
enum StoreMsg {
    Started(Workunit),
    Completed(SpanId, Level, Option<WorkunitMetadata>, SystemTime),
    Canceled(SpanId, SystemTime),
}

#[derive(Clone)]
pub struct WorkunitStore {
    log_starting_workunits: bool,
    max_level: Level,
    senders: [UnboundedSender<StoreMsg>; 2],
    streaming_workunit_data: Arc<Mutex<StreamingWorkunitData>>,
    heavy_hitters_data: Arc<Mutex<HeavyHittersData>>,
    metrics_data: Arc<MetricsData>,
}

struct StreamingWorkunitData {
    receiver: UnboundedReceiver<StoreMsg>,
    running_graph: RunningWorkunitGraph,
}

impl StreamingWorkunitData {
    fn new(receiver: UnboundedReceiver<StoreMsg>) -> StreamingWorkunitData {
        StreamingWorkunitData {
            receiver,
            running_graph: RunningWorkunitGraph::default(),
        }
    }

    pub fn latest_workunits(
        &mut self,
        max_verbosity: log::Level,
    ) -> (Vec<Workunit>, Vec<Workunit>) {
        let should_emit = |level: Level, _: Option<&Workunit>| -> bool { level <= max_verbosity };

        let mut started_workunits = Vec::new();
        let mut completed_workunits = Vec::new();
        while let Ok(msg) = self.receiver.try_recv() {
            match msg {
                StoreMsg::Started(mut started) => {
                    self.running_graph.add(started.clone());

                    if should_emit(started.level, Some(&started)) {
                        started.parent_ids = self
                            .running_graph
                            .first_matched_parents(started.parent_ids, should_emit)
                            .into_iter()
                            .collect();
                        started_workunits.push(started);
                    }
                }
                StoreMsg::Completed(span_id, level, new_metadata, end_time) => {
                    if let Some(mut workunit) =
                        self.running_graph.complete(span_id, new_metadata, end_time)
                    {
                        workunit.level = level;
                        if should_emit(level, Some(&workunit)) {
                            workunit.parent_ids = self
                                .running_graph
                                .first_matched_parents(workunit.parent_ids, should_emit)
                                .into_iter()
                                .collect();
                            completed_workunits.push(workunit);
                        }
                    }
                }
                StoreMsg::Canceled(..) => (),
            }
        }

        (started_workunits, completed_workunits)
    }
}

struct HeavyHittersData {
    receiver: UnboundedReceiver<StoreMsg>,
    running_graph: RunningWorkunitGraph,
}

impl HeavyHittersData {
    fn new(receiver: UnboundedReceiver<StoreMsg>) -> HeavyHittersData {
        HeavyHittersData {
            receiver,
            running_graph: RunningWorkunitGraph::default(),
        }
    }

    fn refresh_store(&mut self) {
        while let Ok(msg) = self.receiver.try_recv() {
            match msg {
                StoreMsg::Started(started) => self.running_graph.add(started),
                StoreMsg::Completed(span_id, _level, new_metadata, time) => {
                    let _ = self.running_graph.complete(span_id, new_metadata, time);
                }
                StoreMsg::Canceled(span_id, time) => {
                    let _ = self.running_graph.complete(span_id, None, time);
                }
            }
        }
    }

    fn heavy_hitters(&mut self, k: usize) -> HashMap<SpanId, (String, SystemTime)> {
        self.refresh_store();

        // Initialize the heap with the visible parents of the leaves of the running workunit graph,
        // sorted oldest first.
        let mut queue: BinaryHeap<(Reverse<SystemTime>, SpanId)> = self
            .running_graph
            .first_matched_parents(self.running_graph.running_leaves(), Self::is_visible)
            .into_iter()
            .flat_map(|span_id| self.running_graph.get(span_id))
            .filter_map(|workunit| match workunit.state {
                WorkunitState::Started { start_time, .. } => {
                    Some((Reverse(start_time), workunit.span_id))
                }
                _ => None,
            })
            .collect();

        // Output the longest running visible parents.
        let mut res = HashMap::new();
        while let Some((Reverse(start_time), span_id)) = queue.pop() {
            let workunit = self.running_graph.get(span_id).unwrap();
            if let Some(effective_name) = workunit.metadata.as_ref().and_then(|m| m.desc.as_ref()) {
                res.insert(workunit.span_id, (effective_name.to_string(), start_time));
                if res.len() >= k {
                    break;
                }
            }
        }
        res
    }

    fn straggling_workunits(&mut self, duration_threshold: Duration) -> Vec<(Duration, String)> {
        self.refresh_store();
        let now = SystemTime::now();

        // Collect the visible parents of running (non-blocked) leaves of the graph which have been
        // running for longer than the threshold.
        let matching_visible_parents = self
            .running_graph
            .first_matched_parents(self.running_graph.running_leaves(), Self::is_visible)
            .into_iter()
            .flat_map(|span_id| self.running_graph.get(span_id))
            .filter_map(|workunit| {
                let duration = Self::duration_for(now, workunit)?;
                if duration >= duration_threshold {
                    Some((
                        workunit
                            .metadata
                            .as_ref()
                            .and_then(|m| m.desc.as_ref())?
                            .clone(),
                        duration,
                    ))
                } else {
                    None
                }
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

    fn is_visible(level: Level, workunit: Option<&Workunit>) -> bool {
        level <= Level::Debug
            && workunit
                .and_then(|wu| wu.metadata.as_ref())
                .and_then(|m| m.desc.as_ref())
                .is_some()
    }

    fn start_time_for(workunit: &Workunit) -> Option<SystemTime> {
        match workunit.state {
            WorkunitState::Started { start_time, .. } => Some(start_time),
            _ => None,
        }
    }

    fn duration_for(now: SystemTime, workunit: &Workunit) -> Option<Duration> {
        now.duration_since(Self::start_time_for(workunit)?).ok()
    }
}

impl WorkunitStore {
    pub fn new(log_starting_workunits: bool, max_level: Level) -> WorkunitStore {
        // NB: Although it would be nice not to have seperate allocations per consumer, it is
        // difficult to use a channel like `tokio::sync::broadcast` due to that channel being bounded.
        // Subscribers receive messages at very different rates, and adjusting the workunit level
        // affects the total number of messages that might be queued at any given time.
        let (sender1, receiver1) = mpsc::unbounded_channel();
        let (sender2, receiver2) = mpsc::unbounded_channel();
        WorkunitStore {
            log_starting_workunits,
            max_level,
            // TODO: Create one `StreamingWorkunitData` per subscriber, and zero if no subscribers are
            // installed.
            senders: [sender1, sender2],
            streaming_workunit_data: Arc::new(Mutex::new(StreamingWorkunitData::new(receiver1))),
            heavy_hitters_data: Arc::new(Mutex::new(HeavyHittersData::new(receiver2))),
            metrics_data: Arc::default(),
        }
    }

    pub fn init_thread_state(&self, parent_id: Option<SpanId>) {
        set_thread_workunit_store_handle(Some(WorkunitStoreHandle {
            store: self.clone(),
            parent_id,
        }))
    }

    pub fn max_level(&self) -> Level {
        self.max_level
    }

    ///
    /// Return visible workunits which have been running longer than the duration_threshold, sorted
    /// in ascending order by their duration.
    ///
    pub fn straggling_workunits(&self, threshold: Duration) -> Vec<(Duration, String)> {
        self.heavy_hitters_data
            .lock()
            .straggling_workunits(threshold)
    }

    ///
    /// Find the longest running leaf workunits, and return the description and start time of their
    /// first visible parents.
    ///
    pub fn heavy_hitters(&self, k: usize) -> HashMap<SpanId, (String, SystemTime)> {
        self.heavy_hitters_data.lock().heavy_hitters(k)
    }

    fn send(&self, msg: StoreMsg) {
        let send_inner = |sender: &UnboundedSender<StoreMsg>, msg: StoreMsg| {
            sender
                .send(msg)
                .unwrap_or_else(|_| panic!("Receivers are static, and should always be present."));
        };
        // Send clones to the first N-1 senders, and the owned value to the final sender.
        for sender in &self.senders[0..self.senders.len() - 1] {
            send_inner(sender, msg.clone());
        }
        send_inner(&self.senders[self.senders.len() - 1], msg);
    }

    ///
    /// NB: Public for macro use. Use `in_workunit!` instead.
    ///
    pub fn _start_workunit(
        &self,
        span_id: SpanId,
        name: &'static str,
        level: Level,
        parent_id: Option<SpanId>,
        metadata: Option<WorkunitMetadata>,
    ) -> Workunit {
        let started = Workunit {
            name,
            level,
            span_id,
            parent_ids: parent_id.into_iter().collect(),
            state: WorkunitState::Started {
                start_time: std::time::SystemTime::now(),
                blocked: Arc::new(AtomicBool::new(false)),
            },
            metadata,
        };

        self.send(StoreMsg::Started(started.clone()));

        if self.log_starting_workunits {
            started.log_workunit_state(false)
        }
        started
    }

    fn complete_workunit(&self, workunit: Workunit) {
        self.complete_workunit_impl(workunit, std::time::SystemTime::now())
    }

    fn cancel_workunit(&self, workunit: Workunit) {
        workunit.log_workunit_state(true);
        self.send(StoreMsg::Canceled(
            workunit.span_id,
            std::time::SystemTime::now(),
        ));
    }

    fn complete_workunit_impl(&self, mut workunit: Workunit, end_time: SystemTime) {
        let level = workunit.level;
        let span_id = workunit.span_id;
        let new_metadata = workunit.metadata.clone();

        self.send(StoreMsg::Completed(span_id, level, new_metadata, end_time));

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
        name: &'static str,
        level: Level,
        start_time: SystemTime,
        end_time: SystemTime,
        parent_id: Option<SpanId>,
        metadata: WorkunitMetadata,
    ) {
        let span_id = SpanId::new();

        let workunit = Workunit {
            name,
            level,
            span_id,
            parent_ids: parent_id.into_iter().collect(),
            state: WorkunitState::Started {
                start_time,
                blocked: Arc::new(AtomicBool::new(false)),
            },
            metadata: Some(metadata),
        };

        self.send(StoreMsg::Started(workunit.clone()));
        self.complete_workunit_impl(workunit, end_time);
    }

    pub fn latest_workunits(&self, max_verbosity: log::Level) -> (Vec<Workunit>, Vec<Workunit>) {
        self.streaming_workunit_data
            .lock()
            .latest_workunits(max_verbosity)
    }

    pub fn increment_counter(&mut self, counter_name: Metric, change: u64) {
        self.metrics_data
            .counters
            .lock()
            .entry(counter_name)
            .and_modify(|e| *e += change)
            .or_insert(change);
    }

    pub fn get_metrics(&self) -> HashMap<&'static str, u64> {
        let counters = self.metrics_data.counters.lock();
        counters
            .iter()
            .map(|(metric, value)| (metric.into(), *value))
            .collect()
    }

    ///
    /// Records an observation of a time-like metric into a histogram.
    ///
    pub fn record_observation(&self, metric: ObservationMetric, value: u64) {
        let mut histograms_by_metric = self.metrics_data.observations.lock();
        histograms_by_metric
            .entry(metric)
            .and_modify(|h| {
                let _ = h.record(value);
            })
            .or_insert_with(|| {
                let mut h =
                    hdrhistogram::Histogram::<u64>::new(3).expect("Failed to allocate histogram");
                let _ = h.record(value);
                h
            });
    }

    ///
    /// Return all observations in binary encoded format.
    ///
    pub fn encode_observations(&self) -> Result<HashMap<&'static str, Bytes>, String> {
        use hdrhistogram::serialization::V2DeflateSerializer;

        let mut serializer = V2DeflateSerializer::new();

        let mut result = HashMap::new();

        let histograms_by_metric = self.metrics_data.observations.lock();
        for (metric, histogram) in histograms_by_metric.iter() {
            let mut writer = BytesMut::new().writer();

            serializer
                .serialize(histogram, &mut writer)
                .map_err(
                    |err| format!("Failed to encode histogram for key `{metric:?}`: {err}",),
                )?;

            result.insert(metric.into(), writer.into_inner().freeze());
        }

        Ok(result)
    }

    pub fn setup_for_tests() -> (WorkunitStore, RunningWorkunit) {
        let store = WorkunitStore::new(false, Level::Trace);
        store.init_thread_state(None);
        let workunit =
            store._start_workunit(SpanId(0), "testing", Level::Info, None, Option::default());
        (store.clone(), RunningWorkunit::new(store, workunit))
    }
}

#[macro_export]
macro_rules! format_workunit_duration_ms {
    ($workunit_duration_ms:expr) => {{
        format_args!("{:.2}s", ($workunit_duration_ms as f64) / 1000.0)
    }};
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
        THREAD_WORKUNIT_STORE_HANDLE
            .with(|thread_store_handle| (*thread_store_handle.borrow()).clone())
    }
}

pub fn expect_workunit_store_handle() -> WorkunitStoreHandle {
    get_workunit_store_handle().expect("A WorkunitStore has not been set for this thread.")
}

/// Run the given async block. If the level given by the WorkunitMetadata is above a configured
/// threshold, the block will run inside of a workunit recorded in the workunit store.
///
/// NB: This macro may only be used on a thread with a WorkunitStore configured (via
/// `WorkunitStore::init_thread_state`). Although it would be an option to silently ignore
/// workunits recorded from other threads, that would usually represent a bug caused by failing to
/// propagate state between threads.
#[macro_export]
macro_rules! in_workunit {
  ($workunit_name: expr, $workunit_level: expr $(, $workunit_field_name:ident = $workunit_field_value:expr)*, |$workunit: ident| $f: expr $(,)?) => {{
    use futures::future::FutureExt;
    let mut store_handle = $crate::expect_workunit_store_handle();
    let level: log::Level  = $workunit_level;
    let mut $workunit = {
      let workunit_metadata =
        if store_handle.store.max_level() >= level {
          Some($crate::WorkunitMetadata {
            $(
                  $workunit_field_name: $workunit_field_value,
            )*
            ..Default::default()
          })
        } else {
          None
        };
      let span_id = $crate::SpanId::new();
      let parent_id = std::mem::replace(&mut store_handle.parent_id, Some(span_id));
      let workunit =
        store_handle
          .store
          ._start_workunit(span_id, $workunit_name, level, parent_id, workunit_metadata);
      $crate::RunningWorkunit::new(store_handle.store.clone(), workunit)
    };
    $crate::scope_task_workunit_store_handle(Some(store_handle), async move {
      let result = {
        let $workunit = &mut $workunit;
        $f
      }
      .await;
      $workunit.complete();
      result
    })
    .boxed()
  }};
}

pub struct RunningWorkunit {
    store: WorkunitStore,
    workunit: Option<Workunit>,
}

impl RunningWorkunit {
    pub fn new(store: WorkunitStore, workunit: Workunit) -> RunningWorkunit {
        RunningWorkunit {
            store,
            workunit: Some(workunit),
        }
    }

    pub fn record_observation(&mut self, metric: ObservationMetric, value: u64) {
        self.store.record_observation(metric, value);
    }

    pub fn increment_counter(&mut self, counter_name: Metric, change: u64) {
        self.store.increment_counter(counter_name, change);
    }

    ///
    /// If the workunit is enabled, receives its current metadata. If Some((metadata, level)) is
    /// returned by the function, the workunit will complete as enabled if the new Level is high
    /// enough to enable it.
    ///
    pub fn update_metadata<F>(&mut self, f: F)
    where
        F: FnOnce(Option<(WorkunitMetadata, Level)>) -> Option<(WorkunitMetadata, Level)>,
    {
        if let Some(ref mut workunit) = self.workunit {
            if let Some((metadata, level)) =
                f(workunit.metadata.clone().map(|m| (m, workunit.level)))
            {
                workunit.level = level;
                workunit.metadata = Some(metadata);
            }
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

#[derive(Default)]
struct MetricsData {
    counters: Mutex<HashMap<Metric, u64>>,
    observations: Mutex<HashMap<ObservationMetric, hdrhistogram::Histogram<u64>>>,
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
