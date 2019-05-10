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
  clippy::single_match_else,
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

use hashing;

use petgraph;

mod entry;
mod node;

pub use crate::entry::Entry;
use crate::entry::{EntryKey, Generation, RunToken};

use std::collections::binary_heap::BinaryHeap;
use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::{File, OpenOptions};
use std::hash::BuildHasherDefault;
use std::io::{self, BufWriter, Write};
use std::path::Path;
use std::time::{Duration, Instant};

use fnv::FnvHasher;

use futures::future::{self, Future};
use indexmap::IndexSet;
use log::{info, trace, warn};
use parking_lot::Mutex;
use petgraph::graph::DiGraph;
use petgraph::visit::EdgeRef;
use petgraph::Direction;

pub use crate::node::{EntryId, Node, NodeContext, NodeError, NodeTracer, NodeVisualizer};
use boxfuture::{BoxFuture, Boxable};

type FNV = BuildHasherDefault<FnvHasher>;

type PGraph<N> = DiGraph<Entry<N>, f32, u32>;

#[derive(Debug, Eq, PartialEq)]
pub struct InvalidationResult {
  pub cleared: usize,
  pub dirtied: usize,
}

type Nodes<N> = HashMap<EntryKey<N>, EntryId>;

struct InnerGraph<N: Node> {
  nodes: Nodes<N>,
  pg: PGraph<N>,
  /// A Graph that is marked `draining:True` will not allow the creation of new `Nodes`. But
  /// while draining, any Nodes that exist in the Graph will continue to run until/unless they
  /// attempt to get/create new Nodes.
  draining: bool,
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
  /// Returns a path which would cause the cycle if an edge were added from src to dst, or None if
  /// no cycle would be created.
  ///
  /// This strongly optimizes for the case of no cycles. If cycles are detected, this is very
  /// expensive to call.
  ///
  fn report_cycle(&self, src_id: EntryId, dst_id: EntryId) -> Option<Vec<Entry<N>>> {
    if src_id == dst_id {
      return Some(vec![self.entry_for_id(src_id).unwrap().clone()]);
    }
    if !self.detect_cycle(src_id, dst_id) {
      return None;
    }
    Self::shortest_path(&self.pg, dst_id, src_id).map(|path| {
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
    self.walk(roots, direction).any(|eid| eid == needle)
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
  /// Begins a topological Walk from the given roots.
  ///
  fn walk(&self, roots: VecDeque<EntryId>, direction: Direction) -> Walk<'_, N> {
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
      f.write_fmt(format_args!(
        "  \"{}\" [style=filled, fillcolor={}];\n",
        node_str,
        format_color(entry)
      ))?;

      for dep_id in self.pg.neighbors(eid) {
        let dep_entry = self.unsafe_entry_for_id(dep_id);

        // Write an entry per edge.
        let dep_str = dep_entry.format();
        f.write_fmt(format_args!("    \"{}\" -> \"{}\"\n", node_str, dep_str))?;
      }
    }

    f.write_all(b"}\n")?;
    Ok(())
  }

  fn trace<T: NodeTracer<N>>(&self, roots: &[N], file_path: &Path) -> Result<(), String> {
    let root_ids: IndexSet<EntryId, FNV> = roots
      .iter()
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
        .ok_or_else(|| "Encountered a Node that was not reachable from any roots.".to_owned())?;

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
    let file = OpenOptions::new().append(true).open(file_path)?;
    let mut f = BufWriter::new(file);

    let format = |eid: EntryId, depth: usize, is_last: bool| -> String {
      let entry = self.unsafe_entry_for_id(eid);
      let indent = "  ".repeat(depth);
      let output = format!("{}Computing {}", indent, entry.node());
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
      writeln!(&mut f, "{}", format(*id, depth, path_iter.peek().is_none()))?;
    }

    f.write_all(b"\n")?;
    Ok(())
  }

  ///
  /// Computes the K longest running entries in a Graph-aware fashion.
  ///
  fn heavy_hitters(&self, roots: &[N], k: usize) -> HashMap<String, Duration> {
    let now = Instant::now();
    let queue_entry = |id| {
      self
        .entry_for_id(id)
        .and_then(|entry| entry.current_running_duration(now))
        .map(|d| (d, id))
    };

    let mut queue: BinaryHeap<(Duration, EntryId)> = BinaryHeap::with_capacity(k);
    let mut visited: HashSet<EntryId, FNV> = HashSet::default();
    let mut res = HashMap::new();

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
        res.insert(format!("{}", self.unsafe_entry_for_id(id).node()), duration);
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
      draining: false,
      nodes: HashMap::default(),
      pg: DiGraph::new(),
    };
    Graph {
      inner: Mutex::new(inner),
    }
  }

