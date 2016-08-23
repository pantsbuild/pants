use std::collections::{HashMap, HashSet, VecDeque};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::io;
use std::path::Path;

use nodes::{Node, Complete};

pub type EntryId = u64;

/**
 * An Entry and its adjacencies.
 *
 * The dependencies and cyclic_dependencies sets are stored as vectors in order to expose
 * them more easily via the C API, but they should never contain dupes.
 */
pub struct Entry {
  id: EntryId,
  // TODO: This is a clone of the Node, which is also kept in the `nodes` map. It would be
  // nice to avoid keeping two copies of each Node, but tracking references between the two
  // maps is painful.
  node: Node,
  state: Option<Complete>,
  // Sets of all Nodes which have ever been awaited by this Node.
  dependencies: HashSet<EntryId>,
  dependents: HashSet<EntryId>,
  // Deps that would be illegal to actually provide, since they would be cyclic.
  cyclic_dependencies: HashSet<EntryId>,
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

  pub fn dependencies(&self) -> &HashSet<EntryId> {
    &self.dependencies
  }

  pub fn dependents(&self) -> &HashSet<EntryId> {
    &self.dependents
  }

  pub fn cyclic_dependencies(&self) -> &HashSet<EntryId> {
    &self.cyclic_dependencies
  }

  pub fn is_complete(&self) -> bool {
    self.state.is_some()
  }
}

type Nodes = HashMap<Node, EntryId>;
type Entries = HashMap<EntryId, Entry>;

/**
 * A DAG (enforced on mutation) of Entries.
 */
pub struct Graph {
  id_generator: EntryId,
  nodes: Nodes,
  entries: Entries,
}

impl Graph {
  pub fn new() -> Graph {
    Graph {
      id_generator: 0,
      nodes: HashMap::new(),
      entries: HashMap::new(),
    }
  }

  pub fn len(&self) -> usize {
    self.entries.len()
  }

  fn is_complete(&self, node: &Node) -> bool {
    self.entry(node).map(|entry| entry.is_complete()).unwrap_or(false)
  }

  fn is_complete_entry(&self, id: EntryId) -> bool {
    self.entries.get(&id).map(|entry| entry.is_complete()).unwrap_or(false)
  }

  fn is_ready(&self, id: EntryId) -> bool {
    self.is_ready_entry(self.entry_for_id(id))
  }

  /**
   * A Node is 'ready' (to run) when it is not complete, but all of its dependencies
   * are complete.
   */
  pub fn is_ready_entry(&self, entry: &Entry) -> bool {
    !entry.is_complete() && (
      entry.dependencies.iter()
        .filter_map(|d| self.entries.get(d))
        .all(|d| { d.is_complete() })
    )
  }

  pub fn entry(&self, node: &Node) -> Option<&Entry> {
    self.nodes.get(node).map(|&id| self.entry_for_id(id))
  }

  pub fn entry_for_id(&self, id: EntryId) -> &Entry {
    self.entries.get(&id).unwrap_or_else(|| {
      panic!("No Entry exists for {}!", id);
    })
  }

  pub fn entry_for_id_mut(&mut self, id: EntryId) -> &mut Entry {
    self.entries.get_mut(&id).unwrap_or_else(|| {
      panic!("No Entry exists for {}!", id);
    })
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
    id_generator: &mut EntryId,
    node: Node
  ) -> EntryId {
    // See TODO on Entry.
    let entry_node = node.clone();
    let id =
      nodes.entry(node).or_insert_with(|| {
        *id_generator += 1;
        *id_generator
      }).clone();

    // Update the Nodes map if needed.
    entries.entry(id).or_insert_with(||
      Entry {
        id: id,
        node: entry_node,
        state: None,
        dependencies: HashSet::new(),
        dependents: HashSet::new(),
        cyclic_dependencies: HashSet::new(),
      }
    );

    id
  }

  pub fn complete(&mut self, id: EntryId, state: Complete) {
    assert!(self.is_ready(id), "Node {:?} is already completed, or has incomplete deps.", id);

    let entry = self.entry_for_id_mut(id);
    entry.state = Some(state);
  }

