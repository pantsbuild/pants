// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

extern crate boxfuture;
extern crate fnv;
extern crate futures;
extern crate hashing;
extern crate petgraph;

mod entry;
mod node;

pub use entry::Entry;
use entry::{EntryKey, Generation, RunToken};

use std::collections::binary_heap::BinaryHeap;
use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::{File, OpenOptions};
use std::hash::BuildHasherDefault;
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use fnv::FnvHasher;

use futures::future::{self, Future};
use petgraph::graph::DiGraph;
use petgraph::visit::EdgeRef;
use petgraph::Direction;

use boxfuture::{BoxFuture, Boxable};
pub use node::{EntryId, Node, NodeContext, NodeError, NodeTracer, NodeVisualizer};

type FNV = BuildHasherDefault<FnvHasher>;

type PGraph<N> = DiGraph<Entry<N>, (), u32>;

#[derive(Debug, Eq, PartialEq)]
pub struct InvalidationResult {
  pub cleared: usize,
  pub dirtied: usize,
}

type Nodes<N> = HashMap<EntryKey<N>, EntryId>;

struct InnerGraph<N: Node> {
  nodes: Nodes<N>,
  pg: PGraph<N>,
}

impl<N: Node> InnerGraph<N> {
  fn entry_id(&self, node: &EntryKey<N>) -> Option<&EntryId> {
    self.nodes.get(node)
  }

  // TODO: Now that we never delete Entries, we should consider making this infalliable.
  fn entry_for_id(&self, id: EntryId) -> Option<&Entry<N>> {
    self.pg.node_weight(id)
  }

  fn entry_for_id_mut(&mut self, id: EntryId) -> Option<&mut Entry<N>> {
    self.pg.node_weight_mut(id)
  }

  fn unsafe_entry_for_id(&self, id: EntryId) -> &Entry<N> {
    self
      .pg
      .node_weight(id)
      .expect("The unsafe_entry_for_id method should only be used in read-only methods!")
  }

  fn ensure_entry(&mut self, node: EntryKey<N>) -> EntryId {
    InnerGraph::ensure_entry_internal(&mut self.pg, &mut self.nodes, node)
  }

  fn ensure_entry_internal(pg: &mut PGraph<N>, nodes: &mut Nodes<N>, node: EntryKey<N>) -> EntryId {
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
  /// Returns true if a cycle would be created by adding an edge from src->dst.
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
    self.walk(roots, direction).any(|eid| eid == needle)
  }

