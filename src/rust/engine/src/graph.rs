use std::collections::{HashMap, HashSet, VecDeque};
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
  node: Node,
  state: Option<Complete>,
  // Sets of all Nodes which have ever been awaited by this Node.
  dependencies: HashSet<EntryId>,
  dependents: HashSet<EntryId>,
  // Vec of Nodes which are currently being awaited by this Node, with a corresponding
  // boolean array to indicate whether the awaited value was cyclic.
  awaiting: Vec<EntryId>,
  awaiting_cyclic: Vec<bool>,
}

impl Entry {
  pub fn id(&self) -> EntryId {
    self.id
  }

  pub fn node(&self) -> &Node {
    &self.node
  }

  pub fn dependencies(&self) -> &HashSet<EntryId> {
    &self.dependencies
  }

  pub fn dependents(&self) -> &HashSet<EntryId> {
    &self.dependents
  }

  pub fn is_complete(&self) -> bool {
    self.state.is_some()
  }
}

/**
 * A DAG (enforced on mutation) of Entries.
 */
pub struct Graph<'a> {
  id_generator: EntryId,
  nodes: HashMap<&'a Node, EntryId>,
  entries: HashMap<EntryId, Entry>,
}

impl<'a> Graph<'a> {
  fn new() -> Graph<'a> {
    Graph {
      id_generator: 0,
      nodes: HashMap::new(),
      entries: HashMap::new(),
    }
  }

  fn len(&self) -> u64 {
    self.entries.len() as u64
  }

  fn is_complete(&self, node: &Node) -> bool {
    self.entry(node).map(|entry| entry.is_complete()).unwrap_or(false)
  }

  fn is_complete_entry(&self, id: EntryId) -> bool {
    self.entries.get(&id).map(|entry| entry.is_complete()).unwrap_or(false)
  }

  fn is_ready(&self, node: &Node) -> bool {
    self.entry(node).map(|e| self.is_ready_entry(e)).unwrap_or(true)
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
    self.nodes.get(node).map(|&id| &*self.entry_for_id(id))
  }

  pub fn entry_for_id(&mut self, id: EntryId) -> &mut Entry {
    self.entries.get_mut(&id).unwrap_or_else(|| {
      panic!("No Entry exists for {}!", id);
    });
  }

  pub fn ensure_entry(&'a mut self, node: Node) -> &mut Entry {
    let entry_id =
      self.nodes.entry(&node).or_insert_with(|| {
        self.id_generator += 1;
        self.id_generator
      }).clone();

    self.entries.entry(entry_id).or_insert_with(||
      Entry {
        id: entry_id,
        node: node,
        state: None,
        dependencies: HashSet::new(),
        dependents: HashSet::new(),
        awaiting: Vec::new(),
        awaiting_cyclic: Vec::new(),
      }
    )
  }

  pub fn complete(&'a mut self, id: EntryId, state: Complete) {
    let entry = self.entry_for_id(id);
    assert!(
      self.is_ready_entry(entry),
      "Node {:?} is already completed, or has incomplete deps.",
      entry.node,
    );

    entry.state = Some(state);
    entry.awaiting.clear();
    entry.awaiting_cyclic.clear();
  }

  /**
   * Adds the given dst Nodes as dependencies of the src Node.
   *
   * Preserves the invariant that completed Nodes may only depend on other completed Nodes.
   */
  pub fn add_dependencies(&'a mut self, src: &mut Entry, dsts: Vec<Node>) {
    assert!(
      !src.is_complete(),
      "Node {:?} is already completed, and may not have new dependencies added: {:?}",
      src.node(),
      dsts,
    );

    // Determine whether each awaited dep is cyclic, and record the non-cyclic ones.
    let mut was_cyclic = Vec::new();
    for dst in dsts {
      let cyclic = self.detect_cycle(&src, &dst);
      was_cyclic.push(cyclic);
      if !cyclic {
        self.ensure_entry(dst).dependents.insert(src.id());
      }
    }

    // Finally, add all non-cyclic deps.
    let dst_entries: Vec<&Entry> = dsts.iter().filter_map(|d| self.entry(d)).collect();
    src.dependencies.extend(
      dst_entries.iter().zip(was_cyclic.iter())
        .filter_map(|(dst, &cyclic)| {
          if !cyclic {
            Some(dst)
          } else {
            None
          }
        })
        .map(|dst| dst.id)
    );

    // Then record the complete awaited set.
    src.awaiting = dst_entries.iter().map(|dst| dst.id).collect();
    src.awaiting_cyclic = was_cyclic;
  }

  /**
   * Detect whether adding an edge from src to dst would create a cycle.
   *
   * Returns true if a cycle would be created by adding an edge from src->dst.
   */
  fn detect_cycle(&self, src: &Entry, dst_node: &Node) -> bool {
    if let Some(dst) = self.entry(dst_node) {
      // Search for an existing path from dst ('s dependencies) to src.
      let roots = dst.dependencies.into_iter().collect();
      self.walk(roots, { |e| !e.is_complete() }, false).any(|e| e.id == src.id)
    } else {
      // dst does not already exist... no cycle possible.
      false
    }
  }

  /**
   * Begins a topological Walk from the given roots.
   */
  pub fn walk<P>(&self, roots: VecDeque<EntryId>, predicate: P, dependents: bool) -> Walk<P>
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
    // eagerly collect all Nodes before we begin mutating anything.
    let entries: Vec<&Entry> = {
      let root_ids = roots.iter().filter_map(|n| self.entry(n)).map(|e| e.id).collect();
      self.walk(root_ids, { |_| true }, true).collect()
    };

    for entry in &entries {
      // remove the roots from their dependencies' dependents lists.
      // FIXME: Because the lifetime of each Entry is the same as the lifetime of the entire Graph,
      // I can't figure out how to iterate over one immutable Entry while mutating a different
      // mutable Entry... so I clone() here. Perhaps this is completely sane, because what's to say
      // they're not the same Entry after all? But regardless, less efficient than it could be.
      for dep_id in entry.dependencies.clone() {
        match self.entries.get_mut(&dep_id) {
          Some(entry) => { entry.dependents.remove(&entry.id); () },
          _ => {},
        }
      }

      // delete each Node
      self.nodes.remove(&entry.node);
      self.entries.remove(&entry.id);
    }

    entries.len()
  }
}

/**
 * Represents the state of a particular topological walk through a Graph. Implements Iterator and
 * has the same lifetime as the Graph itself.
 */
struct Walk<'a, P: Fn(&Entry)->bool> {
  graph: &'a Graph<'a>,
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
