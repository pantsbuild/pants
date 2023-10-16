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

// make the entry module public for testing purposes. We use it to construct mock
// graph entries in the notify watch tests.
pub mod entry;
mod node;

pub use crate::entry::{Entry, EntryState};
use crate::entry::{Generation, NodeResult, RunToken};

use std::collections::VecDeque;
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::sync::{Arc, Weak};
use std::time::Duration;

use async_value::AsyncValueSender;
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

pub use crate::node::{EntryId, Node, NodeContext, NodeError, Stats};

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
        for id in &transitive_ids {
            if let Some(mut entry) = self.pg.node_weight_mut(*id).cloned() {
                if log_dirtied {
                    log::info!("Dirtying {}", entry.node());
                }
                entry.dirty(self);
            }
        }

        invalidation_result
    }

    fn visualize(&self, roots: &[N], path: &Path, context: &N::Context) -> io::Result<()> {
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

    fn live_reachable<'g>(
        &'g self,
        roots: &[N],
        context: &N::Context,
    ) -> impl Iterator<Item = (&N, N::Item)> + 'g {
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

    fn live<'g>(&'g self, context: &N::Context) -> impl Iterator<Item = (&N, N::Item)> + 'g {
        self.live_internal(self.pg.node_indices().collect(), context.clone())
    }

    fn live_internal(
        &self,
        entryids: Vec<EntryId>,
        context: N::Context,
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
pub struct Graph<N: Node> {
    inner: Arc<Mutex<InnerGraph<N>>>,
    invalidation_delay: Duration,
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
        }));
        let _join = executor.spawn(Self::cycle_check_task(Arc::downgrade(&inner)));

        Graph {
            inner,
            invalidation_delay,
        }
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
        context: &N::Context,
        dst_node: N,
    ) -> Result<(N::Item, Generation), N::Error> {
        // Compute information about the dst under the Graph lock, and then release it.
        let (dst_retry, mut entry, entry_id) = {
            // Get or create the destination, and then insert the dep and return its state.
            let mut inner = self.inner.lock();

            let dst_id = inner.ensure_entry(dst_node);
            let dst_retry = if let Some(src_id) = src_id {
                test_trace_log!(
                    "Adding dependency from {:?} to {:?}",
                    inner.entry_for_id(src_id).unwrap().node(),
                    inner.entry_for_id(dst_id).unwrap().node()
                );
                inner.pg.add_edge(src_id, dst_id, ());

                // We should retry the dst Node if the src Node is not restartable. If the src is not
                // restartable, it is only allowed to run once, and so Node invalidation does not pass
                // through it.
                !inner.entry_for_id(src_id).unwrap().node().restartable()
            } else {
                // Otherwise, this is an external request: always retry.
                test_trace_log!(
                    "Requesting node {:?}",
                    inner.entry_for_id(dst_id).unwrap().node()
                );
                true
            };

            let dst_entry = inner.entry_for_id(dst_id).cloned().unwrap();
            (dst_retry, dst_entry, dst_id)
        };

        // Return the state of the destination.
        if dst_retry {
            // Retry the dst a number of times to handle Node invalidation.
            let context = context.clone();
            loop {
                match entry.get_node_result(&context, entry_id).await {
                    Ok(r) => break Ok(r),
                    Err(err) if err == N::Error::invalidated() => {
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
                    Err(other_err) => break Err(other_err),
                }
            }
        } else {
            // Not retriable.
            entry.get_node_result(context, entry_id).await
        }
    }

    ///
    /// Request the given dst Node, optionally in the context of the given src Node.
    ///
    /// If there is no src Node, or the src Node is not restartable, this method will retry for
    /// invalidation until the Node completes.
    ///
    /// Invalidation events in the graph (generally, filesystem changes) will cause restartable
    /// Nodes to be retried here for up to `invalidation_timeout`.
    ///
    pub async fn get(
        &self,
        src_id: Option<EntryId>,
        context: &N::Context,
        dst_node: N,
    ) -> Result<N::Item, N::Error> {
        let (res, _generation) = self.get_inner(src_id, context, dst_node).await?;
        Ok(res)
    }

    ///
    /// Return the value of the given Node. Shorthand for `self.get(None, context, node)`.
    ///
    pub async fn create(&self, node: N, context: &N::Context) -> Result<N::Item, N::Error> {
        self.get(None, context, node).await
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
        context: &N::Context,
    ) -> Result<(N::Item, LastObserved), N::Error> {
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
        let (res, generation) = self.get_inner(None, context, node).await?;
        Ok((res, LastObserved(generation)))
    }

    ///
    /// Compares the generations of the dependencies of the given EntryId to their previous
    /// generation values (re-computing or cleaning them first if necessary), and returns true if any
    /// dependency has changed.
    ///
    async fn dependencies_changed(
        &self,
        entry_id: EntryId,
        previous_dep_generations: Vec<Generation>,
        context: &N::Context,
    ) -> bool {
        let generation_matches = {
            let inner = self.inner.lock();
            let entry = if log::log_enabled!(log::Level::Debug) {
                Some(inner.pg[entry_id].clone())
            } else {
                None
            };
            let dependency_ids = inner
                .pg
                .neighbors_directed(entry_id, Direction::Outgoing)
                .collect::<Vec<_>>();

            if dependency_ids.len() != previous_dep_generations.len() {
                // If we don't have the same number of current dependencies as there were generations
                // previously, then they cannot match.
                return true;
            }

            dependency_ids
                .into_iter()
                .zip(previous_dep_generations.into_iter())
                .map(|(dep_id, previous_dep_generation)| {
                    let entry = entry.clone();
                    let mut dep_entry = inner
                        .entry_for_id(dep_id)
                        .unwrap_or_else(|| panic!("Dependency not present in Graph."))
                        .clone();
                    async move {
                        let (_, generation) = dep_entry
                            .get_node_result(context, dep_id)
                            .await
                            .map_err(|_| ())?;
                        if generation == previous_dep_generation {
                            // Matched.
                            Ok(())
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
        future::try_join_all(generation_matches).await.is_err()
    }

    ///
    /// Clears the dependency edges of the given EntryId if the RunToken matches.
    ///
    fn cleaning_failed(&self, entry_id: EntryId, run_token: RunToken) {
        let mut inner = self.inner.lock();
        // If the RunToken mismatches, return.
        if let Some(entry) = inner.entry_for_id_mut(entry_id) {
            if entry.run_token() != run_token {
                return;
            }
            entry.cleaning_failed()
        }

        // Otherwise, clear the deps. We remove edges in reverse index order, because `remove_edge` is
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

    ///
    /// When a Node is canceled because all receivers go away, the Executor for that Node will call
    /// back to ensure that it is canceled.
    ///
    /// See also: `Self::complete`.
    ///
    fn cancel(&self, entry_id: EntryId, run_token: RunToken) {
        let mut inner = self.inner.lock();
        if let Some(ref mut entry) = inner.entry_for_id_mut(entry_id) {
            entry.cancel(run_token);
        }
    }

    ///
    /// When the Executor finishes executing a Node it calls back to store the result value. We use
    /// the run_token and dirty bits to determine whether the Node changed while we were busy
    /// executing it, so that we can discard the work.
    ///
    /// We use the dirty bit in addition to the RunToken in order to avoid cases where dependencies
    /// change while we're running. In order for a dependency to "change" it must have been cleared
    /// or been marked dirty. But if our dependencies have been cleared or marked dirty, then we will
    /// have been as well. We can thus use the dirty bit as a signal that the generation values of
    /// our dependencies are still accurate. The dirty bit is safe to rely on as it is only ever
    /// mutated, and dependencies' dirty bits are only read, under the InnerGraph lock - this is only
    /// reliably the case because Entry happens to require a &mut InnerGraph reference; it would be
    /// great not to violate that in the future.
    ///
    /// See also: `Self::cancel`.
    ///
    fn complete(
        &self,
        context: &N::Context,
        entry_id: EntryId,
        run_token: RunToken,
        sender: AsyncValueSender<NodeResult<N>>,
        result: Option<Result<N::Item, N::Error>>,
    ) {
        let (entry, has_uncacheable_deps, dep_generations) = {
            let inner = self.inner.lock();
            let mut has_uncacheable_deps = false;
            // Get the Generations of all dependencies of the Node. We can trust that these have not changed
            // since we began executing, as long as we are not currently marked dirty (see the method doc).
            let dep_generations = inner
                .pg
                .neighbors_directed(entry_id, Direction::Outgoing)
                .filter_map(|dep_id| inner.entry_for_id(dep_id))
                .map(|entry| {
                    // If a dependency is itself uncacheable or has uncacheable deps, this Node should
                    // also complete as having uncacheable deps, independent of matching Generation values.
                    // This is to allow for the behaviour that an uncacheable Node should always have "dirty"
                    // (marked as UncacheableDependencies) dependents, transitively.
                    if entry.has_uncacheable_deps() {
                        has_uncacheable_deps = true;
                    }
                    entry.generation()
                })
                .collect();
            (
                inner.entry_for_id(entry_id).cloned(),
                has_uncacheable_deps,
                dep_generations,
            )
        };
        if let Some(mut entry) = entry {
            let mut inner = self.inner.lock();
            entry.complete(
                context,
                run_token,
                dep_generations,
                sender,
                result,
                has_uncacheable_deps,
                &mut inner,
            );
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

    pub fn visualize(&self, roots: &[N], path: &Path, context: &N::Context) -> io::Result<()> {
        let inner = self.inner.lock();
        inner.visualize(roots, path, context)
    }

    pub fn visit_live_reachable(
        &self,
        roots: &[N],
        context: &N::Context,
        mut f: impl FnMut(&N, N::Item),
    ) {
        let inner = self.inner.lock();
        for (n, v) in inner.live_reachable(roots, context) {
            f(n, v);
        }
    }

    pub fn visit_live(&self, context: &N::Context, mut f: impl FnMut(&N, N::Item)) {
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
