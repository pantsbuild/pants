// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::File;
use std::fs::OpenOptions;
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use petgraph::Direction;
use petgraph::graphmap::{DiGraphMap, GraphMap};
use futures::future::{self, Future};

use externs;
use core::FNV;
use nodes::{
  Context,
  ContextFactory,
  Failure,
  Node,
  NodeFuture,
  NodeKey,
  NodeResult,
  TryInto
};

type EntryIdTyp = u32;
const ID_MAX_VALUE: EntryIdTyp = ::std::u32::MAX;

// 2^32 Nodes ought to be more than enough for anyone!
// TODO: But, see the overflow panic in `ensure_entry_internal`.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialOrd, PartialEq)]
pub struct EntryId(EntryIdTyp);

type EntryStateField = future::Shared<NodeFuture<NodeResult>>;

trait EntryStateGetter {
  fn get<N: Node>(&self) -> NodeFuture<N::Output>;
}

impl EntryStateGetter for EntryStateField {
  fn get<N: Node>(&self) -> NodeFuture<N::Output> {
    self
      .clone()
      .then(|node_result| Entry::unwrap::<N>(node_result))
      .boxed()
  }
}

/**
 * Because there are guaranteed to be more edges than nodes in Graphs, we mark cyclic
 * dependencies via a wrapper around the NodeKey (rather than adding a byte to every
 * valid edge).
 */
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
enum EntryKey {
  Valid(NodeKey),
  Cyclic(NodeKey),
}

impl EntryKey {
  fn content(&self) -> &NodeKey {
    match self {
      &EntryKey::Valid(ref v) => v,
      &EntryKey::Cyclic(ref v) => v,
    }
  }
}

/**
 * An Entry and its adjacencies.
 */
pub struct Entry {
  id: EntryId,
  // TODO: This is a clone of the Node, which is also kept in the `nodes` map. It would be
  // nice to avoid keeping two copies of each Node, but tracking references between the two
  // maps is painful.
  node: EntryKey,
  state: EntryStateField,
}

impl Entry {
  /**
   * Creates an Entry, wrapping its execution in `future::lazy` to defer execution until a
   * a caller actually pulls on it. This indirection exists in order to allow Nodes to start
   * outside of the Graph lock.
   */
  fn new(id: EntryId, node: EntryKey, context: Context) -> Entry {
    let state =
      match node.clone() {
        EntryKey::Valid(n) => {
          let core = context.core();
          let pool = core.pool();
          pool.spawn_fn(move || {
            n.run(context)
          })
          .boxed()
        },
        EntryKey::Cyclic(_) =>
          future::err(Failure::Noop("Dep would be cyclic.", None)).boxed(),
      };

    Entry {
      id: id,
      node: node,
      state: future::Shared::new(state),
    }
  }

  fn unwrap<N: Node>(
    res: Result<future::SharedItem<NodeResult>, future::SharedError<Failure>>
  ) -> Result<N::Output, Failure> {
    match res {
      Ok(nr) =>
        Ok(
          nr.clone().try_into().unwrap_or_else(|_| {
            panic!("A Node implementation was ambiguous.")
          })
        ),
      Err(failure) => Err(failure.clone())
    }
  }

  /**
   * Returns a reference to the Node's Future.
   */
  fn state(&self) -> EntryStateField {
    self.state.clone()
  }

  /**
   * If the Future for this Node has already completed, returns a clone of its result.
   */
  fn peek<N: Node>(&self) -> Option<Result<N::Output, Failure>> {
    self.state().peek().map(|nr| Entry::unwrap::<N>(nr))
  }

  fn format<N: Node>(&self) -> String {
    let state =
      match self.peek::<N>() {
        Some(Ok(ref nr)) => format!("{:?}", nr),
        Some(Err(Failure::Throw(ref v))) => externs::val_to_str(v),
        Some(Err(ref x)) => format!("{:?}", x),
        None => "<None>".to_string(),
      };
    format!("{} == {}", self.node.content().format(), state).replace("\"", "\\\"")
  }
}

type Nodes = HashMap<EntryKey, EntryId, FNV>;
type Entries = HashMap<EntryId, Entry, FNV>;

struct InnerGraph {
  id_generator: EntryIdTyp,
  nodes: Nodes,
  entries: Entries,
  pg: DiGraphMap<EntryId, ()>,
}

impl InnerGraph {
  fn entry(&self, node: &EntryKey) -> Option<&Entry> {
    self.nodes.get(node).map(|&id| self.entry_for_id(id))
  }

  fn entry_for_id(&self, id: EntryId) -> &Entry {
    self.entries.get(&id).unwrap_or_else(|| panic!("Invalid EntryId: {:?}", id))
  }