  /**
   * Adds the given dst Nodes as dependencies of the src Node.
   *
   * Preserves the invariant that completed Nodes may only depend on other completed Nodes.
   */
  pub fn add_dependencies(&mut self, src_id: EntryId, dsts: Vec<Node>) {
    assert!(
      !self.is_complete_entry(src_id),
      "Node {:?} is already completed, and may not have new dependencies added: {:?}",
      src_id,
      dsts,
    );

    // Determine whether each awaited dep is cyclic.
    // TODO: skip cycle detection for deps that are already valid.
    let (deps, cyclic_deps): (HashSet<_>, HashSet<_>) =
      dsts.into_iter()
        .map(|dst| self.ensure_entry(dst))
        .collect::<HashSet<_>>()
        .into_iter()
        .partition(|&dst_id| !self.detect_cycle(src_id, dst_id));

    println!(">>> rust adding deps to {}: {:?} and {:?}", src_id, deps, cyclic_deps);
    
    // Add the source as a dependent of each non-cyclic dep.
    for &dep in &deps {
      self.entry_for_id_mut(dep).dependents.insert(src_id);
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
      walked: HashSet::new(),
      predicate: predicate,
    }
  }

  /**
   * Removes the given invalidation roots and their transitive dependents from the Graph.
   */
  pub fn invalidate(&mut self, roots: &Vec<Node>) -> usize {
    // Eagerly collect all entries that will be deleted before we begin mutating anything.
    let ids: HashSet<EntryId> = {
      let root_ids = roots.iter().filter_map(|n| self.entry(n)).map(|e| e.id).collect();
      self.walk(root_ids, { |_| true }, true).map(|e| e.id()).collect()
    };
    Graph::invalidate_internal(
      &mut self.entries,
      &mut self.nodes,
      ids,
    )
  }

  fn invalidate_internal(entries: &mut Entries, nodes: &mut Nodes, ids: HashSet<EntryId>) -> usize {
    // Remove the roots from their dependencies' dependents lists.
    for id in &ids {
      // FIXME: Because the lifetime of each Entry is the same as the lifetime of the entire Graph,
      // I can't figure out how to iterate over one immutable Entry while mutating a different
      // mutable Entry... so I clone() here. Perhaps this is completely sane, because what's to say
      // they're not the same Entry after all? But regardless, less efficient than it could be.
      let dep_ids = entries.get(id).map(|e| e.dependencies.clone()).unwrap_or(HashSet::new());
      for dep_id in dep_ids {
        match entries.get_mut(&dep_id) {
          Some(entry) => { entry.dependents.remove(&entry.id); () },
          _ => {},
        }
      }

      entries.remove(id);
    }

    // Filter the Nodes to delete any with matching keys.
    let filtered: Vec<(Node, EntryId)> =
      nodes.drain()
        .filter(|&(_, id)| ids.contains(&id))
        .collect();
    nodes.extend(filtered);

    entries.len()
  }

  pub fn visualize(&self, roots: &Vec<Node>, path: &Path) -> io::Result<()> {
    let file = try!(File::create(path));
    let mut writer = BufWriter::new(file);
    self.visualize_internal(roots, &mut writer)
  }

  fn visualize_internal<F: Write>(&self, roots: &Vec<Node>, f: &mut BufWriter<F>) -> io::Result<()> {
    let mut viz_colors = HashMap::new();
    let viz_color_scheme = "set312";
    let viz_max_colors = 12;

    try!(f.write_all(b"digraph plans {"));
    try!(f.write_fmt(format_args!("  node[colorscheme={}];", viz_color_scheme)));
    try!(f.write_all(b"  concentrate=true;"));
    try!(f.write_all(b"  rankdir=LR;"));

    let root_entries = roots.iter().filter_map(|n| self.entry(n)).map(|e| e.id()).collect();
    let predicate = |_| true;

    for entry in self.walk(root_entries, |_| true, false) {
      let node_str = format_node(entry.node, entry.state);

      try!(f.write_fmt(format_args!("  \"{}\" [style=filled, fillcolor={}];", node_str, format_color(entry.node, entry.state))));

      for (cyclic, adjacencies) in vec![(false, entry.dependencies), (true, entry.cyclic_dependencies)] {
        for dep_id in adjacencies {
          let dep_entry = self.entry_for_id(dep_id);
          if !predicate(dep_entry) {
            continue;
          }
          try!(f.write_all(format_edge(node_str, format_node(dep_entry), cyclic)));
        }
      }
    }

    try!(f.write_all(b"}"));
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
  walked: HashSet<EntryId>,
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

      match self.graph.entries.get(&id) {
        Some(entry) if (self.predicate)(entry) => {
          if self.dependents {
            self.deque.extend(&entry.dependents);
          } else {
            self.deque.extend(&entry.dependencies);
          }
          return Some(entry);
        }
        _ => {},
      }
    };
    None
  }
}
