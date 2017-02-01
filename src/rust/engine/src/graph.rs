
use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::File;
use std::fs::OpenOptions;
use std::io::{BufWriter, Write};
use std::io;
use std::path::Path;
use std::sync::{Arc, RwLock};

use futures::future::Future;
use futures::future;

use externs::Externs;
use core::{FNV, Key};
use nodes::{Failure, Node, NodeFuture, NodeResult, Context, ContextFactory};

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct EntryId(usize);

pub type DepSet = HashSet<EntryId, FNV>;

/**
 * An Entry and its adjacencies.
 */
pub struct Entry {
  id: EntryId,
  // TODO: This is a clone of the Node, which is also kept in the `nodes` map. It would be
  // nice to avoid keeping two copies of each Node, but tracking references between the two
  // maps is painful.
  node: Node,
  // To avoid holding the Graph's lock longer than necessary, a Node should initializes lazily.
  state: NodeFuture,
  // Sets of all Nodes which have ever been awaited by this Node.
  dependencies: DepSet,
  dependents: DepSet,
  // Deps that would be illegal to actually provide, since they would be cyclic.
  cyclic_dependencies: DepSet,
}

impl Entry {
  fn id(&self) -> EntryId {
    self.id
  }

  fn node(&self) -> &Node {
    &self.node
  }

  fn get(&self) -> &NodeFuture {
    &self.state
  }

  fn dependencies(&self) -> &DepSet {
    &self.dependencies
  }

  fn dependents(&self) -> &DepSet {
    &self.dependents
  }

  fn cyclic_dependencies(&self) -> &DepSet {
    &self.cyclic_dependencies
  }

  /**
   * TODO: This definition is now suspect, since we don't eagerly mark things Finished.
   * Might need to remove that optimization from the cycle detection.
   */
  fn is_complete(&self) -> bool {
    unimplemented!();
    /*
    match self.state {
      EntryState::Pending => false,
      EntryState::Started(..) => false,
      EntryState::Finished(..) => true,
    }
    */
  }

  fn format(&self, externs: &Externs) -> String {
    unimplemented!();
    /*
    let state =
      match self.state {
        Some(Complete::Return(ref v)) => externs.val_to_str(v),
        ref x => format!("{:?}", x),
      };
    format!(
      "{}:{}:{} == {}",
      self.node.format(externs),
      externs.id_to_str(self.node.subject().id()),
      externs.id_to_str(self.node.selector().product().0),
      state,
    ).replace("\"", "\\\"")
    */
  }
}

type Nodes = HashMap<Node, EntryId, FNV>;
type Entries = HashMap<EntryId, Entry, FNV>;

struct InnerGraph {
  id_generator: usize,
  nodes: Nodes,
  entries: Entries,
  cyclic_singleton: NodeFuture,
}

impl InnerGraph {
  fn cyclic_singleton(&self) -> NodeFuture {
    self.cyclic_singleton.clone()
  }

  fn dependencies_all<P>(&self, id: EntryId, predicate: P) -> bool
      where P: Fn(&Entry)->bool {
    self.entry_for_id(id).dependencies.iter().all(|&d| predicate(self.entry_for_id(d)))
  }

  fn entry(&self, node: &Node) -> Option<&Entry> {
    self.nodes.get(node).map(|&id| self.entry_for_id(id))
  }

  fn entry_for_id(&self, id: EntryId) -> &Entry {
    self.entries.get(&id).unwrap_or_else(|| panic!("Invalid EntryId: {:?}", id))
  }

  fn entry_for_id_mut(&mut self, id: EntryId) -> &mut Entry {
    self.entries.get_mut(&id).unwrap_or_else(|| panic!("Invalid EntryId: {:?}", id))
  }

  fn ensure_entry(&mut self, context: &ContextFactory, node: Node) -> EntryId {
    InnerGraph::ensure_entry_internal(
      &mut self.entries,
      &mut self.nodes,
      &mut self.id_generator,
      context,
      node
    )
  }

  fn ensure_entry_internal<'a>(
    entries: &'a mut Entries,
    nodes: &mut Nodes,
    id_generator: &mut usize,
    context_factory: &ContextFactory,
    node: Node
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

