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

use crate::entry::Generation;
pub use crate::entry::{Entry, EntryResult, RunToken};

use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::File;
use std::hash::BuildHasherDefault;
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::time::Duration;

use fnv::FnvHasher;
use futures::future;
use log::{debug, info, trace};
use parking_lot::Mutex;
use petgraph::graph::DiGraph;
use petgraph::visit::EdgeRef;
use petgraph::Direction;
use tokio::time::delay_for;

pub use crate::node::{EdgeId, EntryId, Node, NodeContext, NodeError, NodeVisualizer};

type FNV = BuildHasherDefault<FnvHasher>;

type PGraph<N> = DiGraph<Entry<N>, (EdgeType, RunToken), u32>;

///
/// When an edge is created, it is created with one of two types.
///
/// A "strong" edge is required, and will always either return the value of the Node it depends
/// on, or fail if the creation of the edge would result in a cycle of strong edges.
///
/// A "weak" edge is optional, in that if adding a weak edge would create a cycle in the graph, the
/// request for the value may return None rather than failing.
///
/// TODO: Currently we do not allow a Node with a weak dependency to participate in a cycle with
/// itself that involves a strong edge. This means that entering a `strong-weak` cycle from one
/// side rather than the other has a different result (namely, one side will fail with a cycle
/// error, while the other doesn't). This can be worked around by making both edges weak.
///   see https://github.com/pantsbuild/pants/issues/10229
///
#[derive(Copy, Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
enum EdgeType {
  Weak,
  Strong,
}

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

  fn add_edge(
    &mut self,
    src_id: EntryId,
    dst_id: EntryId,
    edge_type: EdgeType,
    run_token: RunToken,
  ) {
    trace!(
      "Adding dependency {:?} from {:?} to {:?}",
      (edge_type, run_token),
      self.entry_for_id(src_id).unwrap().node(),
      self.entry_for_id(dst_id).unwrap().node(),
    );
    self.pg.add_edge(src_id, dst_id, (edge_type, run_token));
  }

  ///
  /// Detect whether adding an edge from src to dst would create a cycle and returns a path which
  /// would represent the cycle if an edge were added from src to dst. Returns None if no cycle
  /// would be created.
  ///
  /// This is a very expensive method relative to `detect_cycle`: if you don't need the cyclic
  /// path, prefer to call `detect_cycle`.
  ///
  fn detect_and_compute_cycle(
    &self,
    src_id: EntryId,
    dst_id: EntryId,
    should_include_edge: impl Fn(EdgeId) -> bool,
  ) -> Option<Vec<N>> {
    if !self.detect_cycle(src_id, dst_id, &should_include_edge) {
      return None;
    }

    Self::shortest_path(&self.pg, dst_id, src_id, should_include_edge).map(|mut path| {
      path.reverse();
      path.push(dst_id);
      path
        .into_iter()
        .map(|node_index| self.unsafe_entry_for_id(node_index).node().clone())
        .collect()
    })
  }

  ///
  /// Detect whether adding an edge from src to dst would create a cycle.
  ///
  /// Uses Dijkstra's algorithm, which is significantly cheaper than the Bellman-Ford, but keeps
  /// less context around paths on the way.
  ///
  fn detect_cycle(
    &self,
    src_id: EntryId,
    dst_id: EntryId,
    should_include_edge: impl Fn(EdgeId) -> bool,
  ) -> bool {
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
      .walk(roots, direction, should_include_edge)
      .any(|eid| eid == needle)
  }

  ///
  /// Compute and return one shortest path from `src` to `dst`.
  ///
  /// Uses Bellman-Ford, which is pretty expensive O(VE) as it has to traverse the whole graph and
  /// keeping a lot of state on the way.
  ///
  fn shortest_path(
    graph: &PGraph<N>,
    src: EntryId,
    dst: EntryId,
    should_include_edge: impl Fn(EdgeId) -> bool,
  ) -> Option<Vec<EntryId>> {
    let (_path_weights, paths) = {
      // We map the graph to an empty graph with the same node structure, but with potentially
      // fewer edges (based on the predicate). Edges are given equal-weighted float edges, because
      // bellman_ford requires weights.
      //
      // Because the graph has identical nodes, it also has identical node indices (guaranteed by
      // `filter_map`), and we can use the returned path structure as indices into the original
      // graph.
      let float_graph = graph.filter_map(
        |_entry_id, _node| Some(()),
        |edge_index, _edge_type| {
          if should_include_edge(edge_index) {
            Some(1.0_f32)
          } else {
            None
          }
        },
      );
      petgraph::algo::bellman_ford(&float_graph, src)
        .expect("There should not be any negative edge weights")
    };

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
  fn walk<F: Fn(EdgeId) -> bool>(
    &self,
    roots: VecDeque<EntryId>,
    direction: Direction,
    should_walk_edge: F,
  ) -> Walk<'_, N, F> {
    Walk {
      graph: self,
      direction: direction,
      deque: roots,
      walked: HashSet::default(),
      should_walk_edge,
    }
  }

  ///
  /// A running edge is an edge leaving a Running node with a matching RunToken: ie, an edge that was
  /// created by the active run of a node. Running edges are not allowed to form cycles, as that could
  /// cause work to deadlock on itself.
  ///
  /// "Running" edges are a subset of "live" edges: see `live_edge_predicate`
  ///
  fn running_edge_predicate<'a>(inner: &'a InnerGraph<N>) -> impl Fn(EdgeId) -> bool + 'a {
    move |edge_id| {
      let (edge_src_id, _) = inner.pg.edge_endpoints(edge_id).unwrap();
      if let Some(running_run_token) = inner.unsafe_entry_for_id(edge_src_id).running_run_token() {
        // Only include the edge if the Node is running, and the edge is for this run.
        inner.pg[edge_id].1 == running_run_token
      } else {
        // Node is not running.
        false
      }
    }
  }

  ///
  /// A live edge is an edge for the current RunToken of a Node, regardless of whether the Node is
  /// currently running.
  ///
  /// "Live" edges are a superset of "running" edges: see `running_edge_predicate`
  ///
  fn live_edge_predicate<'a>(inner: &'a InnerGraph<N>) -> impl Fn(EdgeId) -> bool + 'a {
    move |edge_id| {
      let (edge_src_id, _) = inner.pg.edge_endpoints(edge_id).unwrap();
      // Only include the edge if it is live.
      inner.pg[edge_id].1 == inner.unsafe_entry_for_id(edge_src_id).run_token()
    }
  }

  fn clear(&mut self) {
    for eid in self.nodes.values() {
      if let Some(entry) = self.pg.node_weight_mut(*eid) {
        entry.clear();
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
    // And their live transitive dependencies, which will be dirtied.
    let transitive_ids: Vec<_> = self
      .walk(
        root_ids.iter().cloned().collect(),
        Direction::Incoming,
        Self::live_edge_predicate(&self),
      )
      .filter(|eid| !root_ids.contains(eid))
      .collect();

    let invalidation_result = InvalidationResult {
      cleared: root_ids.len(),
      dirtied: transitive_ids.len(),
    };

    // Clear the roots.
    for id in &root_ids {
      if let Some(entry) = self.pg.node_weight_mut(*id) {
        entry.clear();
      }
    }

    // Dirty transitive entries, but do not yet clear their output edges. We wait to clear
    // outbound edges until we decide whether we can clean an entry: if we can, all edges are
    // preserved; if we can't, they are eventually cleaned in `Graph::garbage_collect_edges`.
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

    for eid in self.walk(root_entries, Direction::Outgoing, |_| true) {
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
        .walk(
          root_ids,
          Direction::Outgoing,
          Self::live_edge_predicate(&self),
        )
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
/// A potentially cyclic graph of Nodes and their dependencies.
///
/// ----
///
/// A note on cycles: We track the dependencies of Nodes for two primary reasons:
///
///   1. To allow for invalidation/dirtying/clearing when the transitive dependencies of a Node
///      have changed. See `invalidate_from_roots` for more information on this usecase.
///   2. To detect situations where a running Node might depend on its own result, which would
///      cause it to deadlock.
///
/// The first usecase (invalidation) does not care about cycles in the graph: if a Node
/// transitively depends on a previous version of itself, that's ok, as invalidation will dirty
/// the entire cycle.
///
/// The second case does care about cycle detection though, so when new dependencies are introduced
/// in the graph we cycle detect for the case where a running Node might depend on its own result
/// (as determined by the RunToken). Notably, this does _not_ prevent a Node from depending on a
/// previous run of itself, as that cannot cause a deadlock: the two computations are independent.
/// See Graph::report_cycle for more information.
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
    context: &N::Context,
    dst_node: N,
    edge_type: EdgeType,
  ) -> Result<Option<(N::Item, Generation)>, N::Error> {
    // Compute information about the dst under the Graph lock, and then release it.
    let (dst_retry, mut entry, entry_id) = {
      // Get or create the destination, and then insert the dep and return its state.
      let mut inner = self.inner.lock();

      // TODO: doing cycle detection under the lock... unfortunate, but probably unavoidable
      // without a much more complicated algorithm.
      let dst_id = inner.ensure_entry(dst_node);
      let dst_retry = if let Some((src_id, run_token)) = context.entry_id_and_run_token() {
        // See whether adding this edge would create a cycle.
        if inner.detect_cycle(src_id, dst_id, InnerGraph::running_edge_predicate(&inner)) {
          // If we have detected a cycle, the type of edge becomes relevant: a strong edge will
          // report the cycle as a failure, while a weak edge will go ahead and add the dependency,
          // but return None to indicate that it isn't consumable.
          match edge_type {
            EdgeType::Strong => {
              if let Some(cycle_path) = inner.detect_and_compute_cycle(
                src_id,
                dst_id,
                InnerGraph::running_edge_predicate(&inner),
              ) {
                debug!(
                  "Detected cycle considering adding edge from {:?} to {:?}; existing path: {:?}",
                  inner.entry_for_id(src_id).unwrap().node(),
                  inner.entry_for_id(dst_id).unwrap().node(),
                  cycle_path
                );
                // Cyclic dependency: render an error.
                let path_strs = cycle_path.into_iter().map(|n| n.to_string()).collect();
                return Err(N::Error::cyclic(path_strs));
              }
            }
            EdgeType::Weak => {
              // NB: A weak edge is still recorded, as the result can affect the behavior of the
              // node, and nodes with weak edges complete as Dirty to allow them to re-run.
              inner.add_edge(src_id, dst_id, edge_type, run_token);
              return Ok(None);
            }
          }
        }

        // Valid dependency.
        inner.add_edge(src_id, dst_id, edge_type, run_token);

        // We can retry the dst Node if the src Node is not cacheable. If the src is not cacheable,
        // it only be allowed to run once, and so Node invalidation does not pass through it.
        !inner.entry_for_id(src_id).unwrap().node().cacheable()
      } else {
        // Otherwise, this is an external request: always retry.
        trace!(
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
        match entry.get(&context, entry_id).await {
          Ok(r) => break Ok(Some(r)),
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
      Ok(Some(entry.get(context, entry_id).await?))
    }
  }

  ///
  /// Request the given dst Node in the given Context (which might represent a src Node).
  ///
  /// If there is no src Node, or the src Node is not cacheable, this method will retry for
  /// invalidation until the Node completes.
  ///
  /// Invalidation events in the graph (generally, filesystem changes) will cause cacheable Nodes
  /// to be retried here for up to `invalidation_timeout`.
  ///
  pub async fn get(&self, context: &N::Context, dst_node: N) -> Result<N::Item, N::Error> {
    match self.get_inner(context, dst_node, EdgeType::Strong).await {
      Ok(Some((res, _generation))) => Ok(res),
      Err(e) => Err(e),
      Ok(None) => unreachable!("A strong dependency cannot return None."),
    }
  }

  ///
  /// Identical to Get, but if a cycle would be created by the dependency, returns None instead.
  ///
  pub async fn get_weak(
    &self,
    context: &N::Context,
    dst_node: N,
  ) -> Result<Option<N::Item>, N::Error> {
    match self.get_inner(context, dst_node, EdgeType::Weak).await {
      Ok(Some((res, _generation))) => Ok(Some(res)),
      Ok(None) => Ok(None),
      Err(e) => Err(e),
    }
  }

  ///
  /// Return the value of the given Node. This is a synonym for `self.get(context, node)`, but it
  /// is expected to be used by callers requesting node values from the graph, while `self.get` is
  /// also used by Nodes to request dependencies..
  ///
  pub async fn create(&self, node: N, context: &N::Context) -> Result<N::Item, N::Error> {
    let result = self.get(context, node).await;
    // In the background, garbage collect edges.
    // NB: This could safely occur at any frequency: if it ever shows up in profiles, we could make
    // it optional based on how many edges are garbage.
    context.spawn({
      let context = context.clone();
      async move {
        context.graph().garbage_collect_edges();
      }
    });
    result
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
    let (res, generation) = self
      .get_inner(context, node, EdgeType::Strong)
      .await?
      .expect("A strong dependency cannot return None.");
    Ok((res, LastObserved(generation)))
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
  /// Gets the generations of the dependencies of the given EntryId at the given RunToken,
  /// (re)computing or cleaning them first if necessary.
  ///
  async fn dep_generations(
    &self,
    entry_id: EntryId,
    run_token: RunToken,
    context: &N::Context,
  ) -> Result<Vec<Generation>, N::Error> {
    let dep_nodes = {
      let inner = self.inner.lock();
      inner
        .pg
        .edges_directed(entry_id, Direction::Outgoing)
        .filter_map(|edge_ref| {
          if edge_ref.weight().1 == run_token {
            let entry = inner
              .entry_for_id(edge_ref.target())
              .unwrap_or_else(|| panic!("Dependency not present in Graph."))
              .clone();
            Some((edge_ref.weight().0, entry.node().clone()))
          } else {
            None
          }
        })
        .collect::<Vec<_>>()
    };
    let generations = dep_nodes
      .into_iter()
      .map(|(edge_type, node)| async move {
        Ok(
          self
            .get_inner(context, node, edge_type)
            .await?
            .map(|(_, generation)| generation),
        )
      })
      .collect::<Vec<_>>();
    // Weak edges might have returned None: we filter those out, and expect that it might cause the
    // Node to fail to be cleaned.
    Ok(
      future::try_join_all(generations)
        .await?
        .into_iter()
        .filter_map(std::convert::identity)
        .collect(),
    )
  }

  ///
  /// When the Executor finishes executing a Node it calls back to store the result value.
  /// Entry::complete uses the run_token to determine whether the Node changed while we were busy
  /// executing it, so that it can discard the work.
  ///
  fn complete(
    &self,
    context: &N::Context,
    entry_id: EntryId,
    run_token: RunToken,
    result: Option<Result<N::Item, N::Error>>,
  ) {
    let (entry, has_uncacheable_deps, has_weak_deps, dep_generations) = {
      let inner = self.inner.lock();
      let mut has_uncacheable_deps = false;
      let mut has_weak_deps = false;
      // Get the Generations of all dependencies of the Node. We can trust that these have not changed
      // since we began executing, as long as the entry's RunToken is still valid (confirmed in
      // Entry::complete).
      let dep_generations = inner
        .pg
        .edges_directed(entry_id, Direction::Outgoing)
        .filter_map(|edge_ref| {
          if edge_ref.weight().1 == run_token {
            if edge_ref.weight().0 == EdgeType::Weak {
              has_weak_deps = true;
            }
            // If a dependency is itself uncacheable or has uncacheable deps, this Node should
            // also complete as having uncacheable deps, independent of matching Generation values.
            // This is to allow for the behaviour that an uncacheable Node should always have "dirty"
            // (marked as UncacheableDependencies) dependents, transitively.
            let entry = inner.entry_for_id(edge_ref.target()).unwrap();
            if !entry.node().cacheable() || entry.has_uncacheable_deps() {
              has_uncacheable_deps = true;
            }

            Some(entry.generation())
          } else {
            None
          }
        })
        .collect();

      let entry = inner.entry_for_id(entry_id).unwrap().clone();
      (entry, has_uncacheable_deps, has_weak_deps, dep_generations)
    };

    // Attempt to complete the Node outside the graph lock.
    entry.complete(
      context,
      run_token,
      dep_generations,
      result,
      has_uncacheable_deps,
      has_weak_deps,
    );
  }

  ///
  /// Garbage collects all dependency edges that are not associated with the previous or current run
  /// of a Node. Node cleaning consumes the previous edges for an operation, so we preserve those.
  ///
  /// This is executed as a bulk operation, because individual edge removals take O(n), and bulk
  /// edge filtering is both more efficient, and possible to do asynchronously. This method also
  /// avoids the `retain_edges` method, which as of petgraph `0.4.5` uses individual edge removals
  /// under the hood, and is thus not much faster than removing them one by one.
  ///
  ///   See https://github.com/petgraph/petgraph/issues/299.
  ///
  pub fn garbage_collect_edges(&self) {
    let mut inner = self.inner.lock();
    inner.pg = inner.pg.filter_map(
      |_entry_id, node| Some(node.clone()),
      |edge_index, edge_weight| {
        let (edge_src_id, _) = inner.pg.edge_endpoints(edge_index).unwrap();
        // Retain the edge if it is for either the current or previous run of a Node.
        if inner.pg[edge_src_id]
          .run_token()
          .equals_current_or_previous(edge_weight.1)
        {
          Some(*edge_weight)
        } else {
          None
        }
      },
    );
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
    mut f: impl FnMut(&N, N::Item) -> (),
  ) {
    let inner = self.inner.lock();
    for (n, v) in inner.live_reachable(roots, context) {
      f(n, v);
    }
  }

  pub fn visit_live(&self, context: &N::Context, mut f: impl FnMut(&N, N::Item) -> ()) {
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
struct Walk<'a, N: Node, F: Fn(EdgeId) -> bool> {
  graph: &'a InnerGraph<N>,
  direction: Direction,
  deque: VecDeque<EntryId>,
  walked: HashSet<EntryId, FNV>,
  should_walk_edge: F,
}

impl<'a, N: Node + 'a, F: Fn(EdgeId) -> bool> Iterator for Walk<'a, N, F> {
  type Item = EntryId;

  fn next(&mut self) -> Option<Self::Item> {
    while let Some(id) = self.deque.pop_front() {
      // Visit this node and its neighbors if this node has not yet be visited and we aren't
      // stopping our walk at this node, based on if it satisfies the should_walk_edge.
      // This mechanism gives us a way to selectively dirty parts of the graph respecting node boundaries
      // like uncacheable nodes, which shouldn't be dirtied.
      if !self.walked.insert(id) {
        continue;
      }

      let should_walk_edge = &self.should_walk_edge;
      let direction = self.direction;
      self.deque.extend(
        self
          .graph
          .pg
          .edges_directed(id, self.direction)
          .filter_map(|edge_ref| {
            if should_walk_edge(edge_ref.id()) {
              let node = match direction {
                Direction::Outgoing => edge_ref.target(),
                Direction::Incoming => edge_ref.source(),
              };
              Some(node)
            } else {
              None
            }
          }),
      );
      return Some(id);
    }

    None
  }
}

#[cfg(test)]
mod tests;
