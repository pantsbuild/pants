
use std::collections::{hash_set, HashMap, HashSet, VecDeque};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::io;
use std::iter;
use std::path::Path;

use externs::ToStrFunction;
use core::FNV;
use nodes::{Node, Complete, State};

pub type EntryId = usize;

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
pub struct Entry {
  id: EntryId,
  // TODO: This is a clone of the Node, which is also kept in the `nodes` map. It would be
  // nice to avoid keeping two copies of each Node, but tracking references between the two
  // maps is painful.
  node: Node,
  state: State<EntryId>,
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

  pub fn state(&self) -> &State<EntryId> {
    &self.state
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

  pub fn is_staged(&self) -> bool {
    match &self.state {
      &State::Staged(_) => true,
      &State::Complete(_) => true,
      _ => false,
    }
  }

  pub fn is_complete(&self) -> bool {
    match &self.state {
      &State::Complete(_) => true,
      _ => false,
    }
  }

  fn format(&self, to_str: &ToStrFunction) -> String {
    let state =
      match self.state {
        State::Complete(Complete::Return(r)) => to_str.call(r.digest()),
        ref x => format!("{:?}", x),
      };
    format!(
      "{}:{}:{} == {}",
      self.node.format(to_str),
      to_str.call(self.node.subject().digest()),
      to_str.call(self.node.product()),
      state,
    ).replace("\"", "\\\"")
  }
}

type Nodes = HashMap<Node, EntryId, FNV>;
type Entries = Vec<Entry>;

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
      nodes: HashMap::default(),
      entries: Vec::new(),
    }
  }

  pub fn len(&self) -> usize {
    self.entries.len()
  }

  fn is_complete(&self, node: &Node) -> bool {
    self.entry(node).map(|entry| entry.is_complete()).unwrap_or(false)
  }

  fn is_complete_entry(&self, id: EntryId) -> bool {
    self.entry_for_id(id).is_complete()
  }

  pub fn dependencies_all<P>(&self, id: EntryId, predicate: P) -> bool
      where P: Fn(&Entry)->bool {
    self.entry_for_id(id).dependencies.iter().all(|&d| predicate(self.entry_for_id(d)))
  }

  pub fn entry(&self, node: &Node) -> Option<&Entry> {
    self.nodes.get(node).map(|&id| self.entry_for_id(id))
  }

  pub fn entry_for_id(&self, id: EntryId) -> &Entry {
    &self.entries[id]
  }

  pub fn entry_for_id_mut(&mut self, id: EntryId) -> &mut Entry {
    &mut self.entries[id]
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
        let id = *id_generator;
        *id_generator += 1;
        id
      }).clone();

    // If this was an existing entry, we're done..
    if id < entries.len() {
      return id;
    }

    // New entry.
    assert!(
      id == entries.len(),
      "Entry id generator mismatched entries length: {} vs {}", id, entries.len()
    );
    entries.push(
      Entry {
        id: id,
        node: entry_node,
        state: State::empty_waiting(),
        dependencies: Vec::with_capacity(4),
        dependents: Vec::with_capacity(4),
        cyclic_dependencies: Vec::with_capacity(0),
      }
    );

    id
  }

  pub fn set_state(&mut self, id: EntryId, next_state: State<Node>) {
    // Validate the State change.
    match (self.entry_for_id(id).state(), &next_state) {
      (&State::Waiting(_), &State::Complete(_)) =>
        assert!(self.dependencies_all(id, Entry::is_complete), "Node {:?} has incomplete deps.", id),
      (&State::Waiting(_), &State::Staged(_)) =>
        (),
      (&State::Waiting(_), &State::Waiting(_)) =>
        (),
      (&State::Staged(_), &State::Complete(_)) =>
        (),
      (&State::Staged(ref s), t) =>
        panic!("A staged Node may only complete!: from {:?} to {:?}", s, t),
      (&State::Complete(ref c), t) =>
        panic!("Cannot change the State of a completed Node!: from {:?} to {:?}", c, t),
    };

    // The change is valid! Add all dependencies from the state, and then store it.
    let state = next_state.map(|n| self.ensure_entry(n));
    state.dependencies().map(|dst_ids| self.add_dependencies(id, dst_ids));
    self.entry_for_id_mut(id).state = state;
  }

  /**
   * Adds the given dst Nodes as dependencies of the src Node, and returns true if any of them
   * were cyclic.
   *
   * Preserves the invariant that completed Nodes may only depend on other completed Nodes.
   */
  fn add_dependencies(&mut self, src_id: EntryId, dsts: DepSet) {
    assert!(
      !self.is_complete_entry(src_id),
      "Node {:?} is already completed, and may not have new dependencies added: {:?}",
      src_id,
      dsts,
    );

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
   * Removes the given invalidation roots and their transitive dependents from the Graph.
   */
  pub fn invalidate(&mut self, roots: &Vec<Node>) -> usize {
    // Eagerly collect all entries that will be deleted before we begin mutating anything.
    let ids: HashSet<EntryId, FNV> = {
      let root_ids = roots.iter().filter_map(|n| self.entry(n)).map(|e| e.id).collect();
      self.walk(root_ids, { |_| true }, true).map(|e| e.id()).collect()
    };
    Graph::invalidate_internal(
      &mut self.entries,
      &mut self.nodes,
      ids,
    )
  }

  fn invalidate_internal(entries: &mut Entries, nodes: &mut Nodes, ids: HashSet<EntryId, FNV>) -> usize {
    // Remove the roots from their dependencies' dependents lists.
    panic!("FIXME: Needs updating for Entries-as-array.");
    for &id in &ids {
      // FIXME: Because the lifetime of each Entry is the same as the lifetime of the entire Graph,
      // I can't figure out how to iterate over one immutable Entry while mutating a different
      // mutable Entry... so I clone() here. Perhaps this is completely sane, because what's to say
      // they're not the same Entry after all? But regardless, less efficient than it could be.
      let dep_ids = entries[id].dependencies.clone();
      for dep_id in dep_ids {
        match entries.get_mut(dep_id) {
          Some(entry) => { entry.dependents.retain(|&dependent| dependent != id); () },
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

  pub fn visualize(&self, roots: &Vec<Node>, path: &Path, to_str: &ToStrFunction) -> io::Result<()> {
    let file = try!(File::create(path));
    let mut f = BufWriter::new(file);
    let mut viz_colors = HashMap::new();
    let viz_color_scheme = "set312";
    let viz_max_colors = 12;
    let mut format_color =
      |entry: &Entry| {
        match entry.state {
          State::Complete(Complete::Noop(_, _)) => "white".to_string(),
          State::Complete(Complete::Throw(_)) => "tomato".to_string(),
          State::Complete(Complete::Return(_)) => {
            let viz_colors_len = viz_colors.len();
            viz_colors.entry(entry.node.product().clone()).or_insert_with(|| {
              format!("{}", viz_colors_len % viz_max_colors + 1)
            }).clone()
          },
          State::Staged(_) => "limegreen".to_string(),
          State::Waiting(_) => "lightyellow".to_string(),
        }
      };

    try!(f.write_all(b"digraph plans {\n"));
    try!(f.write_fmt(format_args!("  node[colorscheme={}];\n", viz_color_scheme)));
    try!(f.write_all(b"  concentrate=true;\n"));
    try!(f.write_all(b"  rankdir=LR;\n"));

    let root_entries = roots.iter().filter_map(|n| self.entry(n)).map(|e| e.id()).collect();
    let predicate = |_| true;

    for entry in self.walk(root_entries, |_| true, false) {
      let node_str = entry.format(to_str);

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
          let dep_str = dep_entry.format(to_str);
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