  pub fn len(&self) -> usize {
    let inner = self.inner.lock();
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
    let maybe_entry_and_id = {
      // Get or create the destination, and then insert the dep and return its state.
      let mut inner = self.inner.lock();
      if inner.draining {
        None
      } else {
        let dst_id = {
          // TODO: doing cycle detection under the lock... unfortunate, but probably unavoidable
          // without a much more complicated algorithm.
          let potential_dst_id = inner.ensure_entry(EntryKey::Valid(dst_node.clone()));
          match Self::detect_cycle(src_id, potential_dst_id, &mut inner) {
            Ok(true) => {
              // Cyclic dependency: declare a dependency on a copy of the Node that is marked Cyclic.
              inner.ensure_entry(EntryKey::Cyclic(dst_node))
            }
            Ok(false) => {
              // Valid dependency.
              trace!(
                "Adding dependency from {:?} to {:?}",
                inner.entry_for_id(src_id).unwrap().node(),
                inner.entry_for_id(potential_dst_id).unwrap().node()
              );
              potential_dst_id
            }
            Err(err) => return futures::future::err(err).to_boxed(),
          }
        };
        // All edges get a weight of 1.0 so that we can Bellman-Ford over the graph, treating each
        // edge as having equal weight.
        inner.pg.add_edge(src_id, dst_id, 1.0);
        inner
          .entry_for_id(dst_id)
          .cloned()
          .map(|entry| (entry, dst_id))
      }
    };

    // Declare the dep, and return the state of the destination.
    if let Some((mut entry, entry_id)) = maybe_entry_and_id {
      entry.get(context, entry_id).map(|(res, _)| res).to_boxed()
    } else {
      future::err(N::Error::invalidated()).to_boxed()
    }
  }

  fn detect_cycle(
    src_id: EntryId,
    potential_dst_id: EntryId,
    inner: &mut InnerGraph<N>,
  ) -> Result<bool, N::Error> {
    let mut counter = 0;
    loop {
      // Find one cycle if any cycles exist.
      if let Some(cycle_path) = inner.report_cycle(src_id, potential_dst_id) {
        // See if the cycle contains any dirty nodes. If there are dirty nodes, we can try clearing
        // them, and then check if there are still any cycles in the graph.
        let dirty_nodes: HashSet<_> = cycle_path
          .iter()
          .filter(|n| n.may_have_dirty_edges())
          .map(|n| n.node().clone())
          .collect();
        if dirty_nodes.is_empty() {
          // We detected a cycle with no dirty nodes - there's a cycle and there's nothing we can do
          // to remove it.
          info!(
            "Detected cycle considering adding edge from {:?} to {:?}; existing path: {:?}",
            inner.entry_for_id(src_id).unwrap(),
            inner.entry_for_id(potential_dst_id).unwrap(),
            cycle_path
          );
          return Ok(true);
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
          return Err(N::Error::cyclic());
        }
        // Clear the dirty nodes, removing the edges from them, and try again.
        inner.invalidate_from_roots(|node| dirty_nodes.contains(node));
      } else {
        return Ok(false);
      }
    }
  }

  ///
  /// Create the given Node if it does not already exist.
  ///
  pub fn create<C>(&self, node: N, context: &C) -> BoxFuture<N::Item, N::Error>
  where
    C: NodeContext<Node = N>,
  {
    let maybe_entry_and_id = {
      let mut inner = self.inner.lock();
      if inner.draining {
        None
      } else {
        let id = inner.ensure_entry(EntryKey::Valid(node));
        inner.entry_for_id(id).cloned().map(|entry| (entry, id))
      }
    };
    if let Some((mut entry, entry_id)) = maybe_entry_and_id {
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
    let mut inner = self.inner.lock();
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
    )
    .to_boxed()
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
  /// As an example, if generation 0 or X depends on A and B, and generation 1 of X depends on C,
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
      let inner = self.inner.lock();
      // Get the Generations of all dependencies of the Node. We can trust that these have not changed
      // since we began executing, as long as we are not currently marked dirty (see the method doc).
      let dep_generations = inner
        .pg
        .neighbors_directed(entry_id, Direction::Outgoing)
        .filter_map(|dep_id| inner.entry_for_id(dep_id))
        .map(Entry::generation)
        .collect();
      (
        inner.entry_for_id(entry_id).cloned(),
        entry_id,
        dep_generations,
      )
    };
    if let Some(mut entry) = entry {
      let mut inner = self.inner.lock();
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
    let mut inner = self.inner.lock();
    inner.clear()
  }

