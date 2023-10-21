// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
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

mod context;
mod entry;
mod node;

use crate::entry::{Entry, Generation, RunToken};

use std::collections::VecDeque;
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::sync::{Arc, Weak};
use std::time::Duration;

use fixedbitset::FixedBitSet;
use fnv::{FnvHashMap as HashMap, FnvHashSet as HashSet};
use futures::future;
use log::info;
use parking_lot::Mutex;
use petgraph::dot;
use petgraph::graph::DiGraph;
use petgraph::visit::{EdgeRef, VisitMap, Visitable};
use petgraph::Direction;
use task_executor::Executor;
use tokio::time::sleep;
use workunit_store::RunId;

pub use crate::context::Context;
pub use crate::node::{CompoundNode, EntryId, Node, NodeError};

type PGraph<N> = DiGraph<Entry<N>, (), u32>;

#[derive(Debug, Eq, PartialEq)]
pub struct InvalidationResult {
    pub cleared: usize,
    pub dirtied: usize,
}

type Nodes<N> = HashMap<N, EntryId>;

struct InnerGraph<N: Node> {
    nodes: Nodes<N>,
    pg: PGraph<N>,
    run_id_generator: u32,
}

impl<N: Node> InnerGraph<N> {
    fn entry_id(&self, node: &N) -> Option<&EntryId> {
        self.nodes.get(node)
    }

    // TODO: Now that we never delete Entries, we should consider making this infallible.
    fn entry_for_id(&self, id: EntryId) -> Option<&Entry<N>> {
        self.pg.node_weight(id)
    }

    // TODO: Now that we never delete Entries, we should consider making this infallible.
    fn entry_for_id_mut(&mut self, id: EntryId) -> Option<&mut Entry<N>> {
        self.pg.node_weight_mut(id)
    }

    fn unsafe_entry_for_id(&self, id: EntryId) -> &Entry<N> {
        self.pg
            .node_weight(id)
            .expect("The unsafe_entry_for_id method should only be used in read-only methods!")
    }

    fn ensure_entry(&mut self, node: N) -> EntryId {
        InnerGraph::ensure_entry_internal(&mut self.pg, &mut self.nodes, node)
    }

    fn ensure_entry_internal(pg: &mut PGraph<N>, nodes: &mut Nodes<N>, node: N) -> EntryId {
        if let Some(&id) = nodes.get(&node) {
            return id;
        }

        // New entry.
        let id = pg.add_node(Entry::new(node.clone()));
        nodes.insert(node, id);
        id
    }

    ///
    /// Locates all* cycles in running nodes in the graph, and terminates one Node in each of them.
    ///
    /// * Finding "all simple cycles" in a graph is apparently best accomplished with [Johnson's
    /// algorithm](https://www.cs.tufts.edu/comp/150GA/homeworks/hw1/Johnson%2075.PDF), which uses
    /// the strongly connected components, but goes a bit further. Because this method will run
    /// multiple times, we don't worry about that, and just kill one member of each SCC.
    ///
    fn terminate_cycles(&mut self) {
        // Build a graph of Running node indexes.
        let running_graph = self.pg.filter_map(
            |node_idx, node_weight| {
                if node_weight.is_running() {
                    Some(node_idx)
                } else {
                    None
                }
            },
            |_edge_idx, _edge_weight| Some(()),
        );
        // TODO: We'd usually use `tarjan_scc` because it makes one fewer pass, but it panics (without
        // a useful error message) for some graphs. So `kosaraju_scc` it is.
        let running_sccs = petgraph::algo::kosaraju_scc(&running_graph);

        for running_scc in running_sccs {
            if running_scc.len() <= 1 {
                continue;
            }

            // There is a cycle. We bias toward terminating nodes which are being cleaned, because it's
            // possible for them to form false cycles with nodes which are running from scratch. If no
            // nodes are being cleaned, then choose the running node with the highest node id.
            let (running_candidate, should_terminate) = if let Some(dirty_candidate) = running_scc
                .iter()
                .filter(|&id| self.pg[running_graph[*id]].is_cleaning())
                .max_by_key(|&id| running_graph[*id])
            {
                // Nodes are being cleaned: clear the highest id entry.
                (dirty_candidate, false)
            } else {
                // There are no nodes being cleaned: terminate the Running node with the highest id.
                (
                    running_scc
                        .iter()
                        .max_by_key(|&id| running_graph[*id])
                        .unwrap(),
                    true,
                )
            };

            test_trace_log!(
                "Cycle {:?}",
                running_scc
                    .iter()
                    .map(|id| {
                        let entry = &self.pg[running_graph[*id]];
                        format!("{:?}: is_cleaning: {}", entry.node(), entry.is_cleaning())
                    })
                    .collect::<Vec<_>>(),
            );

            // Calculate one path between the chosen node and itself by finding a path to its first
            // predecessor (which as a fellow member of the SCC, must also be reachable).
            let running_predecessor = running_graph
                .neighbors_directed(*running_candidate, Direction::Incoming)
                .find(|id| running_scc.contains(id))
                .unwrap();
            let running_path: Vec<_> = petgraph::algo::all_simple_paths(
                &running_graph,
                *running_candidate,
                running_predecessor,
                0,
                None,
            )
            .next()
            .unwrap();

            // Either terminate or clear the candidate.
            let candidate = running_graph[*running_candidate];
            if should_terminate {
                // Render the error, and terminate the Node with it.
                let path = running_path
                    .into_iter()
                    .map(|rni| self.pg[running_graph[rni]].node())
                    .collect::<Vec<_>>();
                let error = N::cyclic_error(&path);
                self.pg[candidate].terminate(error);
            } else {
                // Else, clear.
                let node = self.pg[candidate].node().clone();
                self.invalidate_from_roots(true, |n| &node == n);
            }
        }
    }

