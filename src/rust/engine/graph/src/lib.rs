// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

extern crate boxfuture;
extern crate fnv;
extern crate futures;
extern crate hashing;
extern crate petgraph;

mod node;

use std::collections::{HashMap, HashSet, VecDeque};
use std::hash::BuildHasherDefault;
use std::fs::{File, OpenOptions};
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use std::collections::binary_heap::BinaryHeap;

use fnv::FnvHasher;

use petgraph::Direction;
use petgraph::stable_graph::{StableDiGraph, StableGraph};
use futures::future::{self, Future};

use boxfuture::{BoxFuture, Boxable};
pub use node::{EntryId, Node, NodeContext, NodeError, NodeTracer, NodeVisualizer};

type FNV = BuildHasherDefault<FnvHasher>;

type PGraph<N> = StableDiGraph<Entry<N>, (), u32>;

type EntryStateField<Item, Error> = future::Shared<BoxFuture<Item, Error>>;

struct EntryState<N: Node> {
  field: EntryStateField<N::Item, N::Error>,
  start_time: Instant,
}

///
/// Because there are guaranteed to be more edges than nodes in Graphs, we mark cyclic
/// dependencies via a wrapper around the Node (rather than adding a byte to every
/// valid edge).
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
enum EntryKey<N: Node> {
  Valid(N),
  Cyclic(N),
}

impl<N: Node> EntryKey<N> {
  fn content(&self) -> &N {
    match self {
      &EntryKey::Valid(ref v) => v,
      &EntryKey::Cyclic(ref v) => v,
    }
  }
}

fn unwrap_entry_res<N: Node>(
  res: Result<future::SharedItem<N::Item>, future::SharedError<N::Error>>,
) -> Result<N::Item, N::Error> {
  match res {
    Ok(nr) => Ok((*nr).clone()),
    Err(failure) => Err((*failure).clone()),
  }
}

///
/// An Entry and its adjacencies.
///
pub struct Entry<N: Node> {
  // TODO: This is a clone of the Node, which is also kept in the `nodes` map. It would be
  // nice to avoid keeping two copies of each Node, but tracking references between the two
  // maps is painful.
  node: EntryKey<N>,
  state: Option<EntryState<N>>,
}

impl<N: Node> Entry<N> {
  ///
  /// Creates an Entry, wrapping its execution in `future::lazy` to defer execution until a
  /// a caller actually pulls on it. This indirection exists in order to allow Nodes to start
  /// outside of the Graph lock.
  ///
  fn new(node: EntryKey<N>) -> Entry<N> {
    Entry {
      node: node,
      state: None,
    }
  }

  ///
  /// Returns a reference to the Node's Future, starting it if need be.
  ///
  fn state<C>(&mut self, context: &C, entry_id: EntryId) -> EntryStateField<N::Item, N::Error>
  where
    C: NodeContext<CloneFor = N::Context>,
  {
    if let Some(ref state) = self.state {
      state.field.clone()
    } else {
      let start_time = Instant::now();
      let state = match &self.node {
        &EntryKey::Valid(ref n) => {
          // Wrap the launch in future::lazy to defer it until after we're outside the Graph lock.
          let context = context.clone_for(entry_id);
          let node = n.clone();
          future::lazy(move || node.run(context)).to_boxed()
        }
        &EntryKey::Cyclic(_) => future::err(N::Error::cyclic()).to_boxed(),
      };

      self.state = Some(EntryState {
        field: state.shared(),
        start_time,
      });
      self.state(context, entry_id)
    }
  }

  ///
  /// If the Future for this Node has already completed, returns a clone of its result.
  ///
  fn peek(&self) -> Option<Result<N::Item, N::Error>> {
    self
      .state
      .as_ref()
      .and_then(|state| state.field.peek().map(unwrap_entry_res::<N>))
  }

  ///
  /// If the Node has started and has not yet completed, returns its runtime.
  ///
  fn current_running_duration(&self, now: &Instant) -> Option<Duration> {
    self.state.as_ref().and_then(|state| {
      if state.field.peek().is_none() {
        // Still running.
        Some(now.duration_since(state.start_time))
      } else {
        None
      }
    })
  }

  fn clear(&mut self) {
    self.state = None;
  }

  fn format(&self) -> String {
    let state = match self.peek() {
      Some(Ok(ref nr)) => format!("{:?}", nr),
      Some(Err(ref x)) => format!("{:?}", x),
      None => "<None>".to_string(),
    };
    format!("{} == {}", self.node.content().format(), state).replace("\"", "\\\"")
  }
}

type Nodes<N> = HashMap<EntryKey<N>, EntryId>;

struct InnerGraph<N: Node> {
  nodes: Nodes<N>,
  pg: PGraph<N>,
}

impl<N: Node> InnerGraph<N> {
  fn entry(&self, node: &EntryKey<N>) -> Option<&Entry<N>> {
    self.entry_id(node).and_then(|&id| self.entry_for_id(id))
  }