    // New entry. Launch the Node on the pool.
    // FIXME: It's necessary to call back to the pool here currently, because otherwise the work
    // represented by the Node begins executing immediately on the current thread, which is
    // undesirable, because we are holding the graph lock. Fixing that would likely mean making
    // the creation of an Entry's state an atomic operation outside of the Graph lock.
    let context = context_factory.create(id);
    let pool = context.pool().clone();
    let pool_node = entry_node.clone();
    let state =
      future::Shared::new(
        pool.spawn_fn(move || {
          pool_node.step(context.create(id))
        })
        .boxed()
      );
    *id_generator += 1;
    entries.insert(
      id,
      Entry {
        id: id,
        node: entry_node,
        state: state,
        dependencies: Default::default(),
        dependents: Default::default(),
        cyclic_dependencies: Default::default(),
      }
    );

    id
  }

  /**
   * Detect whether adding an edge from src to dst would create a cycle.
   *
   * Returns true if a cycle would be created by adding an edge from src->dst.
   */
  fn detect_cycle(&self, src_id: EntryId, dst_id: EntryId) -> bool {
    // If dst has no (incomplete) dependencies (a very common case), don't even allocate the
    // structures to begin the walk.
    if self.dependencies_all(dst_id, |e| e.is_complete()) {
      return false;
    }

    // Search for an existing path from dst to src.
    let mut roots = VecDeque::new();
    roots.push_back(dst_id);
    self.walk(roots, { |e| !e.is_complete() }, false).any(|e| e.id == src_id)
  }

  /**
   * Begins a topological Walk from the given roots.
   */
  fn walk<P>(&self, roots: VecDeque<EntryId>, predicate: P, dependents: bool) -> Walk<P>
    where P: Fn(&Entry)->bool {
    Walk {
      graph: self,
      dependents: dependents,
      deque: roots,
      walked: HashSet::default(),
      predicate: predicate,
    }
  }

  /**
   * Begins a topological walk from the given roots. Provides both the current entry as well as the
   * depth from the root.
   */
  fn leveled_walk<P>(&self, roots: VecDeque<EntryId>, predicate: P, dependents: bool) -> LeveledWalk<P>
    where P: Fn(&Entry, Level) -> bool {
    let rrr = roots.iter().map(|&r| (r, 0)).collect::<VecDeque<_>>();
    LeveledWalk {
      graph: self,
      dependents: dependents,
      deque: rrr,
      walked: HashSet::default(),
      predicate: predicate,
    }
  }

  /**
   * Finds all Nodes with the given subjects, and invalidates their transitive dependents.
   */
  fn invalidate(&mut self, subjects: HashSet<&Key, FNV>) -> usize {
    // Collect all entries that will be deleted.
    let ids: HashSet<EntryId, FNV> = {
      let root_ids =
        self.nodes.iter()
          .filter_map(|(node, &entry_id)| {
            if subjects.contains(node.subject()) {
              Some(entry_id)
            } else {
              None
            }
          })
          .collect();
      self.walk(root_ids, { |_| true }, true).map(|e| e.id()).collect()
    };

    // Then remove all entries in one shot.
    InnerGraph::invalidate_internal(
      &mut self.entries,
      &mut self.nodes,
      &ids,
    );

    // And return the removed count.
    ids.len()
  }

  fn invalidate_internal(entries: &mut Entries, nodes: &mut Nodes, ids: &HashSet<EntryId, FNV>) {
    if ids.is_empty() {
      return;
    }

    for &id in ids {
      // Remove the entries from their dependencies' dependents lists.
      // FIXME: Because the lifetime of each Entry is the same as the lifetime of the entire Graph,
      // I can't figure out how to iterate over one immutable Entry while mutating a different
      // mutable Entry... so I clone() here. Perhaps this is completely sane, because what's to say
      // they're not the same Entry after all? But regardless, less efficient than it could be.
      let dep_ids = entries[&id].dependencies.clone();
      for dep_id in dep_ids {
        entries.get_mut(&dep_id).map(|entry| {
          entry.dependents.remove(&id);
        });
      }

      // Validate that all dependents of the id are also scheduled for removal.
      assert!(entries[&id].dependents.iter().all(|dep| ids.contains(dep)));

      // Remove the entry itself.
      entries.remove(&id);
    }

    // Filter the Nodes to delete any with matching ids.
    let filtered: Vec<(Node, EntryId)> =
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

  pub fn visualize(&self, roots: &Vec<Node>, path: &Path, externs: &Externs) -> io::Result<()> {
    unimplemented!();
    /*
    let file = try!(File::create(path));
    let mut f = BufWriter::new(file);
    let mut viz_colors = HashMap::new();
    let viz_color_scheme = "set312";
    let viz_max_colors = 12;
    let mut format_color =
      |entry: &Entry| {
        match entry.state {
          None => "white".to_string(),
          Some(Complete::Noop(_, _)) => "white".to_string(),
          Some(Complete::Throw(_)) => "tomato".to_string(),
          Some(Complete::Return(_)) => {
            let viz_colors_len = viz_colors.len();
            viz_colors.entry(entry.node.selector().product().clone()).or_insert_with(|| {
              format!("{}", viz_colors_len % viz_max_colors + 1)
            }).clone()
          },
        }
      };

    try!(f.write_all(b"digraph plans {\n"));
    try!(f.write_fmt(format_args!("  node[colorscheme={}];\n", viz_color_scheme)));
    try!(f.write_all(b"  concentrate=true;\n"));
    try!(f.write_all(b"  rankdir=LR;\n"));

    let root_entries = roots.iter().filter_map(|n| self.entry(n)).map(|e| e.id()).collect();
    let predicate = |_| true;

    for entry in self.walk(root_entries, |_| true, false) {
      let node_str = entry.format(externs);

      // Write the node header.
      try!(f.write_fmt(format_args!("  \"{}\" [style=filled, fillcolor={}];\n", node_str, format_color(entry))));

      for (cyclic, adjacencies) in vec![(false, &entry.dependencies), (true, &entry.cyclic_dependencies)] {
        let style = if cyclic { " [style=dashed]" } else { "" };
        for &dep_id in adjacencies {
          let dep_entry = self.entry_for_id(dep_id);
          if !predicate(dep_entry) {
            continue;
          }

          // Write an entry per edge.
          let dep_str = dep_entry.format(externs);
          try!(f.write_fmt(format_args!("    \"{}\" -> \"{}\"{}\n", node_str, dep_str, style)));
        }
      }
    }

    try!(f.write_all(b"}\n"));
    Ok(())
    */
  }

  pub fn trace(&self, root: &Node, path: &Path, externs: &Externs) -> io::Result<()> {
    unimplemented!();
    /*
    let file = try!(OpenOptions::new().append(true).open(path));
    let mut f = BufWriter::new(file);

    let is_bottom = |entry: &Entry| -> bool {
      match entry.state() {
        None => false,
        Some(Complete::Throw(_)) => false,
        Some(Complete::Noop(_, _)) => true,
        Some(Complete::Return(_)) => true
      }
    };

    let is_one_level_above_bottom = |c: &Entry| -> bool {
      for d in &c.dependencies {
        if !is_bottom(self.entry_for_id(*d)) {
          return false;
        }
      }
      true
    };

    let _indent = |level: u32| -> String {
      let mut indent = String::new();
      for _ in 0..level {
        indent.push_str("  ");
      }
      indent
    };

    let _format = |entry: &Entry, level: u32| -> String {
      let indent = _indent(level);
      let output = format!("{}Computing {} for {}",
                           indent,
                           externs.id_to_str(entry.node.product().0),
                           externs.id_to_str(entry.node.subject().id()));
      if is_one_level_above_bottom(entry) {
        let state_str = match entry.state() {
          Some(Complete::Return(ref x)) => format!("Return({})", externs.val_to_str(x)),
          Some(Complete::Throw(ref x)) => format!("Throw({})", externs.val_to_str(x)),
          Some(Complete::Noop(ref x, ref opt_node)) => format!("Noop({:?}, {:?})", x, opt_node),
          None => String::new(),
        };
        format!("{}\n{}  {}", output, indent, state_str)
      } else {
        output
      }
    };

    let root_entries = vec![root].iter().filter_map(|n| self.entry(n)).map(|e| e.id()).collect();
    for t in self.leveled_walk(root_entries, |e,_| !is_bottom(e), false) {
      let (entry, level) = t;
      try!(write!(&mut f, "{}\n", _format(entry, level)));

      for dep_entry in &entry.cyclic_dependencies {
        let indent= _indent(level);
        try!(write!(&mut f, "{}cycle for {:?}\n", indent, dep_entry));
      }
    }

    try!(f.write_all(b"\n"));
    Ok(())
    */
  }
}