    ///
    /// Begins a Walk from the given roots.
    ///
    /// The Walk will iterate over all nodes that descend from the roots in the direction of
    /// traversal but won't necessarily be in topological order.
    ///
    fn walk<F: Fn(&EntryId) -> bool>(
        &self,
        roots: VecDeque<EntryId>,
        direction: Direction,
        stop_walking_predicate: F,
    ) -> Walk<'_, N, F> {
        Walk {
            graph: self,
            direction: direction,
            deque: roots,
            walked: self.pg.visit_map(),
            stop_walking_predicate,
        }
    }

    fn clear(&mut self) {
        for eid in self.nodes.values() {
            if let Some(entry) = self.pg.node_weight_mut(*eid) {
                entry.clear(true);
            }
        }
    }

    ///
    /// Clears the values of all "invalidation root" Nodes and dirties their transitive dependents.
    ///
    /// An "invalidation root" is a Node in the graph which can be invalidated for a reason other
    /// than having had its dependencies changed.
    ///
    fn invalidate_from_roots<P: Fn(&N) -> bool>(
        &mut self,
        log_dirtied: bool,
        predicate: P,
    ) -> InvalidationResult {
        // Collect all entries that will be cleared.
        let root_ids: HashSet<_> = self
            .nodes
            .iter()
            .filter_map(|(node, &entry_id)| {
                // A NotStarted entry does not need clearing, and we can assume that its dependencies are
                // either already dirtied, or have never observed a value for it. Filtering these redundant
                // events helps to "debounce" invalidation (ie, avoid redundant re-dirtying of dependencies).
                if predicate(node) && self.unsafe_entry_for_id(entry_id).is_started() {
                    Some(entry_id)
                } else {
                    None
                }
            })
            .collect();

        // And their transitive dependencies, which will be dirtied.
        //
        // NB: We only dirty "through" a Node and into its dependents if it is Node::restartable.
        let transitive_ids: Vec<_> = self
            .walk(
                root_ids.iter().cloned().collect(),
                Direction::Incoming,
                |&entry_id| {
                    let entry = self.unsafe_entry_for_id(entry_id);
                    !entry.node().restartable() && entry.is_running()
                },
            )
            .filter(|eid| !root_ids.contains(eid))
            .collect();

        let invalidation_result = InvalidationResult {
            cleared: root_ids.len(),
            dirtied: transitive_ids.len(),
        };

        // If there were no roots, then nothing will be invalidated. Return early to avoid scanning all
        // edges in `retain_edges`.
        if root_ids.is_empty() {
            return invalidation_result;
        }

        // Clear roots and remove their outbound edges.
        for id in &root_ids {
            if let Some(entry) = self.pg.node_weight_mut(*id) {
                entry.clear(false);
            }
        }
        self.pg.retain_edges(|pg, edge| {
            if let Some((src, _)) = pg.edge_endpoints(edge) {
                !root_ids.contains(&src)
            } else {
                true
            }
        });

        // Dirty transitive entries, but do not yet clear their output edges. We wait to clear
        // outbound edges until we decide whether we can clean an entry: if we can, all edges are
        // preserved; if we can't, they are cleared in `Graph::clear_deps`.
        for id in transitive_ids {
            if let Some(entry) = self.entry_for_id_mut(id) {
                if log_dirtied {
                    log::info!("Dirtying {}", entry.node());
                }
                entry.dirty();
            }
        }

        invalidation_result
    }

    fn visualize(&self, roots: &[N], path: &Path, context: &Context<N>) -> io::Result<()> {
        let file = File::create(path)?;
        let mut f = BufWriter::new(file);

        let root_ids = roots
            .iter()
            .filter_map(|node| self.entry_id(node))
            .cloned()
            .collect();
        let included = self
            .walk(root_ids, Direction::Outgoing, |_| false)
            .collect::<HashSet<_>>();

        let graph = self.pg.filter_map(
            |node_id, node| {
                if included.contains(&node_id) {
                    Some(node.format(context))
                } else {
                    None
                }
            },
            |_, _| Some("".to_owned()),
        );

        f.write_all(
            format!(
                "{}",
                dot::Dot::with_config(&graph, &[dot::Config::EdgeNoLabel],)
            )
            .as_bytes(),
        )?;

        Ok(())
    }

    fn live_reachable(
        &self,
        roots: &[N],
        context: &Context<N>,
    ) -> impl Iterator<Item = (&N, N::Item)> {
        // TODO: This is a surprisingly expensive method, because it will clone all reachable values by
        // calling `peek` on them.
        let root_ids = roots
            .iter()
            .filter_map(|node| self.entry_id(node))
            .cloned()
            .collect();
        self.live_internal(
            self.walk(root_ids, Direction::Outgoing, |_| false)
                .collect(),
            context.clone(),
        )
    }

    fn live(&self, context: &Context<N>) -> impl Iterator<Item = (&N, N::Item)> {
        self.live_internal(self.pg.node_indices().collect(), context.clone())
    }

    fn live_internal(
        &self,
        entryids: Vec<EntryId>,
        context: Context<N>,
    ) -> impl Iterator<Item = (&N, N::Item)> + '_ {
        entryids
            .into_iter()
            .filter_map(move |eid| self.entry_for_id(eid))
            .filter_map(move |entry| entry.peek(&context).map(|i| (entry.node(), i)))
    }
}