  pub fn invalidate_from_roots<P: Fn(&N) -> bool>(&self, predicate: P) -> InvalidationResult {
    let mut inner = self.inner.lock();
    inner.invalidate_from_roots(predicate)
  }

  pub fn trace<T: NodeTracer<N>>(&self, roots: &[N], path: &Path) -> Result<(), String> {
    let inner = self.inner.lock();
    inner.trace::<T>(roots, path)
  }

  pub fn visualize<V: NodeVisualizer<N>>(
    &self,
    visualizer: V,
    roots: &[N],
    path: &Path,
  ) -> io::Result<()> {
    let inner = self.inner.lock();
    inner.visualize(visualizer, roots, path)
  }

  pub fn heavy_hitters(&self, roots: &[N], k: usize) -> HashMap<String, Duration> {
    let inner = self.inner.lock();
    inner.heavy_hitters(roots, k)
  }

  pub fn reachable_digest_count(&self, roots: &[N]) -> usize {
    let inner = self.inner.lock();
    inner.reachable_digest_count(roots)
  }

  pub fn all_digests(&self) -> Vec<hashing::Digest> {
    let inner = self.inner.lock();
    inner.all_digests()
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

  ///
  /// Marks this Graph with the given draining status. If the Graph already has a matching
  /// draining status, then the operation will return an Err.
  ///
  /// This is an independent operation from acquiring exclusive access to the Graph
  /// (`with_exclusive`), because once exclusive access has been acquired, threads attempting to
  /// access the Graph would wait to acquire the lock, rather than acquiring and then failing fast
  /// as we'd like them to while `draining:True`.
  ///
  pub fn mark_draining(&self, draining: bool) -> Result<(), ()> {
    let mut inner = self.inner.lock();
    if inner.draining == draining {
      Err(())
    } else {
      inner.draining = draining;
      Ok(())
    }
  }
}

///
/// Represents the state of a particular topological walk through a Graph. Implements Iterator and
/// has the same lifetime as the Graph itself.
///
struct Walk<'a, N: Node> {
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
  use parking_lot;
  use rand;

  use std::cmp;
  use std::collections::{HashMap, HashSet};
  use std::sync::{mpsc, Arc};
  use std::thread;
  use std::time::Duration;

  use boxfuture::{BoxFuture, Boxable};
  use futures::future::{self, Future};
  use hashing::Digest;
  use parking_lot::Mutex;

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
    let context = TContext::new_with_dependencies(
      0,
      vec![(TNode(1), None)].into_iter().collect(),
      graph.clone(),
    );
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

  #[test]
  fn drain_and_resume() {
    // Confirms that after draining a Graph that has running work, we are able to resume the work
    // and have it complete successfully.
    let graph = Arc::new(Graph::new());

    let delay_before_drain = Duration::from_millis(100);
    let delay_in_task = delay_before_drain * 10;

    // Create a context that will sleep long enough at TNode(1) to be interrupted before
    // requesting TNode(0).
    let context = {
      let mut delays = HashMap::new();
      delays.insert(TNode(1), delay_in_task);
      TContext::new_with_delays(0, delays, graph.clone())
    };

    // Spawn a background thread that will mark the Graph draining after a short delay.
    let graph2 = graph.clone();
    let _join = thread::spawn(move || {
      thread::sleep(delay_before_drain);
      graph2
        .mark_draining(true)
        .expect("Should not already be draining.");
    });

    // Request a TNode(1) in the "delayed" context, and expect it to be interrupted by the
    // drain.
    assert_eq!(
      graph.create(TNode(2), &context).wait(),
      Err(TError::Invalidated),
    );

    // Unmark the Graph draining, and try again: we expect the `Invalidated` result we saw before
    // due to the draining to not have been persisted.
    graph
      .mark_draining(false)
      .expect("Should already be draining.");
    assert_eq!(
      graph.create(TNode(2), &context).wait(),
      Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
    );
  }

