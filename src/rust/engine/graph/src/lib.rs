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

// make the entry module public for testing purposes. We use it to construct mock
// graph entries in the notify watch tests.
pub mod entry;
mod node;

pub use crate::entry::{Entry, EntryState};
use crate::entry::{Generation, RunToken};

use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::File;
use std::hash::BuildHasherDefault;
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::time::Duration;

use fnv::FnvHasher;
use futures::future;
use log::{debug, info, warn};
use parking_lot::Mutex;
use petgraph::graph::DiGraph;
use petgraph::visit::EdgeRef;
use petgraph::Direction;
use tokio::time::delay_for;

pub use crate::node::{EntryId, Node, NodeContext, NodeError, NodeVisualizer, Stats};

type FNV = BuildHasherDefault<FnvHasher>;

type PGraph<N> = DiGraph<Entry<N>, f32, u32>;

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

  fn unsafe_entry_for_id(&self, id: EntryId) -> &Entry<N> {
    self
      .pg
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
  /// Detect whether adding an edge from src to dst would create a cycle.
  ///
  /// Returns a path which would cause the cycle if an edge were added from src to dst, or None if
  /// no cycle would be created.
  ///
  /// This strongly optimizes for the case of no cycles. If cycles are detected, this is very
  /// expensive to call.
  ///
  fn report_cycle(&self, src_id: EntryId, dst_id: EntryId) -> Option<Vec<Entry<N>>> {
    if src_id == dst_id {
      let entry = self.entry_for_id(src_id).unwrap();
      return Some(vec![entry.clone(), entry.clone()]);
    }
    if !self.detect_cycle(src_id, dst_id) {
      return None;
    }
    Self::shortest_path(&self.pg, dst_id, src_id).map(|mut path| {
      path.reverse();
      path.push(dst_id);
      path
        .into_iter()
        .map(|index| self.entry_for_id(index).unwrap().clone())
        .collect()
    })
  }

  ///
  /// Detect whether adding an edge from src to dst would create a cycle.
  ///
  /// Uses Dijkstra's algorithm, which is significantly cheaper than the Bellman-Ford, but keeps
  /// less context around paths on the way.
  ///
  fn detect_cycle(&self, src_id: EntryId, dst_id: EntryId) -> bool {
    // Search either forward from the dst, or backward from the src.
    let (root, needle, direction) = {
      let out_from_dst = self.pg.neighbors(dst_id).count();
      let in_to_src = self
        .pg
        .neighbors_directed(src_id, Direction::Incoming)
        .count();
      if out_from_dst < in_to_src {
        (dst_id, src_id, Direction::Outgoing)
      } else {
        (src_id, dst_id, Direction::Incoming)
      }
    };

    // Search for an existing path from dst to src.
    let mut roots = VecDeque::new();
    roots.push_back(root);
    self
      .walk(roots, direction, |_| false)
      .any(|eid| eid == needle)
  }

  ///
  /// Compute and return one shortest path from `src` to `dst`.
  ///
  /// Uses Bellman-Ford, which is pretty expensive O(VE) as it has to traverse the whole graph and
  /// keeping a lot of state on the way.
  ///
  fn shortest_path(graph: &PGraph<N>, src: EntryId, dst: EntryId) -> Option<Vec<EntryId>> {
    let (_path_weights, paths) = petgraph::algo::bellman_ford(graph, src)
      .expect("There should not be any negative edge weights");

    let mut next = dst;
    let mut path = Vec::new();
    path.push(next);
    while let Some(current) = paths[next.index()] {
      path.push(current);
      if current == src {
        return Some(path);
      }
      next = current;
    }
    None
  }

  ///
  /// Compute the critical path for this graph.
  ///
  /// The critical path is the longest path. For a directed acyclic graph, it is equivalent to a
  /// shortest path algorithm.
  ///
  /// Modify the graph we have to fit into the expectations of the Bellman-Ford shortest graph
  /// algorithm and use that to calculate the critical path.
  ///
  fn critical_path<F>(&self, roots: &[N], duration: &F) -> (Duration, Vec<Entry<N>>)
  where
    F: Fn(&Entry<N>) -> Duration,
  {
    fn duration_into_weight(d: Duration) -> f64 {
      -(d.as_nanos() as f64)
    }

    // First, let's map nodes to edges
    let mut graph = self.pg.filter_map(
      |_node_idx, node_weight| Some(Some(node_weight)),
      |edge_idx, _edge_weight| {
        let target_node = self.pg.raw_edges()[edge_idx.index()].target();
        self
          .pg
          .node_weight(target_node)
          .map(duration)
          .map(duration_into_weight)
      },
    );

    // Add a single source that's a parent to all roots
    let srcs = roots
      .iter()
      .filter_map(|n| self.entry_id(n))
      .cloned()
      .collect::<Vec<_>>();
    let src = graph.add_node(None);
    for node in srcs {
      graph.add_edge(
        src,
        node,
        graph
          .node_weight(node)
          .map(|maybe_weight| {
            maybe_weight
              .map(duration)
              .map(duration_into_weight)
              .unwrap_or(0.)
          })
          .unwrap(),
      );
    }

    let (weights, paths) =
      petgraph::algo::bellman_ford(&graph, src).expect("The graph must be acyclic");
    if let Some((index, total_duration)) = weights
      .into_iter()
      .enumerate()
      .filter_map(|(i, weight)| {
        // INFINITY is used for missing entries.
        if weight == std::f64::INFINITY {
          None
        } else {
          Some((i, Duration::from_nanos(-weight as u64)))
        }
      })
      .max_by(|(_, left_duration), (_, right_duration)| left_duration.cmp(&right_duration))
    {
      let critical_path = {
        let mut next = paths[index];
        let mut path = vec![graph
          .node_weight(petgraph::graph::NodeIndex::new(index))
          .unwrap()
          .unwrap()];
        while next != Some(src) && next != None {
          if let Some(entry) = graph.node_weight(next.unwrap()).unwrap() {
            path.push(*entry);
          }
          next = paths[next.unwrap().index()];
        }
        path.into_iter().rev().cloned().collect()
      };
      (total_duration, critical_path)
    } else {
      (Duration::from_nanos(0), vec![])
    }
  }

  ///
  /// Begins a Walk from the given roots.
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
      walked: HashSet::default(),
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
  fn invalidate_from_roots<P: Fn(&N) -> bool>(&mut self, predicate: P) -> InvalidationResult {
    // Collect all entries that will be cleared.
    let root_ids: HashSet<_, FNV> = self
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
    let transitive_ids: Vec<_> = self
      .walk(
        root_ids.iter().cloned().collect(),
        Direction::Incoming,
        |_| false,
      )
      .filter(|eid| !root_ids.contains(eid))
      .collect();

    let invalidation_result = InvalidationResult {
      cleared: root_ids.len(),
      dirtied: transitive_ids.len(),
    };

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
        entry.dirty(self);
      }
    }

    invalidation_result
  }

  fn visualize<V: NodeVisualizer<N>>(
    &self,
    mut visualizer: V,
    roots: &[N],
    path: &Path,
    context: &N::Context,
  ) -> io::Result<()> {
    let file = File::create(path)?;
    let mut f = BufWriter::new(file);

    f.write_all(b"digraph plans {\n")?;
    f.write_fmt(format_args!(
      "  node[colorscheme={}];\n",
      visualizer.color_scheme()
    ))?;
    f.write_all(b"  concentrate=true;\n")?;
    f.write_all(b"  rankdir=TB;\n")?;

    let mut format_color = |entry: &Entry<N>| visualizer.color(entry, context);

    let root_entries = roots
      .iter()
      .filter_map(|n| self.entry_id(n))
      .cloned()
      .collect();

    for eid in self.walk(root_entries, Direction::Outgoing, |_| false) {
      let entry = self.unsafe_entry_for_id(eid);
      let node_str = entry.format(context);

      // Write the node header.
      f.write_fmt(format_args!(
        "  \"{}\" [style=filled, fillcolor={}];\n",
        node_str,
        format_color(entry)
      ))?;

      for dep_id in self.pg.neighbors(eid) {
        let dep_entry = self.unsafe_entry_for_id(dep_id);

        // Write an entry per edge.
        let dep_str = dep_entry.format(context);
        f.write_fmt(format_args!("    \"{}\" -> \"{}\"\n", node_str, dep_str))?;
      }
    }

    f.write_all(b"}\n")?;
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
      self
        .walk(root_ids, Direction::Outgoing, |_| false)
        .collect(),
      context.clone(),
    )
  }

  fn live<'g>(&'g self, context: &N::Context) -> impl Iterator<Item = (&N, N::Item)> + 'g {
    self.live_internal(self.pg.node_indices().collect(), context.clone())
  }

  fn live_internal<'g>(
    &'g self,
    entryids: Vec<EntryId>,
    context: N::Context,
  ) -> impl Iterator<Item = (&N, N::Item)> + 'g {
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
  inner: Mutex<InnerGraph<N>>,
  invalidation_delay: Duration,
}