  fn ensure_entry(&mut self, context: &ContextFactory, node: EntryKey) -> EntryId {
    InnerGraph::ensure_entry_internal(
      &mut self.pg,
      &mut self.entries,
      &mut self.nodes,
      &mut self.id_generator,
      context,
      node
    )
  }

  fn ensure_entry_internal<'a>(
    pg: &mut DiGraphMap<EntryId, ()>,
    entries: &'a mut Entries,
    nodes: &mut Nodes,
    id_generator: &mut EntryIdTyp,
    context_factory: &ContextFactory,
    node: EntryKey
  ) -> EntryId {
    // See TODO on Entry.
    let entry_node = node.clone();
    let id =
      nodes.entry(node).or_insert_with(|| {
        EntryId(*id_generator)
      }).clone();

    // If this was an existing entry, we're done..
    if id.0 != *id_generator {
      return id;
    }

    // New entry.
    if *id_generator == ID_MAX_VALUE {
      // TODO: The memory savings are probably worthwhile.
      panic!("Overflow: more than {} nodes have been created.", ID_MAX_VALUE);
    }
    pg.add_node(id);
    let context = context_factory.create(id);
    *id_generator += 1;
    entries.insert(id, Entry::new(id, entry_node, context));

    id
  }

  /**
   * Detect whether adding an edge from src to dst would create a cycle.
   *
   * Returns true if a cycle would be created by adding an edge from src->dst.
   */
  fn detect_cycle(&self, src_id: EntryId, dst_id: EntryId) -> bool {
    // Search either forward from the dst, or backward from the src.
    let (root, needle, dependents) = {
      let out_from_dst = self.pg.neighbors(dst_id).count();
      let in_to_src = self.pg.neighbors_directed(src_id, Direction::Incoming).count();
      if out_from_dst < in_to_src {
        (dst_id, src_id, false)
      } else {
        (src_id, dst_id, true)
      }
    };

    // Search for an existing path from dst to src.
    let mut roots = VecDeque::new();
    roots.push_back(root);
    self.walk(roots, dependents).any(|eid| eid == needle)
  }

  /**
   * Begins a topological Walk from the given roots.
   */
  fn walk(&self, roots: VecDeque<EntryId>, dependents: bool) -> Walk {
    Walk {
      graph: self,
      direction: if dependents { Direction::Incoming } else { Direction::Outgoing },
      deque: roots,
      walked: HashSet::default(),
    }
  }

  /**
   * Begins a topological walk from the given roots. Provides both the current entry as well as the
   * depth from the root.
   */
  fn leveled_walk<P>(&self, roots: Vec<EntryId>, predicate: P, dependents: bool) -> LeveledWalk<P>
    where P: Fn(&Entry, Level) -> bool {
    let rrr = roots.into_iter().map(|r| (r, 0)).collect::<VecDeque<_>>();
    LeveledWalk {
      graph: self,
      direction: if dependents { Direction::Incoming } else { Direction::Outgoing },
      deque: rrr,
      walked: HashSet::default(),
      predicate: predicate,
    }
  }

  /**
   * Finds all Nodes with the given subjects, and invalidates their transitive dependents.
   */
  fn invalidate(&mut self, paths: HashSet<PathBuf>) -> usize {
    // Collect all entries that will be deleted.
    let ids: HashSet<EntryId, FNV> = {
      let root_ids =
        self.nodes.iter()
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
      self.walk(root_ids, true).map(|eid| eid).collect()
    };

    // Then remove all entries in one shot.
    let result = ids.len();
    InnerGraph::invalidate_internal(
      &mut self.pg,
      &mut self.entries,
      &mut self.nodes,
      ids,
    );

    // And return the removed count.
    result
  }

  fn invalidate_internal(
    pg: &mut DiGraphMap<EntryId, ()>,
    entries: &mut Entries,
    nodes: &mut Nodes,
    ids: HashSet<EntryId, FNV>
  ) {
    if ids.is_empty() {
      return;
    }

    for &id in &ids {
      // Validate that all dependents of the id are also scheduled for removal.
      assert!(pg.neighbors_directed(id, Direction::Incoming).all(|dep| ids.contains(&dep)));

      // Remove the entry from the graph (which will also remove dependent edges).
      pg.remove_node(id);

      // Remove the entry itself.
      entries.remove(&id);
    }

    // Filter the Nodes to delete any with matching ids.
    let filtered: Vec<(EntryKey, EntryId)> =
      nodes.drain()
        .filter(|&(_, id)| !ids.contains(&id))
        .collect();
    nodes.extend(filtered);

    assert!(
      nodes.len() == entries.len(),
      "The Nodes and Entries maps are mismatched: {} vs {}",
      nodes.len(),
      entries.len()
    );
  }

  pub fn visualize(&self, roots: &Vec<NodeKey>, path: &Path) -> io::Result<()> {
    let file = try!(File::create(path));
    let mut f = BufWriter::new(file);
    let mut viz_colors = HashMap::new();
    let viz_color_scheme = "set312";
    let viz_max_colors = 12;
    let mut format_color =
      |entry: &Entry| {
        match entry.peek::<NodeKey>() {
          None | Some(Err(Failure::Noop(_, _))) => "white".to_string(),
          Some(Err(Failure::Throw(_))) => "4".to_string(),
          Some(Ok(_)) => {
            let viz_colors_len = viz_colors.len();
            viz_colors.entry(entry.node.content().product_str()).or_insert_with(|| {
              format!("{}", viz_colors_len % viz_max_colors + 1)
            }).clone()
          },
        }
      };

    try!(f.write_all(b"digraph plans {\n"));
    try!(f.write_fmt(format_args!("  node[colorscheme={}];\n", viz_color_scheme)));
    try!(f.write_all(b"  concentrate=true;\n"));
    try!(f.write_all(b"  rankdir=TB;\n"));

    let root_entries =
      roots.iter()
        .filter_map(|n| self.entry(&EntryKey::Valid(n.clone())))
        .map(|e| e.id).collect();
    let predicate = |_| true;

    for eid in self.walk(root_entries, false) {
      let entry = self.entry_for_id(eid);
      let node_str = entry.format::<NodeKey>();

      // Write the node header.
      try!(f.write_fmt(format_args!("  \"{}\" [style=filled, fillcolor={}];\n", node_str, format_color(entry))));

      for dep_id in self.pg.neighbors(entry.id) {
        let dep_entry = self.entry_for_id(dep_id);
        if !predicate(dep_entry) {
          continue;
        }

        // Write an entry per edge.
        let dep_str = dep_entry.format::<NodeKey>();
        try!(f.write_fmt(format_args!("    \"{}\" -> \"{}\"\n", node_str, dep_str)));
      }
    }

    try!(f.write_all(b"}\n"));
    Ok(())
  }

  pub fn trace(&self, root: &NodeKey, path: &Path) -> io::Result<()> {
    let file = try!(OpenOptions::new().append(true).open(path));
    let mut f = BufWriter::new(file);

    let is_bottom = |entry: &Entry| -> bool {
      match entry.peek::<NodeKey>() {
        None | Some(Err(Failure::Noop(..))) => true,
        Some(Err(Failure::Throw(_))) => false,
        Some(Ok(_)) => true,
      }
    };

    let is_one_level_above_bottom = |c: &Entry| -> bool {
      for d in self.pg.neighbors(c.id) {
        if !is_bottom(self.entry_for_id(d)) {
          return false;
        }
      }
      true
    };

    let _indent = |level: Level| -> String {
      let mut indent = String::new();
      for _ in 0..level {
        indent.push_str("  ");
      }
      indent
    };

    let _format = |entry: &Entry, level: Level| -> String {
      let indent = _indent(level);
      let output = format!("{}Computing {}", indent, entry.node.content().format());
      if is_one_level_above_bottom(entry) {
        let state_str = match entry.peek::<NodeKey>() {
          None => "<None>".to_string(),
          Some(Ok(ref x)) => format!("{:?}", x),
          Some(Err(Failure::Throw(ref x))) => format!("Throw({})", externs::val_to_str(x)),
          Some(Err(Failure::Noop(ref x, ref opt_node))) => format!("Noop({:?}, {:?})", x, opt_node),
        };
        format!("{}\n{}  {}", output, indent, state_str)
      } else {
        output
      }
    };

    let root_entries =
      self.entry(&EntryKey::Valid(root.clone()))
        .map(|e| vec![e.id])
        .unwrap_or_else(|| vec![]);
    for t in self.leveled_walk(root_entries, |e,_| !is_bottom(e), false) {
      let (entry, level) = t;
      try!(write!(&mut f, "{}\n", _format(entry, level)));
    }

    try!(f.write_all(b"\n"));
    Ok(())
  }
}

