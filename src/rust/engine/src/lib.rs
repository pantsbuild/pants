mod core;
mod nodes;

use std::collections::{HashMap, HashSet, VecDeque};

use nodes::{Node, State};

type EntryId = u64;

/**
 * An Entry and its adjacencies.
 *
 * The dependencies and cyclic_dependencies sets are stored as vectors in order to expose
 * them more easily via the C API, but they should never contain dupes.
 */
pub struct Entry {
  id: EntryId,
  node: Node,
  state: State,
  // Sets of all Nodes which have ever been awaited by this Node.
  dependencies: HashSet<EntryId>,
  dependents: HashSet<EntryId>,
  // Vec of Nodes which are currently being awaited by this Node, with a corresponding
  // boolean array to indicate whether the awaited value was cyclic.
  awaiting: Vec<EntryId>,
  awaiting_cyclic: Vec<bool>,
}

impl Entry {
  fn is_complete(&self) -> bool {
    match self.state {
      Waiting => true,
      _ => false,
    }
  }
}

/**
 * A DAG (enforced on mutation) of Entries.
 */
pub struct Graph {
  id_generator: EntryId,
  nodes: HashMap<Node, EntryId>,
  entries: HashMap<EntryId, Entry>,
}

impl Graph {
  fn new() -> Graph {
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

  /**
   * A Node is 'ready' (to run) when it is not complete, but all of its dependencies
   * are complete.
   */
  fn is_ready(&self, node: &Node) -> bool {
    (!self.is_complete(node)) && (
      self.entry(node).map(|e| {
          e.dependencies
            .iter()
            .all(|d| { self.is_complete_entry(*d) })
        }).unwrap_or(true)
    )
  }

  fn entry(&self, node: &Node) -> Option<&Entry> {
    self.nodes.get(node).and_then(|id| self.entries.get(id))
  }

  fn ensure_entry(&mut self, node: Node) -> &mut Entry {
    let entry_id =
      self.nodes.entry(node).or_insert_with(|| {
        self.id_generator += 1;
        self.id_generator
      }).clone();

    self.entries.entry(entry_id).or_insert_with(||
      Entry {
        id: entry_id,
        node: node,
        state: State::Waiting { dependencies: Vec::new() },
        dependencies: HashSet::new(),
        dependents: HashSet::new(),
        awaiting: Vec::new(),
        awaiting_cyclic: Vec::new(),
      }
    )
  }

  fn complete(&mut self, node: Node, state: State) {
    assert!(
      self.is_ready(&node),
      "Node {:?} is already completed, or has incomplete deps.",
      node,
    );
    let mut entry = self.ensure_entry(node);
    entry.state = state;
    entry.awaiting.clear();
    entry.awaiting_cyclic.clear();
  }

  /**
   * Adds the given dst Nodes as dependencies of the src Node.
   *
   * Preserves the invariant that completed Nodes may only depend on other completed Nodes.
  fn await(&mut self, src: Node, dsts: &Vec<Node>) {
    assert!(
      !self.is_complete(src),
      "Node {:?} is already completed, and may not have new dependencies added: {:?}",
      src,
      dsts,
    );

    // Determine whether each awaited dep is cyclic, and record the non-cyclic ones.
    let mut was_cyclic = Vec::new();
    for &dst in dsts {
      let cyclic = self.detect_cycle(src, dst);
      was_cyclic.push(cyclic);
      if !cyclic {
        self.ensure_entry(dst).dependents.insert(src);
      }
    }

    // Finally, borrow the src and add all non-cyclic deps.
    let entry = self.ensure_entry(src);
    entry.dependencies.extend(dsts.iter().zip(was_cyclic.iter())
      .filter_map(|(dst, &cyclic)| {
        if !cyclic {
          Some(dst)
        } else {
          None
        }
      })
    );

    // Then record the complete awaited set.
    entry.awaiting = dsts.clone();
    entry.awaiting_cyclic = was_cyclic;
  }
   */

  /**
   * Detect whether adding an edge from src to dst would create a cycle.
   *
   * Returns true if a cycle would be created by adding an edge from src->dst.
   */
  fn detect_cycle(&self, src: &Node, dst: &Node) -> bool {
    let entries = self.entry(dst).and_then(|d| self.entry(src).map(|s| (s, d)));
    if let Some((src_entry, dst_entry)) = entries {
      // Search for an existing path from dst ('s dependencies) to src.
      let roots = dst_entry.dependencies.into_iter().collect();
      self.walk(roots, { |e| !e.is_complete() }, false).any(|e| e.id == src_entry.id)
    } else {
      // Either src or dst does not already exist... no cycle possible.
      false
    }
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
  fn invalidate(&mut self, roots: &Vec<Node>) -> usize {
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

/**
 * Primitive structs to allow a list of steps to be directly exposed to python.
 *
 * NB: This is marked `allow(dead_code)` because it's only used in the C API.
 */
#[allow(dead_code)]
pub struct RawStep {
  node: Node,
  awaiting_ptr: *mut Node,
  awaiting_len: u64,
  awaiting_cyclic_ptr: *mut bool,
  awaiting_cyclic_len: u64,
}

pub struct RawSteps {
  steps_ptr: *mut RawStep,
  steps_len: u64,
}

/**
 * Represents the state of an execution of (a subgraph of) a Graph.
 */
pub struct Execution {
  ready: Vec<RawStep>,
  ready_raw: *mut RawSteps,
}

impl Execution {
  /**
   * Begins an Execution from the given root Nodes.
   */
  fn new() -> Execution {
    let mut execution =
      Execution {
        ready: Vec::new(),
        ready_raw:
          Box::into_raw(
            Box::new(
              RawSteps {
                steps_ptr: Vec::new().as_mut_ptr(),
                steps_len: 0,
              }
            )
          ),
      };
    // replace the soon-to-be-invalid nodes_ptr with a live pointer.
    // TODO: determine the syntax for instantiating and using the Vec inline above.
    with_raw_steps(execution.ready_raw, |rr| {
      rr.steps_ptr = execution.ready.as_mut_ptr()
    });
    execution
  }

  /**
   * Continues execution after the waiting Nodes given Nodes have completed with the given states.
   */
  fn next(&mut self, graph: &mut Graph, changed: &Vec<Node>) {
    let mut candidates: HashSet<Node> = HashSet::new();

    // For each changed node, determine whether its dependents or itself are a candidate.
    for &node in changed {
      match graph.entry(&node) {
        Some(entry) if entry.is_complete() => {
          // Mark any dependents of the Node as candidates.
          candidates.extend(&entry.dependents);
        },
        Some(entry) => {
          // If all dependencies of the Node are completed, the Node itself is a candidate.
          let incomplete_deps: Vec<Node> =
            entry.dependencies
              .iter()
              .map(|d| *d)
              .filter(|&d| { !graph.is_complete(d) })
              .collect();
          if incomplete_deps.len() > 0 {
            // Mark incomplete deps as candidates for steps.
            candidates.extend(incomplete_deps);
          } else {
            // All deps are already completed: mark this Node as a candidate for another step.
            candidates.insert(node);
          }
        },
        _ => {
          // Node has no deps yet: mark as a candidate for another step.
          candidates.insert(node);
        },
      };
    }

    // Create a set of steps for any ready candidates in the raw ready struct.
    self.ready.clear();
    self.ready.extend(
      candidates.iter()
        .map(|n| *n)
        .filter_map(|node| {
          if graph.is_ready(node) {
            let entry = graph.ensure_entry(node);
            Some(
              RawStep {
                node: node,
                awaiting_ptr: entry.awaiting.as_mut_ptr(),
                awaiting_len: entry.awaiting.len() as u64,
                awaiting_cyclic_ptr: entry.awaiting_cyclic.as_mut_ptr(),
                awaiting_cyclic_len: entry.awaiting_cyclic.len() as u64,
              }
            )
          } else {
            None
          }
        })
    );
    with_raw_steps(self.ready_raw, |rr| {
      rr.steps_ptr = self.ready.as_mut_ptr();
      rr.steps_len = self.ready.len() as u64;
    });
  }
}

fn with_raw_steps<F,T>(raw_steps_ptr: *mut RawSteps, mut f: F) -> T
    where F: FnMut(&mut RawSteps)->T {
  let mut raw_steps = unsafe { Box::from_raw(raw_steps_ptr) };
  let t = f(&mut raw_steps);
  std::mem::forget(raw_steps);
  t
}