///
/// A DAG (enforced on mutation) of Entries.
///
#[derive(Clone)]
pub struct Graph<N: Node> {
    inner: Arc<Mutex<InnerGraph<N>>>,
    invalidation_delay: Duration,
    executor: Executor,
}

impl<N: Node> Graph<N> {
    pub fn new(executor: Executor) -> Graph<N> {
        Self::new_with_invalidation_delay(executor, Duration::from_millis(500))
    }

    pub fn new_with_invalidation_delay(
        executor: Executor,
        invalidation_delay: Duration,
    ) -> Graph<N> {
        let inner = Arc::new(Mutex::new(InnerGraph {
            nodes: HashMap::default(),
            pg: DiGraph::new(),
            run_id_generator: 0,
        }));
        let _join = executor.native_spawn(Self::cycle_check_task(Arc::downgrade(&inner)));

        Graph {
            inner,
            invalidation_delay,
            executor,
        }
    }

    /// Create a Context wrapping an opaque Node::Context type, which will use a newly generated RunId.
    pub fn context(&self, context: N::Context) -> Context<N> {
        self.context_with_run_id(context, self.generate_run_id())
    }

    /// Create a Context wrapping an opaque Node::Context type.
    pub fn context_with_run_id(&self, context: N::Context, run_id: RunId) -> Context<N> {
        Context::new(self.clone(), context, run_id)
    }

    /// Generate a unique RunId for this Graph which can be reused in `context_with_run_id`.
    pub fn generate_run_id(&self) -> RunId {
        let mut inner = self.inner.lock();
        let run_id = inner.run_id_generator;
        inner.run_id_generator += 1;
        RunId(run_id)
    }

    ///
    /// A task which periodically checks for cycles in Running nodes. Doing this in the background
    /// allows for batching and laziness: nodes which don't form cycles may complete without ever
    /// being checked.
    ///
    /// Uses a `Weak` reference to the Graph to detect when the sender has shut down.
    ///
    async fn cycle_check_task(inner: Weak<Mutex<InnerGraph<N>>>) {
        loop {
            sleep(Duration::from_millis(500)).await;

            if let Some(inner) = Weak::upgrade(&inner) {
                inner.lock().terminate_cycles();
            } else {
                // We've been shut down.
                break;
            };
        }
    }

    pub fn len(&self) -> usize {
        let inner = self.inner.lock();
        inner.nodes.len()
    }