/**
 * A DAG (enforced on mutation) of Entries.
 */
pub struct Graph {
  inner: Mutex<InnerGraph>,
}

impl Graph {
  pub fn new() -> Graph {
    let inner =
      InnerGraph {
        id_generator: 0,
        nodes: HashMap::default(),
        entries: HashMap::default(),
        pg: GraphMap::new(),
      };
    Graph {
      inner: Mutex::new(inner),
    }
  }

  pub fn len(&self) -> usize {
    let inner = self.inner.lock().unwrap();
    inner.entries.len()
  }

  /**
   * If the given Node has completed, returns a clone of its state.
   */
  pub fn peek<N: Node>(&self, node: N) -> Option<Result<N::Output, Failure>> {
    let node = node.into();
    let inner = self.inner.lock().unwrap();
    inner.entry(&EntryKey::Valid(node)).and_then(|e| e.peek::<N>())
  }

  /**
   * In the context of the given src Node, declare a dependency on the given dst Node and
   * begin its execution if it has not already started.
   */
  pub fn get<N: Node>(&self, src_id: EntryId, context: &ContextFactory, dst_node: N) -> NodeFuture<N::Output> {
    let dst_node = dst_node.into();

    // Get or create the destination, and then insert the dep and return its state.
    let dst_state = {
      let mut inner = self.inner.lock().unwrap();
      let dst_id = {
        // TODO: doing cycle detection under the lock... unfortunate, but probably unavoidable
        // without a much more complicated algorithm.
        let potential_dst_id = inner.ensure_entry(context, EntryKey::Valid(dst_node.clone()));
        if inner.detect_cycle(src_id, potential_dst_id) {
          // Cyclic dependency: declare a dependency on a copy of the Node that is marked Cyclic.
          inner.ensure_entry(context, EntryKey::Cyclic(dst_node.clone()))
        } else {
          // Valid dependency.
          potential_dst_id
        }
      };

      // Declare the dep, and return the state of the destination.
      inner.pg.add_edge(src_id, dst_id, ());
      inner.entry_for_id(dst_id).state()
    };

    // Got the destination's state. Now that we're outside the graph locks, we can safely
    // retrieve it.
    dst_state.get::<N>()
  }

