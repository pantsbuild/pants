
use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::io;
use std::path::Path;

use externs::Externs;
use core::{FNV, Key};
use nodes::{Node, Complete};

#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct EntryId(usize);

pub type DepSet = Vec<EntryId>;

/**
 * An Entry and its adjacencies.
 *
 * The dependencies and cyclic_dependencies sets are stored as vectors in order to expose
 * them more easily via the C API, but they should never contain dupes.
 *
 * NB: The average number of dependencies for a Node is somewhere between 1 and 2, so Vec is
 * not too crazy (although maintaining sorted order and then binary-searching in sufficiently
 * large Vecs would make sense).
 */
#[derive(Debug)]
pub struct Entry {
  id: EntryId,
  // TODO: This is a clone of the Node, which is also kept in the `nodes` map. It would be
  // nice to avoid keeping two copies of each Node, but tracking references between the two
  // maps is painful.
  node: Node,
  state: Option<Complete>,
  // Sets of all Nodes which have ever been awaited by this Node.
  dependencies: DepSet,
  dependents: DepSet,
  // Deps that would be illegal to actually provide, since they would be cyclic.
  cyclic_dependencies: DepSet,
}

impl Entry {
  pub fn id(&self) -> EntryId {
    self.id
  }

  pub fn node(&self) -> &Node {
    &self.node
  }

  pub fn state(&self) -> Option<&Complete> {
    self.state.as_ref()
  }

  pub fn dependencies(&self) -> &DepSet {
    &self.dependencies
  }

  pub fn dependents(&self) -> &DepSet {
    &self.dependents
  }

  pub fn cyclic_dependencies(&self) -> &DepSet {
    &self.cyclic_dependencies
  }

  pub fn is_complete(&self) -> bool {
    self.state.is_some()
  }

  fn format(&self, externs: &Externs) -> String {
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
  }
}

type Nodes = HashMap<Node, EntryId, FNV>;
type Entries = HashMap<EntryId, Entry, FNV>;

/**
 * A DAG (enforced on mutation) of Entries.
 */
pub struct Graph {
  id_generator: usize,
  nodes: Nodes,
  entries: Entries,
  cyclic_singleton: Complete,
}

impl Graph {
  pub fn new() -> Graph {
    Graph {
      id_generator: 0,
      nodes: HashMap::default(),
      entries: HashMap::default(),
      cyclic_singleton: Complete::Noop("Dep would be cyclic.", None),
    }
  }

  pub fn cyclic_singleton(&self) -> &Complete {
    &(self.cyclic_singleton)
  }

  pub fn len(&self) -> usize {
    self.entries.len()
  }

  pub fn is_complete_entry(&self, id: EntryId) -> bool {
    self.entry_for_id(id).is_complete()
  }

  pub fn is_ready_entry(&self, id: EntryId) -> bool {
    !self.is_complete_entry(id) && self.dependencies_all(id, |e| e.is_complete())
  }

  pub fn dependencies_all<P>(&self, id: EntryId, predicate: P) -> bool
      where P: Fn(&Entry)->bool {
    self.entry_for_id(id).dependencies.iter().all(|&d| predicate(self.entry_for_id(d)))
  }

  pub fn entry(&self, node: &Node) -> Option<&Entry> {
    self.nodes.get(node).map(|&id| self.entry_for_id(id))
  }

  pub fn entry_for_id(&self, id: EntryId) -> &Entry {
    self.entries.get(&id).unwrap_or_else(|| panic!("Invalid EntryId: {:?}", id))
  }

  pub fn entry_for_id_mut(&mut self, id: EntryId) -> &mut Entry {
    self.entries.get_mut(&id).unwrap_or_else(|| panic!("Invalid EntryId: {:?}", id))
  }

  pub fn ensure_entry(&mut self, node: Node) -> EntryId {
    Graph::ensure_entry_internal(
      &mut self.entries,
      &mut self.nodes,
      &mut self.id_generator,
      node
    )
  }

  fn ensure_entry_internal<'a>(
    entries: &'a mut Entries,
    nodes: &mut Nodes,
    id_generator: &mut usize,
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

    // New entry.
    *id_generator += 1;
    entries.insert(
      id,
      Entry {
        id: id,
        node: entry_node,
        state: None,
        dependencies: Vec::new(),
        dependents: Vec::new(),
        cyclic_dependencies: Vec::new(),
      }
    );

    id
  }

  pub fn complete(&mut self, id: EntryId, state: Complete) {
    assert!(self.is_ready_entry(id), "Node {:?} is already completed, or has incomplete deps.", self.entry_for_id(id));

    self.entry_for_id_mut(id).state = Some(state);
  }

  /**
   * Adds the given dst Nodes as dependencies of the src Node, and returns true if any of them
   * were cyclic.
   *
   * Preserves the invariant that completed Nodes may only depend on other completed Nodes.
   */
  pub fn add_dependencies(&mut self, src_id: EntryId, dst_nodes: Vec<Node>) {
    assert!(
      !self.is_complete_entry(src_id),
      "Node {:?} is already completed, and may not have new dependencies added: {:?}",
      src_id,
      dst_nodes,
    );

    let dsts: Vec<EntryId> = dst_nodes.into_iter().map(|n| self.ensure_entry(n)).collect();

    // Determine whether each awaited dep is cyclic.
    let (deps, cyclic_deps): (DepSet, DepSet) = {
      let src = self.entry_for_id(src_id);
      dsts.into_iter()
        .filter(|dst_id| !(src.dependencies.contains(dst_id) || src.cyclic_dependencies.contains(dst_id)))
        .partition(|&dst_id| !self.detect_cycle(src_id, dst_id))
    };

    // Add the source as a dependent of each non-cyclic dep.
    for &dep in &deps {
      self.entry_for_id_mut(dep).dependents.push(src_id);
    }

    // Finally, add all deps to the source.
    let src = self.entry_for_id_mut(src_id);
    src.dependencies.extend(deps);
    src.cyclic_dependencies.extend(cyclic_deps);
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
   * Finds all Nodes with the given subjects, and invalidates their transitive dependents.
   */
  pub fn invalidate(&mut self, subjects: HashSet<&Key, FNV>) -> usize {
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
    Graph::invalidate_internal(
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
          entry.dependents.retain(|&dependent| dependent != id);
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
  }
}

/**
 * Represents the state of a particular topological walk through a Graph. Implements Iterator and
 * has the same lifetime as the Graph itself.
 */
struct Walk<'a, P: Fn(&Entry)->bool> {
  graph: &'a Graph,
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