impl<N: Node> Graph<N> {
  pub fn new() -> Graph<N> {
    Self::new_with_invalidation_delay(Duration::from_millis(500))
  }

  pub fn new_with_invalidation_delay(invalidation_delay: Duration) -> Graph<N> {
    let inner = InnerGraph {
      nodes: HashMap::default(),
      pg: DiGraph::new(),
    };
    Graph {
      inner: Mutex::new(inner),
      invalidation_delay,
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

      // TODO: doing cycle detection under the lock... unfortunate, but probably unavoidable
      // without a much more complicated algorithm.
      let dst_id = inner.ensure_entry(dst_node);
      let dst_retry = if let Some(src_id) = src_id {
        if let Some(cycle_path) = Self::report_cycle(src_id, dst_id, &mut inner, context) {
          // Cyclic dependency: render an error.
          let path_strs = cycle_path
            .into_iter()
            .map(|e| e.node().to_string())
            .collect();
          return Err(N::Error::cyclic(path_strs));
        }

        // Valid dependency.
        test_trace_log!(
          "Adding dependency from {:?} to {:?}",
          inner.entry_for_id(src_id).unwrap().node(),
          inner.entry_for_id(dst_id).unwrap().node()
        );
        // All edges get a weight of 1.0 so that we can Bellman-Ford over the graph, treating each
        // edge as having equal weight.
        inner.pg.add_edge(src_id, dst_id, 1.0);

        // We can retry the dst Node if the src Node is not cacheable. If the src is not cacheable,
        // it only be allowed to run once, and so Node invalidation does not pass through it.
        !inner.entry_for_id(src_id).unwrap().node().cacheable()
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
            delay_for(self.invalidation_delay).await;
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
  /// If there is no src Node, or the src Node is not cacheable, this method will retry for
  /// invalidation until the Node completes.
  ///
  /// Invalidation events in the graph (generally, filesystem changes) will cause cacheable Nodes
  /// to be retried here for up to `invalidation_timeout`.
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
        delay_for(delay).await;
      }
    };

    // Re-request the Node.
    let (res, generation) = self.get_inner(None, context, node).await?;
    Ok((res, LastObserved(generation)))
  }