    async fn get_inner(
        &self,
        src_id: Option<EntryId>,
        context: &Context<N>,
        dst_node: N,
    ) -> (Result<N::Item, N::Error>, Generation) {
        // Compute information about the dst under the Graph lock, and then release it.
        let (entry, entry_id) = {
            // Get or create the destination, and then insert the dep and return its state.
            let mut inner = self.inner.lock();

            let dst_id = inner.ensure_entry(dst_node);
            if let Some(src_id) = src_id {
                test_trace_log!(
                    "Adding dependency from {:?} to {:?}",
                    inner.entry_for_id(src_id).unwrap().node(),
                    inner.entry_for_id(dst_id).unwrap().node()
                );
                inner.pg.add_edge(src_id, dst_id, ());
            } else {
                // Otherwise, this is an external request: always retry.
                test_trace_log!(
                    "Requesting node {:?}",
                    inner.entry_for_id(dst_id).unwrap().node()
                );
            }

            let dst_entry = inner.entry_for_id(dst_id).cloned().unwrap();
            (dst_entry, dst_id)
        };

        // Return the state of the destination, retrying the dst to handle Node invalidation.
        let context = context.clone();
        let (result, generation, uncacheable) = loop {
            match entry.get_node_result(&context, entry_id).await {
                (Err(err), _, _) if err == N::Error::invalidated() => {
                    let node = {
                        let inner = self.inner.lock();
                        inner.unsafe_entry_for_id(entry_id).node().clone()
                    };
                    info!(
                        "Filesystem changed during run: retrying `{}` in {:?}...",
                        node, self.invalidation_delay
                    );
                    sleep(self.invalidation_delay).await;
                    continue;
                }
                res => break res,
            }
        };

        if src_id.is_some() {
            if let Err(e) = context.dep_record(entry_id, generation, uncacheable) {
                return (Err(e), generation);
            }
        }

        (result, generation)
    }

    ///
    /// Return the value of the given Node.
    ///
    pub async fn create(&self, node: N, context: &Context<N>) -> Result<N::Item, N::Error> {
        let (res, _generation) = self.get_inner(None, context, node).await;
        res
    }

    ///
    /// Gets the value of the given Node (optionally waiting for it to have changed since the given
    /// LastObserved token), and then returns its new value and a new LastObserved token.
    ///
    pub async fn poll(
        &self,
        node: N,
        token: Option<LastObserved>,
        delay: Option<Duration>,
        context: &Context<N>,
    ) -> (Result<N::Item, N::Error>, LastObserved) {
        // If the node is currently clean at the given token, Entry::poll will delay until it has
        // changed in some way.
        if let Some(LastObserved(generation)) = token {
            let entry = {
                let mut inner = self.inner.lock();
                let entry_id = inner.ensure_entry(node.clone());
                inner.unsafe_entry_for_id(entry_id).clone()
            };
            entry.poll(context, generation).await;
            if let Some(delay) = delay {
                sleep(delay).await;
            }
        };

        // Re-request the Node.
        let (res, generation) = self.get_inner(None, context, node).await;
        (res, LastObserved(generation))
    }