/**
 * A DAG (enforced on mutation) of Entries.
 */
pub struct Graph {
  inner: RwLock<InnerGraph>,
}

impl Graph {
  pub fn new() -> Graph {
    let inner =
      InnerGraph {
        id_generator: 0,
        nodes: HashMap::default(),
        entries: HashMap::default(),
        cyclic_singleton:
          future::Shared::new(future::err(Failure::Noop("Dep would be cyclic.", None)).boxed()),
      };
    Graph {
      inner: RwLock::new(inner),
    }
  }

  pub fn len(&self) -> usize {
    let inner = self.inner.read().unwrap();
    inner.entries.len()
  }

  /**
   * Returns a clone of the state of the given Node.
   */
  pub fn wait(&self, node: &Node, externs: &Externs) -> Option<NodeResult> {
    let inner = self.inner.read().unwrap();
    inner.entry(node)
      .map(|e| {
        // Wait for the Node, and then clone and convert its state
        match e.get().clone().wait() {
          Ok(ref v) => Ok(externs.clone_val(v)),
          Err(shared_err) => {
            match *shared_err {
              Failure::Noop(msg, ref n) => Err(Failure::Noop(msg, n.clone())),
              Failure::Throw(ref msg) => Err(Failure::Throw(externs.clone_val(msg))),
            }
          },
        }
      })
  }