  #[test]
  fn cyclic_failure() {
    // Confirms that an attempt to create a cycle fails.
    let graph = Arc::new(Graph::new());
    let top = TNode(2);
    let context = TContext::new_with_dependencies(
      0,
      // Request creation of a cycle by sending the bottom most node to the top.
      vec![(TNode(0), Some(top))].into_iter().collect(),
      graph.clone(),
    );

    assert_eq!(graph.create(TNode(2), &context).wait(), Err(TError::Cyclic));
  }

  #[test]
  fn cyclic_dirtying() {
    // Confirms that a dirtied path between two nodes is able to reverse direction while being
    // cleaned.
    let graph = Arc::new(Graph::new());
    let initial_top = TNode(2);
    let initial_bot = TNode(0);

    // Request with a context that creates a path downward.
    let context_down = TContext::new(0, graph.clone());
    assert_eq!(
      graph.create(initial_top.clone(), &context_down).wait(),
      Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
    );

    // Clear the bottom node, and then clean it with a context that causes the path to reverse.
    graph.invalidate_from_roots(|n| n == &initial_bot);
    let context_up = TContext::new_with_dependencies(
      1,
      // Reverse the path from bottom to top.
      vec![(TNode(1), None), (TNode(0), Some(TNode(1)))]
        .into_iter()
        .collect(),
      graph.clone(),
    );

    let res = graph.create(initial_bot, &context_up).wait();

    assert_eq!(res, Ok(vec![T(1, 1), T(0, 1)]));

    let res = graph.create(initial_top, &context_up).wait();

    assert_eq!(res, Ok(vec![T(1, 1), T(2, 1)]));
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
      let token = T(self.0, context.id());
      if let Some(dep) = context.dependency_of(&self) {
        context.maybe_delay(&self);
        context
          .get(dep)
          .map(move |mut v| {
            v.push(token);
            v
          })
          .to_boxed()
      } else {
        future::ok(vec![token]).to_boxed()
      }
    }

    fn digest(_result: Self::Item) -> Option<Digest> {
      None
    }

    fn cacheable(&self) -> bool {
      true
    }
  }

  impl std::fmt::Display for TNode {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
      write!(f, "{:?}", self)
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
    // A mapping from source to optional destination that drives what values each TNode depends on.
    // If there is no entry in this map for a node, then TNode::run will default to requesting
    // the next smallest node. Finally, if a None entry is present, a node will have no
    // dependencies.
    edges: Arc<HashMap<TNode, Option<TNode>>>,
    delays: HashMap<TNode, Duration>,
    graph: Arc<Graph<TNode>>,
    runs: Arc<Mutex<Vec<TNode>>>,
    entry_id: Option<EntryId>,
  }
  impl NodeContext for TContext {
    type Node = TNode;
    fn clone_for(&self, entry_id: EntryId) -> TContext {
      TContext {
        id: self.id,
        edges: self.edges.clone(),
        delays: self.delays.clone(),
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
        edges: Arc::default(),
        delays: HashMap::default(),
        graph,
        runs: Arc::new(Mutex::new(Vec::new())),
        entry_id: None,
      }
    }

    fn new_with_dependencies(
      id: usize,
      edges: HashMap<TNode, Option<TNode>>,
      graph: Arc<Graph<TNode>>,
    ) -> TContext {
      TContext {
        id,
        edges: Arc::new(edges),
        delays: HashMap::default(),
        graph,
        runs: Arc::new(Mutex::new(Vec::new())),
        entry_id: None,
      }
    }

    fn new_with_delays(
      id: usize,
      delays: HashMap<TNode, Duration>,
      graph: Arc<Graph<TNode>>,
    ) -> TContext {
      TContext {
        id,
        edges: Arc::default(),
        delays,
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
      let mut runs = self.runs.lock();
      runs.push(node);
    }

    fn maybe_delay(&self, node: &TNode) {
      if let Some(delay) = self.delays.get(node) {
        thread::sleep(*delay);
      }
    }

    ///
    /// If the given TNode should declare a dependency on another TNode, returns that dependency.
    ///
    fn dependency_of(&self, node: &TNode) -> Option<TNode> {
      match self.edges.get(node) {
        Some(Some(ref dep)) => Some(dep.clone()),
        Some(None) => None,
        None if node.0 > 0 => Some(TNode(node.0 - 1)),
        None => None,
      }
    }

    fn runs(&self) -> Vec<TNode> {
      self.runs.lock().clone()
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
