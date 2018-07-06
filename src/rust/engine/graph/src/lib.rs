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
use petgraph::visit::EdgeRef;
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

///
/// A token associated with a Node that is incremented whenever its output value has (or might
/// have) changed. When a dependent consumes a dependency at a particular generation, that
/// generation is recorded on the consuming edge, and can later used to determine whether the
/// inputs to a node have changed.
///
/// Unlike the RunToken (which is incremented whenever a node re-runs), the Generation is only
/// incremented when the output of a node has changed.
///
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Generation(u32);

impl Generation {
  fn initial() -> Generation {
    Generation(0)
  }

  fn next(&self) -> Generation {
    Generation(self.0 + 1)
  }
}

enum EntryState<N: Node> {
  // A node that has either been explicitly cleared, or has not yet started Running. In this state
  // there is no need for a dirty bit because the generation is either in its initial state, or has
  // been explicitly incremented when the node was cleared.
  //
  // The previous_result value is _not_ a valid value for this Entry: rather, it is preserved in
  // order to compute the generation value for this Node by comparing it to the new result the next
  // time the Node runs.
  NotStarted {
    run_token: RunToken,
    generation: Generation,
    previous_result: Option<Result<N::Item, N::Error>>,
  },
  // A node that is running. A running node that has been marked dirty re-runs rather than
  // completing.
  //
  // The `previous_result` value for a Running node is not a valid value. See NotStarted.
  Running {
    run_token: RunToken,
    generation: Generation,
    start_time: Instant,
    waiters: Vec<oneshot::Sender<Result<(N::Item, Generation), N::Error>>>,
    previous_result: Option<Result<N::Item, N::Error>>,
    dirty: bool,
  },
  // A node that has completed, and then possibly been marked dirty. Because marking a node
  // dirty does not eagerly re-execute any logic, it will stay this way until a caller moves it
  // back to Running.
  Completed {
    run_token: RunToken,
    generation: Generation,
    result: Result<N::Item, N::Error>,
    dep_generations: Vec<Generation>,
    dirty: bool,
  },
}