  ///
  /// Begins a topological Walk from the given roots.
  ///
  fn walk(&self, roots: VecDeque<EntryId>, direction: Direction) -> Walk<N> {
    Walk {
      graph: self,
      direction: direction,
      deque: roots,
      walked: HashSet::default(),
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
      .filter_map(|(entry, &entry_id)| {
        if predicate(entry.content()) {
          Some(entry_id)
        } else {
          None
        }
      })
      .collect();
    // And their transitive dependencies, which will be dirtied.
    let transitive_ids: Vec<_> = self
      .walk(root_ids.iter().cloned().collect(), Direction::Incoming)
      .filter(|eid| !root_ids.contains(eid))
      .collect();

    let invalidation_result = InvalidationResult {
      cleared: root_ids.len(),
      dirtied: transitive_ids.len(),
    };

    // Clear roots and remove their outbound edges.
    for id in &root_ids {
      self.pg.node_weight_mut(*id).map(|entry| entry.clear());
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
  ) -> io::Result<()> {
    let file = try!(File::create(path));
    let mut f = BufWriter::new(file);

    try!(f.write_all(b"digraph plans {\n"));
    try!(f.write_fmt(format_args!(
      "  node[colorscheme={}];\n",
      visualizer.color_scheme()
    ),));
    try!(f.write_all(b"  concentrate=true;\n"));
    try!(f.write_all(b"  rankdir=TB;\n"));

    let mut format_color = |entry: &Entry<N>| visualizer.color(entry);

    let root_entries = roots
      .iter()
      .filter_map(|n| self.entry_id(&EntryKey::Valid(n.clone())))
      .cloned()
      .collect();

    for eid in self.walk(root_entries, Direction::Outgoing) {
      let entry = self.unsafe_entry_for_id(eid);
      let node_str = entry.format();

      // Write the node header.
      try!(f.write_fmt(format_args!(
        "  \"{}\" [style=filled, fillcolor={}];\n",
        node_str,
        format_color(entry)
      )));

      for dep_id in self.pg.neighbors(eid) {
        let dep_entry = self.unsafe_entry_for_id(dep_id);

        // Write an entry per edge.
        let dep_str = dep_entry.format();
        try!(f.write_fmt(format_args!("    \"{}\" -> \"{}\"\n", node_str, dep_str)));
      }
    }

    try!(f.write_all(b"}\n"));
    Ok(())
  }

  fn trace<T: NodeTracer<N>>(&self, roots: &[N], file_path: &Path) -> Result<(), String> {
    let root_ids: HashSet<EntryId, FNV> = roots
      .into_iter()
      .filter_map(|nk| self.entry_id(&EntryKey::Valid(nk.clone())))
      .cloned()
      .collect();

    // Find all bottom Nodes for the trace by walking recursively under the roots.
    let bottom_nodes = {
      let mut queue: VecDeque<_> = root_ids.iter().cloned().collect();
      let mut visited: HashSet<EntryId, FNV> = HashSet::default();
      let mut bottom_nodes = Vec::new();
      while let Some(id) = queue.pop_front() {
        if !visited.insert(id) {
          continue;
        }

        // If all dependencies are bottom nodes, then we represent a failure.
        let mut non_bottom_deps = self
          .pg
          .neighbors_directed(id, Direction::Outgoing)
          .filter(|dep_id| !T::is_bottom(self.unsafe_entry_for_id(*dep_id).peek()))
          .peekable();

        if non_bottom_deps.peek().is_none() {
          bottom_nodes.push(id);
        } else {
          // Otherwise, continue recursing on `rest`.
          queue.extend(non_bottom_deps);
        }
      }
      bottom_nodes
    };

    // Invert the graph into a evenly-weighted dependent graph by cloning it and stripping out
    // the Nodes (to avoid cloning them), adding equal edge weights, and then reversing it.
    // Because we do not remove any Nodes or edges, all EntryIds remain stable.
    let dependent_graph = {
      let mut dg = self
        .pg
        .filter_map(|_, _| Some(()), |_, _| Some(1.0))
        .clone();
      dg.reverse();
      dg
    };

    // Render the shortest path through the dependent graph to any root for each bottom_node.
    for bottom_node in bottom_nodes {
      // We use Bellman Ford because it actually records paths, unlike Dijkstra's.
      let (path_weights, paths) = petgraph::algo::bellman_ford(&dependent_graph, bottom_node)
        .unwrap_or_else(|e| {
          panic!(
            "There should not be any negative edge weights. Got: {:?}",
            e
          )
        });

      // Find the root with the shortest path weight.
      let minimum_path_id = root_ids
        .iter()
        .min_by_key(|root_id| path_weights[root_id.index()] as usize)
        .ok_or_else(|| format!("Encountered a Node that was not reachable from any roots."))?;

      // Collect the path by walking through the `paths` Vec, which contains the indexes of
      // predecessor Nodes along a path to the bottom Node.
      let path = {
        let mut next_id = *minimum_path_id;
        let mut path = Vec::new();
        path.push(next_id);
        while let Some(current_id) = paths[next_id.index()] {
          path.push(current_id);
          if current_id == bottom_node {
            break;
          }
          next_id = current_id;
        }
        path
      };

      // Render the path.
      self
        .trace_render_path_to_file::<T>(&path, file_path)
        .map_err(|e| format!("Failed to render trace to {:?}: {}", file_path, e))?;
    }

    Ok(())
  }

  ///
  /// Renders a Graph path to the given file path.
  ///
  fn trace_render_path_to_file<T: NodeTracer<N>>(
    &self,
    path: &[EntryId],
    file_path: &Path,
  ) -> io::Result<()> {
    let file = try!(OpenOptions::new().append(true).open(file_path));
    let mut f = BufWriter::new(file);

    let _format = |eid: EntryId, depth: usize, is_last: bool| -> String {
      let entry = self.unsafe_entry_for_id(eid);
      let indent = "  ".repeat(depth);
      let output = format!("{}Computing {}", indent, entry.node().format());
      if is_last {
        format!(
          "{}\n{}  {}",
          output,
          indent,
          T::state_str(&indent, entry.peek())
        )
      } else {
        output
      }
    };

    let mut path_iter = path.iter().enumerate().peekable();
    while let Some((depth, id)) = path_iter.next() {
      try!(writeln!(
        &mut f,
        "{}",
        _format(*id, depth, path_iter.peek().is_none())
      ));
    }

    try!(f.write_all(b"\n"));
    Ok(())
  }

  ///
  /// Computes the K longest running entries in a Graph-aware fashion.
  ///
  fn heavy_hitters(&self, roots: &[N], k: usize) -> Vec<(String, Duration)> {
    let now = Instant::now();
    let queue_entry = |id| {
      self
        .entry_for_id(id)
        .and_then(|entry| entry.current_running_duration(&now))
        .map(|d| (d, id))
    };

    let mut queue: BinaryHeap<(Duration, EntryId)> = BinaryHeap::with_capacity(k);
    let mut visited: HashSet<EntryId, FNV> = HashSet::default();
    let mut res = Vec::new();

    // Initialize the queue.
    queue.extend(
      roots
        .iter()
        .filter_map(|nk| self.entry_id(&EntryKey::Valid(nk.clone())))
        .filter_map(|eid| queue_entry(*eid)),
    );

    while let Some((duration, id)) = queue.pop() {
      if !visited.insert(id) {
        continue;
      }

      // Compute the running dependencies of the node.
      let mut deps = self
        .pg
        .neighbors_directed(id, Direction::Outgoing)
        .filter_map(&queue_entry)
        .peekable();

      if deps.peek().is_none() {
        // If the entry has no running deps, it is a leaf. Emit it.
        res.push((self.unsafe_entry_for_id(id).node().format(), duration));
        if res.len() >= k {
          break;
        }
      } else {
        // Otherwise, assume it is blocked on the running dependencies and expand them.
        queue.extend(deps);
      }
    }

    res
  }

  fn reachable_digest_count(&self, roots: &[N]) -> usize {
    let root_ids = roots
      .iter()
      .cloned()
      .filter_map(|node| self.entry_id(&EntryKey::Valid(node)))
      .cloned()
      .collect();
    self
      .digests_internal(self.walk(root_ids, Direction::Outgoing).collect())
      .count()
  }

  fn all_digests(&self) -> Vec<hashing::Digest> {
    self
      .digests_internal(self.pg.node_indices().collect())
      .collect()
  }

  fn digests_internal<'g>(
    &'g self,
    entryids: Vec<EntryId>,
  ) -> impl Iterator<Item = hashing::Digest> + 'g {
    entryids
      .into_iter()
      .filter_map(move |eid| self.entry_for_id(eid))
      .filter_map(|entry| match entry.peek() {
        Some(Ok(item)) => N::digest(item),
        _ => None,
      })
  }
}