  fn entry_id(&self, node: &EntryKey<N>) -> Option<&EntryId> {
    self.nodes.get(node)
  }

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

  fn ensure_entry_internal<'a>(
    pg: &mut PGraph<N>,
    nodes: &mut Nodes<N>,
    node: EntryKey<N>,
  ) -> EntryId {
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

  ///
  /// Begins a topological walk from the given roots. Provides both the current entry as well as the
  /// depth from the root.
  ///
  fn leveled_walk<P>(
    &self,
    roots: Vec<EntryId>,
    predicate: P,
    direction: Direction,
  ) -> LeveledWalk<N, P>
  where
    P: Fn(EntryId, Level) -> bool,
  {
    let rrr = roots.into_iter().map(|r| (r, 0)).collect::<VecDeque<_>>();
    LeveledWalk {
      graph: self,
      direction: direction,
      deque: rrr,
      walked: HashSet::default(),
      predicate: predicate,
    }
  }

  fn clear(&mut self) {
    for eid in self.nodes.values() {
      self.pg.node_weight_mut(*eid).map(|entry| entry.clear());
    }
  }

  ///
  /// Finds all Nodes with the given subjects, and invalidates their transitive dependents.
  ///
  fn invalidate(&mut self, paths: HashSet<PathBuf>) -> usize {
    // Collect all entries that will be deleted.
    let ids: HashSet<EntryId, FNV> = {
      let root_ids = self
        .nodes
        .iter()
        .filter_map(|(node, &entry_id)| {
          node.content().fs_subject().and_then(|path| {
            if paths.contains(path) {
              Some(entry_id)
            } else {
              None
            }
          })
        })
        .collect();
      self
        .walk(root_ids, Direction::Incoming)
        .map(|eid| eid)
        .collect()
    };

    // Then remove all entries in one shot.
    let result = ids.len();
    InnerGraph::invalidate_internal(&mut self.pg, &mut self.nodes, ids);

    // And return the removed count.
    result
  }

  fn invalidate_internal(pg: &mut PGraph<N>, nodes: &mut Nodes<N>, ids: HashSet<EntryId, FNV>) {
    if ids.is_empty() {
      return;
    }

    for &id in &ids {
      // Validate that all dependents of the id are also scheduled for removal.
      assert!(
        pg.neighbors_directed(id, Direction::Incoming)
          .all(|dep| ids.contains(&dep))
      );

      // Remove the entry from the graph (which will also remove dependent edges).
      pg.remove_node(id);
    }

    // Filter the Nodes to delete any with matching ids.
    let filtered: Vec<(EntryKey<N>, EntryId)> = nodes
      .drain()
      .filter(|&(_, id)| !ids.contains(&id))
      .collect();
    nodes.extend(filtered);

    assert!(
      nodes.len() == pg.node_count(),
      "The Nodes and Entries maps are mismatched: {} vs {}",
      nodes.len(),
      pg.node_count()
    );
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

    let mut format_color = |entry: &Entry<N>| visualizer.color(entry.node.content(), entry.peek());

    let root_entries = roots
      .iter()
      .filter_map(|n| self.entry_id(&EntryKey::Valid(n.clone())))
      .map(|&eid| eid)
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
        try!(f.write_fmt(format_args!("    \"{}\" -> \"{}\"\n", node_str, dep_str),));
      }
    }

    try!(f.write_all(b"}\n"));
    Ok(())
  }

  fn trace<T: NodeTracer<N>>(&self, root: &N, path: &Path) -> io::Result<()> {
    let file = try!(OpenOptions::new().append(true).open(path));
    let mut f = BufWriter::new(file);

    let is_bottom = |eid: EntryId| -> bool { T::is_bottom(self.unsafe_entry_for_id(eid).peek()) };

    let is_one_level_above_bottom =
      |eid: EntryId| -> bool { self.pg.neighbors(eid).all(|d| is_bottom(d)) };

    let _indent = |level: Level| -> String {
      let mut indent = String::new();
      for _ in 0..level {
        indent.push_str("  ");
      }
      indent
    };

    let _format = |eid: EntryId, level: Level| -> String {
      let entry = self.unsafe_entry_for_id(eid);
      let indent = _indent(level);
      let output = format!("{}Computing {}", indent, entry.node.content().format());
      if is_one_level_above_bottom(eid) {
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

    let root_entries = self
      .entry_id(&EntryKey::Valid(root.clone()))
      .map(|&eid| vec![eid])
      .unwrap_or_else(|| vec![]);
    for t in self.leveled_walk(root_entries, |eid, _| !is_bottom(eid), Direction::Outgoing) {
      let (eid, level) = t;
      try!(write!(&mut f, "{}\n", _format(eid, level)));
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

    let mut queue: BinaryHeap<(Duration, EntryId)> = BinaryHeap::with_capacity(k as usize);
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
        .filter_map(|id| queue_entry(id))
        .peekable();

      if deps.peek().is_none() {
        // If the entry has no running deps, it is a leaf. Emit it.
        res.push((
          self.unsafe_entry_for_id(id).node.content().format(),
          duration,
        ));
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
  ) -> Box<Iterator<Item = hashing::Digest> + 'g> {
    Box::new(
      entryids
        .into_iter()
        .filter_map(move |eid| self.entry_for_id(eid))
        .filter_map(|entry| match entry.peek() {
          Some(Ok(item)) => N::digest(item),
          _ => None,
        }),
    )
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
      pg: StableGraph::new(),
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
  /// If the given Node has completed, returns a clone of its state.
  ///
  pub fn peek(&self, node: N) -> Option<Result<N::Item, N::Error>> {
    let node = node.into();
    let inner = self.inner.lock().unwrap();
    inner.entry(&EntryKey::Valid(node)).and_then(|e| e.peek())
  }

  ///
  /// In the context of the given src Node, declare a dependency on the given dst Node and
  /// begin its execution if it has not already started.
  ///
  pub fn get<C>(&self, src_id: EntryId, context: &C, dst_node: N) -> BoxFuture<N::Item, N::Error>
  where
    C: NodeContext<CloneFor = N::Context>,
  {
    // Get or create the destination, and then insert the dep and return its state.
    let dst_state = {
      let mut inner = self.inner.lock().unwrap();
      let dst_id = {
        // TODO: doing cycle detection under the lock... unfortunate, but probably unavoidable
        // without a much more complicated algorithm.
        let potential_dst_id = inner.ensure_entry(EntryKey::Valid(dst_node.clone()));
        if inner.detect_cycle(src_id, potential_dst_id) {
          // Cyclic dependency: declare a dependency on a copy of the Node that is marked Cyclic.
          inner.ensure_entry(EntryKey::Cyclic(dst_node.clone()))
        } else {
          // Valid dependency.
          potential_dst_id
        }
      };

      // Declare the dep, and return the state of the destination.
      inner.pg.add_edge(src_id, dst_id, ());
      inner
        .entry_for_id_mut(dst_id)
        .map(|entry| entry.state(context, dst_id))
        .unwrap_or_else(|| future::err(N::Error::invalidated()).to_boxed().shared())
    };

    // Got the destination's state. Now that we're outside the graph locks, we can safely
    // retrieve it.
    dst_state.then(unwrap_entry_res::<N>).to_boxed()
  }

  ///
  /// Create the given Node if it does not already exist.
  ///
  pub fn create<C>(&self, node: N, context: &C) -> BoxFuture<N::Item, N::Error>
  where
    C: NodeContext<CloneFor = N::Context>,
  {
    // Initialize the state while under the lock...
    let state = {
      let mut inner = self.inner.lock().unwrap();
      let id = inner.ensure_entry(EntryKey::Valid(node.into()));
      inner
        .entry_for_id_mut(id)
        .map(|entry| entry.state(context, id))
        .unwrap_or_else(|| future::err(N::Error::invalidated()).to_boxed().shared())
    };
    // ...but only `get` it outside the lock.
    state.then(unwrap_entry_res::<N>).to_boxed()
  }

  ///
  /// Clears the state of all Nodes in the Graph by dropping their state fields.
  ///
  pub fn clear(&self) {
    let mut inner = self.inner.lock().unwrap();
    inner.clear()
  }

  pub fn invalidate(&self, paths: HashSet<PathBuf>) -> usize {
    let mut inner = self.inner.lock().unwrap();
    inner.invalidate(paths)
  }

  pub fn trace<T: NodeTracer<N>>(&self, root: &N, path: &Path) -> io::Result<()> {
    let inner = self.inner.lock().unwrap();
    inner.trace::<T>(root, path)
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

  #[allow(dead_code)]
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

type Level = u32;

///
/// Represents the state of a particular topological walk through a Graph. Implements Iterator and
/// has the same lifetime as the Graph itself.
///
struct LeveledWalk<'a, N: Node + 'a, P: Fn(EntryId, Level) -> bool> {
  graph: &'a InnerGraph<N>,
  direction: Direction,
  deque: VecDeque<(EntryId, Level)>,
  walked: HashSet<EntryId, FNV>,
  predicate: P,
}

impl<'a, N: Node + 'a, P: Fn(EntryId, Level) -> bool> Iterator for LeveledWalk<'a, N, P> {
  type Item = (EntryId, Level);

  fn next(&mut self) -> Option<Self::Item> {
    while let Some((id, level)) = self.deque.pop_front() {
      if self.walked.contains(&id) {
        continue;
      }
      self.walked.insert(id);

      if !(self.predicate)(id, level) {
        continue;
      }

      // Entry matches: queue its neighbors and then return it.
      self.deque.extend(
        self
          .graph
          .pg
          .neighbors_directed(id, self.direction)
          .into_iter()
          .map(|d| (d, level + 1)),
      );
      return Some((id, level));
    }

    None
  }
}