  fn report_cycle(
    src_id: EntryId,
    potential_dst_id: EntryId,
    inner: &mut InnerGraph<N>,
    context: &N::Context,
  ) -> Option<Vec<Entry<N>>> {
    let mut counter = 0;
    loop {
      // Find one cycle if any cycles exist.
      if let Some(cycle_path) = inner.report_cycle(src_id, potential_dst_id) {
        // See if the cycle contains any dirty nodes. If there are dirty nodes, we can try clearing
        // them, and then check if there are still any cycles in the graph.
        let dirty_nodes: HashSet<_> = cycle_path
          .iter()
          .filter(|n| !n.is_clean(context))
          .map(|n| n.node().clone())
          .collect();
        if dirty_nodes.is_empty() {
          // We detected a cycle with no dirty nodes - there's a cycle and there's nothing we can do
          // to remove it. We only log at debug because the UI will render the cycle.
          debug!(
            "Detected cycle considering adding edge from {:?} to {:?}; existing path: {:?}",
            inner.entry_for_id(src_id).unwrap(),
            inner.entry_for_id(potential_dst_id).unwrap(),
            cycle_path
          );
          return Some(cycle_path);
        }
        counter += 1;
        // Obsolete edges from a dirty node may cause fake cycles to be detected if there was a
        // dirty dep from A to B, and we're trying to add a dep from B to A.
        // If we detect a cycle that contains dirty nodes (and so potentially obsolete edges),
        // we repeatedly cycle-detect, clearing (and re-running) and dirty nodes (and their edges)
        // that we encounter.
        //
        // We do this repeatedly, because there may be multiple paths which would cause cycles,
        // which contain dirty nodes. If we've cleared 10 separate paths which contain dirty nodes,
        // and are still detecting cycle-causing paths containing dirty nodes, give up. 10 is a very
        // arbitrary number, which we can increase if we find real graphs in the wild which hit this
        // limit.
        if counter > 10 {
          warn!(
            "Couldn't remove cycle containing dirty nodes after {} attempts; nodes in cycle: {:?}",
            counter, cycle_path
          );
          return Some(cycle_path);
        }
        // Clear the dirty nodes, removing the edges from them, and try again.
        inner.invalidate_from_roots(|node| dirty_nodes.contains(node));
      } else {
        return None;
      }
    }
  }

  ///
  /// Calculate the critical path for the subset of the graph that descends from these roots,
  /// assuming this mapping between entries and durations.
  ///
  pub fn critical_path<F>(&self, roots: &[N], duration: &F) -> (Duration, Vec<Entry<N>>)
  where
    F: Fn(&Entry<N>) -> Duration,
  {
    self.inner.lock().critical_path(roots, duration)
  }