///
/// A DAG (enforced on mutation) of Entries.
///
pub struct Graph<N: Node> {
  inner: Mutex<InnerGraph<N>>,
}

impl<N: Node> Graph<N> {
  pub fn new() -> Graph<N> {
    let inner = InnerGraph {
      nodes: HashMap::default(),
      pg: DiGraph::new(),
    };
    Graph {
      inner: Mutex::new(inner),
    }
  }

  pub fn len(&self) -> usize {
    let inner = self.inner.lock().unwrap();
    inner.nodes.len()
  }

  ///
  /// In the context of the given src Node, declare a dependency on the given dst Node and
  /// begin its execution if it has not already started.
  ///
  pub fn get<C>(&self, src_id: EntryId, context: &C, dst_node: N) -> BoxFuture<N::Item, N::Error>
  where
    C: NodeContext<Node = N>,
  {
    let (maybe_entry, entry_id) = {
      // Get or create the destination, and then insert the dep and return its state.
      let mut inner = self.inner.lock().unwrap();
      let dst_id = {
        // TODO: doing cycle detection under the lock... unfortunate, but probably unavoidable
        // without a much more complicated algorithm.
        let potential_dst_id = inner.ensure_entry(EntryKey::Valid(dst_node.clone()));
        if inner.detect_cycle(src_id, potential_dst_id) {
          // Cyclic dependency: declare a dependency on a copy of the Node that is marked Cyclic.
          inner.ensure_entry(EntryKey::Cyclic(dst_node))
        } else {
          // Valid dependency.
          potential_dst_id
        }
      };
      inner.pg.add_edge(src_id, dst_id, ());
      (inner.entry_for_id(dst_id).cloned(), dst_id)
    };

    // Declare the dep, and return the state of the destination.
    if let Some(mut entry) = maybe_entry {
      entry.get(context, entry_id).map(|(res, _)| res).to_boxed()
    } else {
      future::err(N::Error::invalidated()).to_boxed()
    }
  }