    ///
    /// Compares the generations of the dependencies of the given EntryId to their previous
    /// generation values (re-computing or cleaning them first if necessary).
    ///
    /// Returns `Ok(uncacheable_deps)` if the node was successfully cleaned, and clears the node's
    /// edges if it was not successfully cleaned.
    ///
    async fn attempt_cleaning(
        &self,
        entry_id: EntryId,
        run_token: RunToken,
        previous_dep_generations: &[(EntryId, Generation)],
        context: &Context<N>,
    ) -> Result<bool, ()> {
        let generation_matches = {
            let inner = self.inner.lock();
            let entry = if log::log_enabled!(log::Level::Debug) {
                Some(inner.pg[entry_id].clone())
            } else {
                None
            };

            previous_dep_generations
                .iter()
                .map(|&(dep_id, previous_dep_generation)| {
                    let entry = entry.clone();
                    let dep_entry = inner
                        .entry_for_id(dep_id)
                        .unwrap_or_else(|| panic!("Dependency not present in Graph."))
                        .clone();

                    async move {
                        let (_, generation, uncacheable) =
                            dep_entry.get_node_result(context, dep_id).await;
                        if generation == previous_dep_generation {
                            // Matched.
                            Ok(uncacheable)
                        } else {
                            // Did not match. We error here to trigger fail-fast in `try_join_all`.
                            log::debug!(
                                "Dependency {} of {:?} changed.",
                                dep_entry.node(),
                                entry.map(|e| e.node().to_string())
                            );
                            Err(())
                        }
                    }
                })
                .collect::<Vec<_>>()
        };

        // We use try_join_all in order to speculatively execute all branches, and to fail fast if any
        // generation mismatches. The first mismatch encountered will cause any extraneous cleaning
        // work to be canceled. See #11290 for more information about the tradeoffs inherent in
        // speculation.
        match future::try_join_all(generation_matches).await {
            Ok(uncacheable_deps) => {
                // Cleaning succeeded.
                //
                // Return true if any dep was uncacheable.
                Ok(uncacheable_deps.into_iter().any(|u| u))
            }
            Err(()) => {
                // Cleaning failed.
                //
                // If the RunToken still matches, clear all edges of the Node before returning.
                let mut inner = self.inner.lock();
                if let Some(entry) = inner.entry_for_id_mut(entry_id) {
                    if entry.cleaning_failed(run_token).is_ok() {
                        // Clear the deps. We remove edges in reverse index order, because `remove_edge` is
                        // implemented in terms of `swap_remove`, and so affects edge ids greater than the removed edge
                        // id. See https://docs.rs/petgraph/0.5.1/petgraph/graph/struct.Graph.html#method.remove_edge
                        let mut edge_ids = inner
                            .pg
                            .edges_directed(entry_id, Direction::Outgoing)
                            .map(|e| e.id())
                            .collect::<Vec<_>>();
                        edge_ids.sort_by_key(|id| std::cmp::Reverse(id.index()));
                        for edge_id in edge_ids {
                            inner.pg.remove_edge(edge_id);
                        }
                    }
                }
                Err(())
            }
        }
    }

    ///
    /// Clears the state of all Nodes in the Graph by dropping their state fields.
    ///
    pub fn clear(&self) {
        let mut inner = self.inner.lock();
        inner.clear()
    }

    pub fn invalidate_from_roots<P: Fn(&N) -> bool>(
        &self,
        log_dirtied: bool,
        predicate: P,
    ) -> InvalidationResult {
        let mut inner = self.inner.lock();
        inner.invalidate_from_roots(log_dirtied, predicate)
    }

    pub fn visualize(&self, roots: &[N], path: &Path, context: &Context<N>) -> io::Result<()> {
        let inner = self.inner.lock();
        inner.visualize(roots, path, context)
    }

    pub fn visit_live_reachable(
        &self,
        roots: &[N],
        context: &Context<N>,
        mut f: impl FnMut(&N, N::Item),
    ) {
        let inner = self.inner.lock();
        for (n, v) in inner.live_reachable(roots, context) {
            f(n, v);
        }
    }

    pub fn visit_live(&self, context: &Context<N>, mut f: impl FnMut(&N, N::Item)) {
        let inner = self.inner.lock();
        for (n, v) in inner.live(context) {
            f(n, v);
        }
    }
}

///
/// An opaque token that represents a particular observed "version" of a Node.
///
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LastObserved(Generation);

///
/// Represents the state of a particular walk through a Graph. Implements Iterator and has the same
/// lifetime as the Graph itself.
///
struct Walk<'a, N: Node, F>
where
    F: Fn(&EntryId) -> bool,
{
    graph: &'a InnerGraph<N>,
    direction: Direction,
    deque: VecDeque<EntryId>,
    walked: FixedBitSet,
    stop_walking_predicate: F,
}

impl<'a, N: Node + 'a, F: Fn(&EntryId) -> bool> Iterator for Walk<'a, N, F> {
    type Item = EntryId;

    fn next(&mut self) -> Option<Self::Item> {
        while let Some(id) = self.deque.pop_front() {
            // Visit this node and it neighbors if this node has not yet be visited and we aren't
            // stopping our walk at this node, based on if it satisfies the stop_walking_predicate.
            // This mechanism gives us a way to selectively dirty parts of the graph respecting node boundaries
            // like !restartable nodes, which shouldn't be dirtied.
            if !self.walked.visit(id) || (self.stop_walking_predicate)(&id) {
                continue;
            }

            self.deque
                .extend(self.graph.pg.neighbors_directed(id, self.direction));
            return Some(id);
        }

        None
    }
}

///
/// Logs at trace level, but only in `cfg(test)`.
///
#[macro_export]
macro_rules! test_trace_log {
    ($($arg:tt)+) => {
      #[cfg(test)]
      {
        log::trace!($($arg)+)
      }
    };
}

#[cfg(test)]
mod tests;