  /**
   * Create the given Node if it does not already exist.
   */
  pub fn create<N: Node>(&self, node: N, context: &ContextFactory) -> NodeFuture<N::Output> {
    // Initialize the state while under the lock...
    let state = {
      let mut inner = self.inner.lock().unwrap();
      let id = inner.ensure_entry(context, EntryKey::Valid(node.into()));
      inner.entry_for_id(id).state()
    };
    // ...but only `get` it outside the lock.
    state.get::<N>()
  }

  pub fn invalidate(&self, paths: HashSet<PathBuf>) -> usize {
    let mut inner = self.inner.lock().unwrap();
    inner.invalidate(paths)
  }

  pub fn trace(&self, root: &NodeKey, path: &Path) -> io::Result<()> {
    let inner = self.inner.lock().unwrap();
    inner.trace(root, path)
  }

  pub fn visualize(&self, roots: &Vec<NodeKey>, path: &Path) -> io::Result<()> {
    let inner = self.inner.lock().unwrap();
    inner.visualize(roots, path)
  }
}

/**
 * Represents the state of a particular topological walk through a Graph. Implements Iterator and
 * has the same lifetime as the Graph itself.
 */
struct Walk<'a> {
  graph: &'a InnerGraph,
  direction: Direction,
  deque: VecDeque<EntryId>,
  walked: HashSet<EntryId, FNV>,
}

impl<'a> Iterator for Walk<'a> {
  type Item = EntryId;

  fn next(&mut self) -> Option<EntryId> {
    while let Some(id) = self.deque.pop_front() {
      if !self.walked.insert(id) {
        continue;
      }

      // Queue the neighbors of the entry and then return it.
      self.deque.extend(self.graph.pg.neighbors_directed(id, self.direction));
      return Some(id);
    }

    None
  }
}

type Level = u32;

/**
 * Represents the state of a particular topological walk through a Graph. Implements Iterator and
 * has the same lifetime as the Graph itself.
 */
struct LeveledWalk<'a, P: Fn(&Entry, Level)->bool> {
  graph: &'a InnerGraph,
  direction: Direction,
  deque: VecDeque<(EntryId, Level)>,
  walked: HashSet<EntryId, FNV>,
  predicate: P,
}

impl<'a, P: Fn(&Entry, Level)->bool> Iterator for LeveledWalk<'a, P> {
  type Item = (&'a Entry, Level);

  fn next(&mut self) -> Option<(&'a Entry, Level)> {
    while let Some((id, level)) = self.deque.pop_front() {
      if self.walked.contains(&id) {
        continue;
      }
      self.walked.insert(id);

      let entry = self.graph.entry_for_id(id);
      if !(self.predicate)(entry, level) {
        continue;
      }

      // Entry matches: queue its neighbors and then return it.
      self.deque.extend(
        self.graph.pg.neighbors_directed(id, self.direction).into_iter()
          .map(|d| (d, level+1))
      );
      return Some((entry, level));
    }

    None
  }
}
