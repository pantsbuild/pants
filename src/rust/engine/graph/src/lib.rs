// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

extern crate boxfuture;
extern crate fnv;
extern crate futures;
extern crate hashing;
extern crate petgraph;

mod node;

use std::collections::binary_heap::BinaryHeap;
use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::{File, OpenOptions};
use std::hash::BuildHasherDefault;
use std::io::{self, BufWriter, Write};
use std::mem;
use std::path::Path;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use fnv::FnvHasher;

use futures::future::{self, Future};
use futures::sync::oneshot;
use petgraph::graph::DiGraph;
use petgraph::Direction;

use boxfuture::{BoxFuture, Boxable};
pub use node::{EntryId, Node, NodeContext, NodeError, NodeTracer, NodeVisualizer};

type FNV = BuildHasherDefault<FnvHasher>;

type PGraph<N> = DiGraph<Entry<N>, (), u32>;

///
/// A token that uniquely identifies one run of a Node in the Graph. Each run of a Node (via
/// `N::Context::spawn`) has a different RunToken associated with it. When a run completes, if
/// the current RunToken of its Node no longer matches the RunToken of the spawned work (because
/// the Node was `cleared`), the work is discarded. See `Entry::complete` for more information.
///
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct RunToken(u32);

impl RunToken {
  fn initial() -> RunToken {
    RunToken(0)
  }

  fn next(&self) -> RunToken {
    RunToken(self.0 + 1)
  }
}

enum EntryState<N: Node> {
  NotStarted(RunToken),
  Running {
    waiters: Vec<oneshot::Sender<Result<N::Item, N::Error>>>,
    start_time: Instant,
    run_token: RunToken,
  },
  Completed {
    result: Result<N::Item, N::Error>,
    run_token: RunToken,
  },
}

impl<N: Node> EntryState<N> {
  fn initial() -> EntryState<N> {
    EntryState::NotStarted(RunToken::initial())
  }
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

///
/// An Entry and its adjacencies.
///
pub struct Entry<N: Node> {
  // TODO: This is a clone of the Node, which is also kept in the `nodes` map. It would be
  // nice to avoid keeping two copies of each Node, but tracking references between the two
  // maps is painful.
  node: EntryKey<N>,
  state: EntryState<N>,
}

impl<N: Node> Entry<N> {
  ///
  /// Creates an Entry without starting it. This indirection exists because we cannot know
  /// the EntryId of an Entry until after it is stored in the Graph, and we need the EntryId
  /// in order to run the Entry.
  ///
  fn new(node: EntryKey<N>) -> Entry<N> {
    Entry {
      node: node,
      state: EntryState::initial(),
    }
  }

  ///
  /// Returns a Future for the Node's field.
  ///
  fn get<C>(&mut self, context: &C, entry_id: EntryId) -> BoxFuture<N::Item, N::Error>
  where
    C: NodeContext<Node = N>,
  {
    let next_state = match &mut self.state {
      &mut EntryState::NotStarted(run_token) => {
        match &self.node {
          &EntryKey::Valid(ref n) => {
            let context2 = context.clone_for(entry_id);
            let node = n.clone();

            // Spawn the execution of the work on an Executor, which will cause it to execute
            // outside of the Graph lock, and allow us to call back into the graph lock to set the
            // final value.
            context.spawn(future::lazy(move || {
              let context = context2.clone();
              node.run(context2).then(move |res| {
                context.graph().complete(entry_id, run_token, res);
                Ok(())
              })
            }));

            EntryState::Running {
              waiters: Vec::new(),
              start_time: Instant::now(),
              run_token,
            }
          }
          &EntryKey::Cyclic(_) => EntryState::Completed {
            result: Err(N::Error::cyclic()),
            run_token: run_token,
          },
        }
      }
      &mut EntryState::Running {
        ref mut waiters, ..
      } => {
        let (send, recv) = oneshot::channel();
        waiters.push(send);
        return recv
          .map_err(|_| N::Error::invalidated())
          .flatten()
          .to_boxed();
      }
      &mut EntryState::Completed { ref result, .. } => {
        return future::result(result.clone()).to_boxed();
      }
    };

    // swap in the new state and then recurse.
    self.state = next_state;
    self.get(context, entry_id)
  }