impl<N: Node> EntryState<N> {
  fn initial() -> EntryState<N> {
    EntryState::NotStarted {
      run_token: RunToken::initial(),
      generation: Generation::initial(),
      previous_result: None,
    }
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
  /// Spawn the execution of the node on an Executor, which will cause it to execute outside of
  /// the Graph lock and call back into the graph lock to set the final value.
  ///
  fn run<C>(
    context: &C,
    entry_key: &EntryKey<N>,
    entry_id: EntryId,
    run_token: RunToken,
    generation: Generation,
    previous_dep_generations: Option<Vec<Generation>>,
    previous_result: Option<Result<N::Item, N::Error>>,
  ) -> EntryState<N>
  where
    C: NodeContext<Node = N>,
  {
    // Increment the RunToken to uniquely identify this work.
    let run_token = run_token.next();
    match entry_key {
      &EntryKey::Valid(ref n) => {
        let context2 = context.clone_for(entry_id);
        let node = n.clone();

        context.spawn(future::lazy(move || {
          // If we have previous result generations, compare them to all current dependency
          // generations (which, if they are dirty, will cause recursive cleaning). If they
          // match, we can consider the previous result value to be clean for reuse.
          let was_clean = if let Some(previous_dep_generations) = previous_dep_generations {
            let context3 = context2.clone();
            context2
              .graph()
              .dep_generations(entry_id, &context2)
              .then(move |generation_res| match generation_res {
                Ok(ref dep_generations) if dep_generations == &previous_dep_generations => {
                  // Dependencies have not changed: Node is clean.
                  Ok(true)
                }
                _ => {
                  // If dependency generations mismatched or failed to fetch, clear its
                  // dependencies and indicate that it should re-run.
                  context3.graph().clear_deps(entry_id, run_token);
                  Ok(false)
                }
              })
              .to_boxed()
          } else {
            future::ok(false).to_boxed()
          };

          // If the Node was clean, complete it. Otherwise, re-run.
          was_clean.and_then(move |was_clean| {
            if was_clean {
              // No dependencies have changed: we can complete the Node without changing its
              // previous_result or generation.
              context2
                .graph()
                .complete(&context2, entry_id, run_token, None);
              future::ok(()).to_boxed()
            } else {
              // The Node needs to (re-)run!
              let context = context2.clone();
              node
                .run(context2)
                .then(move |res| {
                  context
                    .graph()
                    .complete(&context, entry_id, run_token, Some(res));
                  Ok(())
                })
                .to_boxed()
            }
          })
        }));

        EntryState::Running {
          waiters: Vec::new(),
          start_time: Instant::now(),
          run_token,
          generation,
          previous_result,
          dirty: false,
        }
      }
      &EntryKey::Cyclic(_) => EntryState::Completed {
        result: Err(N::Error::cyclic()),
        dep_generations: Vec::new(),
        run_token,
        generation,
        dirty: false,
      },
    }
  }

  ///
  /// Returns a Future for the Node's value and Generation.
  ///
  /// The two separate state matches handle two cases: in the first case we simply want to mutate
  /// or clone the state, so we take it by reference without swapping it. In the second case, we
  /// need to consume the state (which avoids cloning some of the values held there), so we take it
  /// by value.
  ///
  fn get<C>(&mut self, context: &C, entry_id: EntryId) -> BoxFuture<(N::Item, Generation), N::Error>
  where
    C: NodeContext<Node = N>,
  {
    // First check whether the Node is already complete, or is currently running: in both of these
    // cases we don't swap the state of the Node.
    match &mut self.state {
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
      &mut EntryState::Completed {
        ref result,
        generation,
        dirty,
        ..
      } if !dirty =>
      {
        return future::result(result.clone())
          .map(move |res| (res, generation))
          .to_boxed();
      }
      _ => {}
    };

    // Otherwise, we'll need to swap the state of the Node, so take it by value.
    let next_state = match mem::replace(&mut self.state, EntryState::initial()) {
      EntryState::NotStarted {
        run_token,
        generation,
        previous_result,
      } => Self::run(
        context,
        &self.node,
        entry_id,
        run_token,
        generation,
        None,
        previous_result,
      ),
      EntryState::Completed {
        run_token,
        generation,
        result,
        dep_generations,
        dirty,
      } => {
        assert!(
          dirty,
          "A clean Node should not reach this point: {:?}",
          result
        );
        // The Node has already completed but is now marked dirty. This indicates that we are the
        // first caller to request it since it was marked dirty. We attempt to clean it (which will
        // cause it to re-run if the dep_generations mismatch).
        Self::run(
          context,
          &self.node,
          entry_id,
          run_token,
          generation,
          Some(dep_generations),
          Some(result),
        )
      }
      EntryState::Running { .. } => {
        panic!("A Running Node should not reach this point.");
      }
    };

    // Swap in the new state and then recurse.
    self.state = next_state;
    self.get(context, entry_id)
  }

  ///
  /// If the Future for this Node has already completed, returns a clone of its result.
  ///
  fn peek(&self) -> Option<Result<N::Item, N::Error>> {
    match &self.state {
      &EntryState::Completed {
        ref result, dirty, ..
      } if !dirty =>
      {
        Some(result.clone())
      }
      _ => None,
    }
  }

  ///
  /// Called from the Executor when a Node completes.
  ///
  /// A `result` value of `None` indicates that the Node was found to be clean, and its previous
  /// result should be used. This special case exists to avoid 1) cloning the result to call this
  /// method, and 2) comparing the current/previous results unnecessarily.
  ///
  fn complete<C>(
    &mut self,
    context: &C,
    entry_id: EntryId,
    result_run_token: RunToken,
    dep_generations: Vec<Generation>,
    result: Option<Result<N::Item, N::Error>>,
  ) where
    C: NodeContext<Node = N>,
  {
    // We care about exactly one case: a Running state with the same run_token. All other states
    // represent various (legal) race conditions. See `RunToken`'s docs for more information.
    match &self.state {
      &EntryState::Running { run_token, .. } if result_run_token == run_token => {}
      _ => {
        // We care about exactly one case: a Running state with the same run_token. All other states
        // represent various (legal) race conditions.
        return;
      }
    }

    self.state = match mem::replace(&mut self.state, EntryState::initial()) {
      EntryState::Running {
        waiters,
        run_token,
        generation,
        previous_result,
        dirty,
        ..
      } => {
        if dirty {
          // The node was dirtied while it was running. The dep_generations and new result cannot
          // be trusted and were never published. We continue to use the previous result.
          Self::run(
            context,
            &self.node,
            entry_id,
            run_token,
            generation,
            None,
            previous_result,
          )
        } else {
          // If the new result does not match the previous result, the generation increments.
          let (generation, next_result) = if let Some(result) = result {
            if Some(&result) == previous_result.as_ref() {
              // Node was re-executed, but had the same result value.
              (generation, result)
            } else {
              (generation.next(), result)
            }
          } else {
            // Node was marked clean.
            // NB: The unwrap here avoids a clone and a comparison: see the method docs.
            (
              generation,
              previous_result.unwrap_or_else(|| {
                panic!("A Node cannot be marked clean without a previous result.")
              }),
            )
          };
          // Notify all waiters (ignoring any that have gone away), and then store the value.
          // A waiter will go away whenever they drop the `Future` `Receiver` of the value, perhaps
          // due to failure of another Future in a `join` or `join_all`, or due to a timeout at the
          // root of a request.
          for waiter in waiters {
            let _ = waiter.send(next_result.clone().map(|res| (res, generation)));
          }
          EntryState::Completed {
            result: next_result,
            dep_generations,
            run_token,
            generation,
            dirty: false,
          }
        }
      }
      s => s,
    };
  }

  ///
  /// Get the current Generation of this entry.
  ///
  /// TODO: Consider moving the Generation and RunToken out of the EntryState once we decide what
  /// we want the per-Entry locking strategy to be.
  ///
  fn generation(&self) -> Generation {
    match &self.state {
      &EntryState::NotStarted { generation, .. }
      | &EntryState::Running { generation, .. }
      | &EntryState::Completed { generation, .. } => generation,
    }
  }

  ///
  /// Get the current RunToken of this entry.
  ///
  /// TODO: Consider moving the Generation and RunToken out of the EntryState once we decide what
  /// we want the per-Entry locking strategy to be.
  ///
  fn run_token(&self) -> RunToken {
    match &self.state {
      &EntryState::NotStarted { run_token, .. }
      | &EntryState::Running { run_token, .. }
      | &EntryState::Completed { run_token, .. } => run_token,
    }
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

  ///
  /// Clears the state of this Node, forcing it to be recomputed.
  ///
  fn clear(&mut self) {
    let (run_token, generation, previous_result) =
      match mem::replace(&mut self.state, EntryState::initial()) {
        EntryState::NotStarted {
          run_token,
          generation,
          previous_result,
        }
        | EntryState::Running {
          run_token,
          generation,
          previous_result,
          ..
        } => (run_token, generation, previous_result),
        EntryState::Completed {
          run_token,
          generation,
          result,
          ..
        } => (run_token, generation, Some(result)),
      };

    // Swap in a state with a new RunToken value, which invalidates any outstanding work.
    self.state = EntryState::NotStarted {
      run_token: run_token.next(),
      generation,
      previous_result,
    };
  }

  ///
  /// Dirties this Node, which will cause it to examine its dependencies the next time it is
  /// requested, and re-run if any of them have changed generations.
  ///
  fn dirty(&mut self) {
    match &mut self.state {
      &mut EntryState::Running { ref mut dirty, .. }
      | &mut EntryState::Completed { ref mut dirty, .. } => {
        // Mark dirty.
        *dirty = true;
      }
      &mut EntryState::NotStarted { .. } => {}
    }
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
      self.pg.node_weight_mut(*id).map(|entry| entry.dirty());
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
      let output = format!("{}Computing {}", indent, entry.node.content().format());
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
      entry.get(context, dst_id).map(|(res, _)| res).to_boxed()
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
      entry.get(context, id).map(|(res, _)| res).to_boxed()
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
    let dep_edges: Vec<_> = inner
      .pg
      .edges_directed(entry_id, Direction::Outgoing)
      .map(|edge| edge.id())
      .collect();
    for dep_edge in dep_edges {
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
  /// our dependencies are still accurate.
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
    let mut inner = self.inner.lock().unwrap();
    // Get the Generations of all dependencies of the Node. We can trust that these have not changed
    // since we began executing, as long as we are not currently marked dirty (see the method doc).
    let dep_generations = inner
      .pg
      .neighbors_directed(entry_id, Direction::Outgoing)
      .filter_map(|dep_id| inner.entry_for_id(dep_id))
      .map(|entry| entry.generation())
      .collect();
    if let Some(entry) = inner.entry_for_id_mut(entry_id) {
      entry.complete(context, entry_id, run_token, dep_generations, result);
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