  ///
  /// Create the given Node if it does not already exist.
  ///
  pub fn create<C>(&self, node: N, context: &C) -> BoxFuture<N::Item, N::Error>
  where
    C: NodeContext<Node = N>,
  {
    let (maybe_entry, entry_id) = {
      let mut inner = self.inner.lock().unwrap();
      let id = inner.ensure_entry(EntryKey::Valid(node));
      (inner.entry_for_id(id).cloned(), id)
    };
    if let Some(mut entry) = maybe_entry {
      entry.get(context, entry_id).map(|(res, _)| res).to_boxed()
    } else {
      future::err(N::Error::invalidated()).to_boxed()
    }
  }

  ///
  /// Gets the generations of the dependencies of the given EntryId, (re)computing or cleaning
  /// them first if necessary.
  ///
  fn dep_generations<C>(
    &self,
    entry_id: EntryId,
    context: &C,
  ) -> BoxFuture<Vec<Generation>, N::Error>
  where
    C: NodeContext<Node = N>,
  {
    let mut inner = self.inner.lock().unwrap();
    let dep_ids = inner
      .pg
      .neighbors_directed(entry_id, Direction::Outgoing)
      .collect::<Vec<_>>();

    future::join_all(
      dep_ids
        .into_iter()
        .map(|dep_id| {
          let entry = inner
            .entry_for_id_mut(dep_id)
            .unwrap_or_else(|| panic!("Dependency not present in Graph."));
          entry
            .get(context, dep_id)
            .map(|(_, generation)| generation)
            .to_boxed()
        })
        .collect::<Vec<_>>(),
    ).to_boxed()
  }

  ///
  /// Clears the dependency edges of the given EntryId if the RunToken matches.
  ///
  fn clear_deps(&self, entry_id: EntryId, run_token: RunToken) {
    let mut inner = self.inner.lock().unwrap();
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
  fn complete<C>(
    &self,
    context: &C,
    entry_id: EntryId,
    run_token: RunToken,
    result: Option<Result<N::Item, N::Error>>,
  ) where
    C: NodeContext<Node = N>,
  {
    let (entry, entry_id, dep_generations) = {
      let mut inner = self.inner.lock().unwrap();
      // Get the Generations of all dependencies of the Node. We can trust that these have not changed
      // since we began executing, as long as we are not currently marked dirty (see the method doc).
      let dep_generations = inner
        .pg
        .neighbors_directed(entry_id, Direction::Outgoing)
        .filter_map(|dep_id| inner.entry_for_id(dep_id))
        .map(|entry| entry.generation())
        .collect();
      (
        inner.entry_for_id(entry_id).cloned(),
        entry_id,
        dep_generations,
      )
    };
    if let Some(mut entry) = entry {
      let mut inner = self.inner.lock().unwrap();
      entry.complete(
        context,
        entry_id,
        run_token,
        dep_generations,
        result,
        &mut inner,
      );
    }
  }

  ///
  /// Clears the state of all Nodes in the Graph by dropping their state fields.
  ///
  pub fn clear(&self) {
    let mut inner = self.inner.lock().unwrap();
    inner.clear()
  }

  pub fn invalidate_from_roots<P: Fn(&N) -> bool>(&self, predicate: P) -> InvalidationResult {
    let mut inner = self.inner.lock().unwrap();
    inner.invalidate_from_roots(predicate)
  }

  pub fn trace<T: NodeTracer<N>>(&self, roots: &[N], path: &Path) -> Result<(), String> {
    let inner = self.inner.lock().unwrap();
    inner.trace::<T>(roots, path)
  }

  pub fn visualize<V: NodeVisualizer<N>>(
    &self,
    visualizer: V,
    roots: &[N],
    path: &Path,
  ) -> io::Result<()> {
    let inner = self.inner.lock().unwrap();
    inner.visualize(visualizer, roots, path)
  }

  pub fn heavy_hitters(&self, roots: &[N], k: usize) -> Vec<(String, Duration)> {
    let inner = self.inner.lock().unwrap();
    inner.heavy_hitters(roots, k)
  }

  pub fn reachable_digest_count(&self, roots: &[N]) -> usize {
    let inner = self.inner.lock().unwrap();
    inner.reachable_digest_count(roots)
  }

  pub fn all_digests(&self) -> Vec<hashing::Digest> {
    let inner = self.inner.lock().unwrap();
    inner.all_digests()
  }
}

///
/// Represents the state of a particular topological walk through a Graph. Implements Iterator and
/// has the same lifetime as the Graph itself.
///
struct Walk<'a, N: Node + 'a> {
  graph: &'a InnerGraph<N>,
  direction: Direction,
  deque: VecDeque<EntryId>,
  walked: HashSet<EntryId, FNV>,
}

impl<'a, N: Node + 'a> Iterator for Walk<'a, N> {
  type Item = EntryId;