  ///
  /// If the Future for this Node has already completed, returns a clone of its result.
  ///
  fn peek(&self) -> Option<Result<N::Item, N::Error>> {
    match &self.state {
      &EntryState::Completed { ref result, .. } => Some(result.clone()),
      _ => None,
    }
  }

  ///
  /// Called from the Executor when a Node completes.
  ///
  fn complete(&mut self, result_run_token: RunToken, result: Result<N::Item, N::Error>) {
    // Temporarily swap in `NotStarted` in order to take ownership of the state.
    let state = mem::replace(&mut self.state, EntryState::initial());

    // We care about exactly one case: a Running state with the same run_token. All other states
    // represent various (legal) race conditions. See `RunToken`'s docs for more information.
    self.state = match state {
      EntryState::Running {
        waiters,
        start_time,
        run_token,
      } => {
        if result_run_token == run_token {
          // Notify all waiters (ignoring any that have gone away), and then store the value.
          // A waiter will go away whenever they drop the `Future` `Receiver` of the value, perhaps
          // due to failure of another Future in a `join` or `join_all`, or due to a timeout at the
          // root of a request.
          for waiter in waiters {
            let _ = waiter.send(result.clone());
          }
          EntryState::Completed { result, run_token }
        } else {
          EntryState::Running {
            waiters,
            start_time,
            run_token,
          }
        }
      }
      s => s,
    };
  }

  ///
  /// If the Node has started and has not yet completed, returns its runtime.
  ///
  fn current_running_duration(&self, now: &Instant) -> Option<Duration> {
    match &self.state {
      &EntryState::Running { start_time, .. } => Some(now.duration_since(start_time)),
      _ => None,
    }
  }

  fn clear(&mut self) {
    let run_token = match mem::replace(&mut self.state, EntryState::initial()) {
      EntryState::NotStarted(run_token) => run_token,
      EntryState::Running { run_token, .. } => run_token,
      EntryState::Completed { run_token, .. } => run_token,
    };

    // Swap in a state with a new RunToken value, which invalidates any outstanding work.
    self.state = EntryState::NotStarted(run_token.next());
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
      if let Some(entry) = self.pg.node_weight_mut(*eid) {
        entry.clear();
      }
    }
  }