  /**
   * In the context of the given src Node, declare a dependency on the given dst Node and
   * begin its execution if it has not already started.
   *
   * TODO: Restore the invariant that completed Nodes may only depend on other completed Nodes
   * to make cycle detection cheaper.
   */
  pub fn get(&self, src_id: EntryId, context: &ContextFactory, dst_node: &Node) -> NodeFuture {
    // First, check whether the destination already exists, and the dep is already declared.
    {
      let inner = self.inner.read().unwrap();
      let src_entry = inner.entry_for_id(src_id);
      if let Some(dst_entry) = inner.entry(dst_node) {
        if src_entry.dependencies().contains(&dst_entry.id) {
          // Declared and valid.
          return dst_entry.get().clone();
        } else if src_entry.cyclic_dependencies().contains(&dst_entry.id) {
          // Declared but cyclic.
          return inner.cyclic_singleton();
        }
      }
    }

    // Get or create the destination, and then insert the dep.
    // TODO: doing cycle detection under the writelock... unfortunate, but probably unavoidable
    // without a much more complicated algorithm.
    {
      let mut inner = self.inner.write().unwrap();
      let dst_id = inner.ensure_entry(context, dst_node.clone());
      if inner.detect_cycle(src_id, dst_id) {
        // Undeclared but cyclic.
        inner.entry_for_id_mut(src_id).cyclic_dependencies.insert(dst_id);
      } else {
        // Undeclared and valid.
        inner.entry_for_id_mut(src_id).dependencies.insert(dst_id);
        inner.entry_for_id_mut(dst_id).dependents.insert(src_id);
      }
    }

    // Recurse to retry (which should always succeed the first time).
    // TODO: will look up the Node multiple times.
    self.get(src_id, context, dst_node)
  }

  /**
   * Started the given Node if it has not already started.
   */
  pub fn started(&self, node: Node, context: &ContextFactory) -> NodeFuture {
    let mut inner = self.inner.write().unwrap();
    let id = inner.ensure_entry(context, node);
    inner.entry_for_id(id).get().clone()
  }

  pub fn invalidate(&self, subjects: HashSet<&Key, FNV>) -> usize {
    let mut inner = self.inner.write().unwrap();
    inner.invalidate(subjects)
  }

  pub fn trace(&self, root: &Node, path: &Path, externs: &Externs) -> io::Result<()> {
    let inner = self.inner.read().unwrap();
    inner.trace(root, path, externs)
  }

  pub fn visualize(&self, roots: &Vec<Node>, path: &Path, externs: &Externs) -> io::Result<()> {
    let inner = self.inner.read().unwrap();
    inner.visualize(roots, path, externs)
  }
}

/**
 * Represents the state of a particular topological walk through a Graph. Implements Iterator and
 * has the same lifetime as the Graph itself.
 */
struct Walk<'a, P: Fn(&Entry)->bool> {
  graph: &'a InnerGraph,
  dependents: bool,
  deque: VecDeque<EntryId>,
  walked: HashSet<EntryId, FNV>,
  predicate: P,
}

impl<'a, P: Fn(&Entry)->bool> Iterator for Walk<'a, P> {
  type Item = &'a Entry;

  fn next(&mut self) -> Option<&'a Entry> {
    while let Some(id) = self.deque.pop_front() {
      if self.walked.contains(&id) {
        continue;
      }
      self.walked.insert(id);

      let entry = self.graph.entry_for_id(id);
      if !(self.predicate)(entry) {
        continue;
      }

      // Entry matches.
      if self.dependents {
        self.deque.extend(&entry.dependents);
      } else {
        self.deque.extend(&entry.dependencies);
      }
      return Some(entry);
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
  dependents: bool,
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

      // Entry matches.
      if self.dependents {
        for d in &entry.dependents {
          self.deque.push_back((*d, level+1));
        }
      } else {
        for d in &entry.dependencies {
          self.deque.push_back((*d, level+1));
        }
      }
      return Some((entry, level));
    }

    None
  }
}