  fn next(&mut self) -> Option<Self::Item> {
    while let Some(id) = self.deque.pop_front() {
      if !self.walked.insert(id) {
        continue;
      }

      // Queue the neighbors of the entry and then return it.
      self
        .deque
        .extend(self.graph.pg.neighbors_directed(id, self.direction));
      return Some(id);
    }

    None
  }
}

#[cfg(test)]
mod tests {
  extern crate rand;

  use std::cmp;
  use std::collections::HashSet;
  use std::sync::{mpsc, Arc, Mutex};
  use std::thread;
  use std::time::Duration;

  use boxfuture::{BoxFuture, Boxable};
  use futures::future::{self, Future};
  use hashing::Digest;

  use self::rand::Rng;

  use super::{EntryId, Graph, InvalidationResult, Node, NodeContext, NodeError};

  #[test]
  fn create() {
    let graph = Arc::new(Graph::new());
    let context = TContext::new(0, graph.clone());
    assert_eq!(
      graph.create(TNode(2), &context).wait(),
      Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
    );
  }

  #[test]
  fn invalidate_and_clean() {
    let graph = Arc::new(Graph::new());
    let context = TContext::new(0, graph.clone());

    // Create three nodes.
    assert_eq!(
      graph.create(TNode(2), &context).wait(),
      Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
    );
    assert_eq!(context.runs(), vec![TNode(2), TNode(1), TNode(0)]);

    // Clear the middle Node, which dirties the upper node.
    assert_eq!(
      graph.invalidate_from_roots(|&TNode(n)| n == 1),
      InvalidationResult {
        cleared: 1,
        dirtied: 1
      }
    );

    // Confirm that the cleared Node re-runs, and the upper node is cleaned without re-running.
    assert_eq!(
      graph.create(TNode(2), &context).wait(),
      Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
    );
    assert_eq!(context.runs(), vec![TNode(2), TNode(1), TNode(0), TNode(1)]);
  }

  #[test]
  fn invalidate_and_rerun() {
    let graph = Arc::new(Graph::new());
    let context0 = TContext::new(0, graph.clone());

    // Create three nodes.
    assert_eq!(
      graph.create(TNode(2), &context0).wait(),
      Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
    );
    assert_eq!(context0.runs(), vec![TNode(2), TNode(1), TNode(0)]);

    // Clear the middle Node, which dirties the upper node.
    assert_eq!(
      graph.invalidate_from_roots(|&TNode(n)| n == 1),
      InvalidationResult {
        cleared: 1,
        dirtied: 1
      }
    );

    // Request with a new context, which will cause both the middle and upper nodes to rerun since
    // their input values have changed.
    let context1 = TContext::new(1, graph.clone());
    assert_eq!(
      graph.create(TNode(2), &context1).wait(),
      Ok(vec![T(0, 0), T(1, 1), T(2, 1)])
    );
    assert_eq!(context1.runs(), vec![TNode(1), TNode(2)]);
  }