  ///
  /// Finds all "invalidation root" Nodes by applying the given predicate, and invalidates
  /// their transitive dependents.
  ///
  /// An "invalidation root" is a Node in the graph which can be invalidated for a reason other
  /// than having had its dependencies changed. When an invalidation root Node is invalidated,
  /// its dependencies are invalidated as well (regardless of whether they are also roots).
  ///
  fn invalidate_from_roots<P: Fn(&N) -> bool>(&mut self, predicate: P) -> usize {
    // Collect all entries that will be deleted.
    let ids: HashSet<EntryId, FNV> = {
      let root_ids = self
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
      self
        .walk(root_ids, Direction::Incoming)
        .map(|eid| eid)
        .collect()
    };
    let invalidated_count = ids.len();

    // Clear entry states.
    for id in &ids {
      self.pg.node_weight_mut(*id).map(|entry| entry.clear());
    }

    // Then prune all edges adjacent to the entries.
    self.pg.retain_edges(|pg, edge| {
      if let Some((src, dst)) = pg.edge_endpoints(edge) {
        !(ids.contains(&src) || ids.contains(&dst))
      } else {
        true
      }
    });

    invalidated_count
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

  fn trace<T: NodeTracer<N>>(&self, root: &N, path: &Path) -> io::Result<()> {
    let file = try!(OpenOptions::new().append(true).open(path));
    let mut f = BufWriter::new(file);

    let is_bottom = |eid: EntryId| -> bool { T::is_bottom(self.unsafe_entry_for_id(eid).peek()) };

    let is_one_level_above_bottom =
      |eid: EntryId| -> bool { self.pg.neighbors(eid).all(&is_bottom) };

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
      try!(writeln!(&mut f, "{}", _format(eid, level)));
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

    // Declare the dep, and return the state of the destination.
    inner.pg.add_edge(src_id, dst_id, ());
    if let Some(entry) = inner.entry_for_id_mut(dst_id) {
      entry.get(context, dst_id)
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
    let mut inner = self.inner.lock().unwrap();
    let id = inner.ensure_entry(EntryKey::Valid(node));
    if let Some(entry) = inner.entry_for_id_mut(id) {
      entry.get(context, id)
    } else {
      future::err(N::Error::invalidated()).to_boxed()
    }
  }

  ///
  /// When the Executor finishes executing a Node it calls back to store the result value. We use
  /// the run_token value to determine whether the Node changed while we were busy executing it,
  /// so that we can discard the work.
  ///
  fn complete(&self, entry_id: EntryId, run_token: RunToken, result: Result<N::Item, N::Error>) {
    let mut inner = self.inner.lock().unwrap();
    if let Some(entry) = inner.entry_for_id_mut(entry_id) {
      entry.complete(run_token, result);
    }
  }

  ///
  /// Clears the state of all Nodes in the Graph by dropping their state fields.
  ///
  pub fn clear(&self) {
    let mut inner = self.inner.lock().unwrap();
    inner.clear()
  }

  pub fn invalidate_from_roots<P: Fn(&N) -> bool>(&self, predicate: P) -> usize {
    let mut inner = self.inner.lock().unwrap();
    inner.invalidate_from_roots(predicate)
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

#[cfg(test)]
mod tests {
  use std::sync::Arc;
  use std::thread;

  use boxfuture::{BoxFuture, Boxable};
  use futures::future::{self, Future};
  use hashing::Digest;

  use super::{EntryId, Graph, Node, NodeContext, NodeError};

  #[test]
  fn create() {
    let graph = Arc::new(Graph::new());
    let context = TContext::new(graph.clone());
    assert_eq!(
      graph.create(TNode(2), &context).wait(),
      Ok("2/1/0".to_string())
    );
  }

  ///
  /// A node that builds a string by recursively requesting itself and prepending its value
  /// to the result.
  ///
  #[derive(Clone, Debug, Eq, Hash, PartialEq)]
  struct TNode(usize);
  impl Node for TNode {
    type Context = TContext;
    type Item = String;
    type Error = TError;

    fn run(self, context: TContext) -> BoxFuture<String, TError> {
      let depth = self.0;
      if depth > 0 {
        context
          .get(TNode(depth - 1))
          .map(move |v| format!("{}/{}", depth, v))
          .to_boxed()
      } else {
        future::ok(format!("{}", depth)).to_boxed()
      }
    }

    fn format(&self) -> String {
      format!("{:?}", self)
    }

    fn digest(_result: Self::Item) -> Option<Digest> {
      None
    }
  }

  #[derive(Clone)]
  struct TContext {
    graph: Arc<Graph<TNode>>,
    entry_id: Option<EntryId>,
  }
  impl NodeContext for TContext {
    type Node = TNode;
    fn clone_for(&self, entry_id: EntryId) -> TContext {
      TContext {
        graph: self.graph.clone(),
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
    fn new(graph: Arc<Graph<TNode>>) -> TContext {
      TContext {
        graph,
        entry_id: None,
      }
    }

    fn get(&self, dst: TNode) -> BoxFuture<String, TError> {
      self.graph.get(self.entry_id.unwrap(), self, dst)
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