  ///
  /// Gets the generations of the dependencies of the given EntryId, (re)computing or cleaning
  /// them first if necessary.
  ///
  async fn dep_generations(
    &self,
    entry_id: EntryId,
    context: &N::Context,
  ) -> Result<Vec<Generation>, N::Error> {
    let generations = {
      let inner = self.inner.lock();
      inner
        .pg
        .neighbors_directed(entry_id, Direction::Outgoing)
        .map(|dep_id| {
          let mut entry = inner
            .entry_for_id(dep_id)
            .unwrap_or_else(|| panic!("Dependency not present in Graph."))
            .clone();
          async move {
            let (_, generation) = entry.get_node_result(context, dep_id).await?;
            Ok(generation)
          }
        })
        .collect::<Vec<_>>()
    };
    future::try_join_all(generations).await
  }

  ///
  /// Clears the dependency edges of the given EntryId if the RunToken matches.
  ///
  fn clear_deps(&self, entry_id: EntryId, run_token: RunToken) {
    let mut inner = self.inner.lock();
    // If the RunToken mismatches, return.
    if let Some(entry) = inner.entry_for_id(entry_id) {
      if entry.run_token() != run_token {
        return;
      }
    }

    // Otherwise, clear the deps.
    // NB: Because `remove_edge` changes EdgeIndex values, we remove edges one at a time.
    while let Some(dep_edge) = inner
      .pg
      .edges_directed(entry_id, Direction::Outgoing)
      .next()
      .map(|edge| edge.id())
    {
      inner.pg.remove_edge(dep_edge);
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
  /// TODO: We don't track which generation actually added which edges, so over time nodes will end
  /// up with spurious dependencies. This is mostly sound, but may lead to over-invalidation and
  /// doing more work than is necessary.
  /// As an example, if generation 0 of X depends on A and B, and generation 1 of X depends on C,
  /// nothing will prune the dependencies from X onto A and B, so generation 1 of X will have
  /// dependencies on A, B, and C in the graph, even though running it only depends on C.
  /// At some point we should address this, but we must be careful with how we do so; anything which
  /// ties together the generation of a node with specifics of edges would require careful
  /// consideration of locking (probably it would require merging the EntryState locks and Graph
  /// locks, or working out something clever).
  ///
  /// It would also require careful consideration of nodes in the Running EntryState - these may
  /// have previous RunToken edges and next RunToken edges which collapse into the same Generation
  /// edges; when working out whether a dirty node is really clean, care must be taken to avoid
  /// spurious cycles. Currently we handle this as a special case by, if we detect a cycle that
  /// contains dirty nodes, clearing those nodes (removing any edges from them). This is a little
  /// hacky, but will tide us over until we fully solve this problem.
  ///
  fn complete(
    &self,
    context: &N::Context,
    entry_id: EntryId,
    run_token: RunToken,
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
          // also complete as having uncacheable dpes, independent of matching Generation values.
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

  pub fn invalidate_from_roots<P: Fn(&N) -> bool>(&self, predicate: P) -> InvalidationResult {
    let mut inner = self.inner.lock();
    inner.invalidate_from_roots(predicate)
  }

  pub fn visualize<V: NodeVisualizer<N>>(
    &self,
    visualizer: V,
    roots: &[N],
    path: &Path,
    context: &N::Context,
  ) -> io::Result<()> {
    let inner = self.inner.lock();
    inner.visualize(visualizer, roots, path, context)
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

  ///
  /// Executes an operation while all access to the Graph is prevented (by acquiring the Graph's
  /// lock).
  ///
  pub fn with_exclusive<F, T>(&self, f: F) -> T
  where
    F: FnOnce() -> T,
  {
    let _inner = self.inner.lock();
    f()
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
  walked: HashSet<EntryId, FNV>,
  stop_walking_predicate: F,
}

impl<'a, N: Node + 'a, F: Fn(&EntryId) -> bool> Iterator for Walk<'a, N, F> {
  type Item = EntryId;

  fn next(&mut self) -> Option<Self::Item> {
    while let Some(id) = self.deque.pop_front() {
      // Visit this node and it neighbors if this node has not yet be visited and we aren't
      // stopping our walk at this node, based on if it satisfies the stop_walking_predicate.
      // This mechanism gives us a way to selectively dirty parts of the graph respecting node boundaries
      // like uncacheable nodes, which shouldn't be dirtied.
      if !self.walked.insert(id) || (self.stop_walking_predicate)(&id) {
        continue;
      }

      self
        .deque
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