  #[test]
  fn invalidate_with_changed_dependencies() {
    let graph = Arc::new(Graph::new());
    let context = TContext::new(0, graph.clone());

    // Create three nodes.
    assert_eq!(
      graph.create(TNode(2), &context).wait(),
      Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
    );

    // Clear the middle Node, which dirties the upper node.
    assert_eq!(
      graph.invalidate_from_roots(|&TNode(n)| n == 1),
      InvalidationResult {
        cleared: 1,
        dirtied: 1
      }
    );

    // Request with a new context that truncates execution at the middle Node.
    let context = TContext::new_with_stop_at(0, TNode(1), graph.clone());
    assert_eq!(
      graph.create(TNode(2), &context).wait(),
      Ok(vec![T(1, 0), T(2, 0)])
    );

    // Confirm that dirtying the bottom Node does not affect the middle/upper Nodes, which no
    // longer depend on it.
    assert_eq!(
      graph.invalidate_from_roots(|&TNode(n)| n == 0),
      InvalidationResult {
        cleared: 1,
        dirtied: 0,
      }
    );
  }

  #[test]
  fn invalidate_randomly() {
    let graph = Arc::new(Graph::new());

    let invalidations = 10;
    let sleep_per_invalidation = Duration::from_millis(100);
    let range = 100;

    // Spawn a background thread to randomly invalidate in the relevant range. Hold its handle so
    // it doesn't detach.
    let graph2 = graph.clone();
    let (send, recv) = mpsc::channel();
    let _join = thread::spawn(move || {
      let mut rng = rand::thread_rng();
      let mut invalidations = invalidations;
      while invalidations > 0 {
        invalidations -= 1;

        // Invalidate a random node in the graph.
        let candidate = rng.gen_range(0, range);
        graph2.invalidate_from_roots(|&TNode(n)| n == candidate);

        thread::sleep(sleep_per_invalidation);
      }
      send.send(()).unwrap();
    });

    // Continuously re-request the root with increasing context values, and assert that Node and
    // context values are ascending.
    let mut iterations = 0;
    let mut max_distinct_context_values = 0;
    loop {
      let context = TContext::new(iterations, graph.clone());

      // Compute the root, and validate its output.
      let node_output = match graph.create(TNode(range), &context).wait() {
        Ok(output) => output,
        Err(TError::Invalidated) => {
          // Some amnount of concurrent invalidation is expected: retry.
          continue;
        }
        Err(e) => panic!(
          "Did not expect any errors other than Invalidation. Got: {:?}",
          e
        ),
      };
      max_distinct_context_values = cmp::max(
        max_distinct_context_values,
        TNode::validate(&node_output).unwrap(),
      );

      // Poll the channel to see whether the background thread has exited.
      if let Ok(_) = recv.try_recv() {
        break;
      }
      iterations += 1;
    }

    assert!(
      max_distinct_context_values > 1,
      "In {} iterations, observed a maximum of {} distinct context values.",
      iterations,
      max_distinct_context_values
    );
  }

  ///
  /// A token containing the id of a Node and the id of a Context, respectively. Has a short name
  /// to minimize the verbosity of tests.
  ///
  #[derive(Clone, Debug, Eq, PartialEq)]
  struct T(usize, usize);

  ///
  /// A node that builds a Vec of tokens by recursively requesting itself and appending its value
  /// to the result.
  ///
  #[derive(Clone, Debug, Eq, Hash, PartialEq)]
  struct TNode(usize);
  impl Node for TNode {
    type Context = TContext;
    type Item = Vec<T>;
    type Error = TError;

    fn run(self, context: TContext) -> BoxFuture<Vec<T>, TError> {
      context.ran(self.clone());
      let depth = self.0;
      let token = T(depth, context.id());
      if depth > 0 && !context.stop_at(&self) {
        context
          .get(TNode(depth - 1))
          .map(move |mut v| {
            v.push(token);
            v
          })
          .to_boxed()
      } else {
        future::ok(vec![token]).to_boxed()
      }
    }

    fn format(&self) -> String {
      format!("{:?}", self)
    }

    fn digest(_result: Self::Item) -> Option<Digest> {
      None
    }
  }

  impl TNode {
    ///
    /// Validates the given TNode output. Both node ids and context ids should increase left to
    /// right: node ids monotonically, and context ids non-monotonically.
    ///
    /// Valid:
    ///   (0,0), (1,1), (2,2), (3,3)
    ///   (0,0), (1,0), (2,1), (3,1)
    ///
    /// Invalid:
    ///   (0,0), (1,1), (2,1), (3,0)
    ///   (0,0), (1,0), (2,0), (1,0)
    ///
    /// If successful, returns the count of distinct context ids in the path.
    ///
    fn validate(output: &Vec<T>) -> Result<usize, String> {
      let (node_ids, context_ids): (Vec<_>, Vec<_>) = output
        .iter()
        .map(|&T(node_id, context_id)| {
          // We cast to isize to allow comparison to -1.
          (node_id as isize, context_id)
        })
        .unzip();
      // Confirm monotonically ordered.
      let mut previous: isize = -1;
      for node_id in node_ids {
        if previous + 1 != node_id {
          return Err(format!(
            "Node ids in {:?} were not monotonically ordered.",
            output
          ));
        }
        previous = node_id;
      }
      // Confirm ordered (non-monotonically).
      let mut previous: usize = 0;
      for &context_id in &context_ids {
        if previous > context_id {
          return Err(format!("Context ids in {:?} were not ordered.", output));
        }
        previous = context_id;
      }

      Ok(context_ids.into_iter().collect::<HashSet<_>>().len())
    }
  }

  ///
  /// A context that keeps a record of Nodes that have been run.
  ///
  #[derive(Clone)]
  struct TContext {
    id: usize,
    stop_at: Option<TNode>,
    graph: Arc<Graph<TNode>>,
    runs: Arc<Mutex<Vec<TNode>>>,
    entry_id: Option<EntryId>,
  }
  impl NodeContext for TContext {
    type Node = TNode;
    fn clone_for(&self, entry_id: EntryId) -> TContext {
      TContext {
        id: self.id,
        stop_at: self.stop_at.clone(),
        graph: self.graph.clone(),
        runs: self.runs.clone(),
        entry_id: Some(entry_id),
      }
    }

    fn graph(&self) -> &Graph<TNode> {
      &self.graph
    }

    fn spawn<F>(&self, future: F)
    where
      F: Future<Item = (), Error = ()> + Send + 'static,
    {
      // Avoids introducing a dependency on a threadpool.
      thread::spawn(move || {
        future.wait().unwrap();
      });
    }
  }

  impl TContext {
    fn new(id: usize, graph: Arc<Graph<TNode>>) -> TContext {
      TContext {
        id,
        stop_at: None,
        graph,
        runs: Arc::new(Mutex::new(Vec::new())),
        entry_id: None,
      }
    }

    fn new_with_stop_at(id: usize, stop_at: TNode, graph: Arc<Graph<TNode>>) -> TContext {
      TContext {
        id,
        stop_at: Some(stop_at),
        graph,
        runs: Arc::new(Mutex::new(Vec::new())),
        entry_id: None,
      }
    }

    fn id(&self) -> usize {
      self.id
    }

    fn get(&self, dst: TNode) -> BoxFuture<Vec<T>, TError> {
      self.graph.get(self.entry_id.unwrap(), self, dst)
    }

    fn ran(&self, node: TNode) {
      let mut runs = self.runs.lock().unwrap();
      runs.push(node);
    }

    fn stop_at(&self, node: &TNode) -> bool {
      Some(node) == self.stop_at.as_ref()
    }

    fn runs(&self) -> Vec<TNode> {
      self.runs.lock().unwrap().clone()
    }
  }

  #[derive(Clone, Debug, Eq, PartialEq)]
  enum TError {
    Cyclic,
    Invalidated,
  }
  impl NodeError for TError {
    fn invalidated() -> Self {
      TError::Invalidated
    }

    fn cyclic() -> Self {
      TError::Cyclic
    }
  }
}
