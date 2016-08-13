use std::collections::{HashMap, HashSet, VecDeque};

pub type Node = u64;
pub type StateType = u8;

/**
 * An Entry and its adjacencies.
 *
 * The dependencies and cyclic_dependencies sets are stored as vectors in order to expose
 * them more easily via the C API, but they should never contain dupes.
 */
pub struct Entry {
  node: Node,
  state: StateType,
  dependencies: Vec<Node>,
  dependents: HashSet<Node>,
  cyclic_dependencies: Vec<Node>,
}

/**
 * A DAG (enforced on mutation) of Entries.
 */
pub struct Graph {
  empty_state: StateType,
  nodes: HashMap<Node,Entry>,
}

impl Graph {
  fn new(empty_state: StateType) -> Graph {
    Graph {
      empty_state: empty_state,
      nodes: HashMap::new()
    }
  }

  fn len(&self) -> u64 {
    self.nodes.len() as u64
  }

  fn is_complete(&self, node: Node) -> bool {
    self.nodes.get(&node).map(|e| e.state != self.empty_state).unwrap_or(false)
  }

  fn is_complete_entry(&self, entry: &Entry) -> bool {
    entry.state == self.empty_state
  }

  /**
   * A Node is 'ready' (to run) when it is not complete, but all of its dependencies
   * are complete.
   */
  fn is_ready(&self, node: Node) -> bool {
    (!self.is_complete(node)) && (
      self.nodes.get(&node).map(|e| {
          e.dependencies
            .iter()
            .all(|d| { self.is_complete(*d) })
        }).unwrap_or(true)
    )
  }

  fn ensure_entry(&mut self, node: Node) -> &mut Entry {
    let empty_state = self.empty_state;
    self.nodes.entry(node).or_insert_with(||
      Entry {
        node: node,
        state: empty_state,
        dependencies: Vec::new(),
        dependents: HashSet::new(),
        cyclic_dependencies: Vec::new(),
      }
    )
  }

  /**
   * Adds the given dst Nodes as dependencies of the src Node.
   *
   * Preserves the invariant that completed Nodes may only depend on other completed Nodes.
   */
  fn add_dependencies(&mut self, src: Node, dsts: &Vec<Node>) {
    let empty_state = self.empty_state;
    let (state, dependencies) = {
      let entry = self.ensure_entry(src);
      (entry.state, entry.dependencies.iter().map(|&n| n).collect::<HashSet<Node>>())
    };
    assert!(
      state == empty_state,
      "Node {} is already completed, and may not have new dependencies added: {:?}",
      src,
      dsts,
    );

    for &dst in dsts {
      if dependencies.contains(&dst) {
        continue;
      }

      if self.detect_cycle(src, dst) {
        self.ensure_entry(src).cyclic_dependencies.push(dst);
      } else {
        self.ensure_entry(src).dependencies.push(dst);
        self.ensure_entry(dst).dependents.insert(src);
      }
    }
  }

  /**
   * Detect whether adding an edge from src to dst would create a cycle.
   *
   * Returns true if a cycle would be created by adding an edge from src->dst.
   */
  fn detect_cycle(&self, src: Node, dst: Node) -> bool {
    for node in self.walk(&vec![dst], { |entry| !self.is_complete_entry(entry) }, false) {
      if node == src {
        return true;
      }
    }
    return false;
  }

  /**
   * Begins a topological Walk from the given roots.
   */
  fn walk<P>(&self, roots: &Vec<Node>, predicate: P, dependents: bool) -> Walk<P>
      where P: Fn(&Entry)->bool {
    Walk {
      graph: self,
      dependents: dependents,
      deque: roots.iter().map(|&x| x).collect(),
      walked: HashSet::new(),
      predicate: predicate,
    }
  }

  /**
   * Removes the given invalidation roots and their transitive dependents from the Graph.
   */
  fn invalidate(&mut self, roots: &Vec<Node>) -> usize {
    // eagerly collect all Nodes before we begin mutating anything.
    let nodes: Vec<Node> = self.walk(roots, { |_| true }, true).collect();

    for node in &nodes {
      // remove the roots from their dependencies' dependents lists.
      // FIXME: Because the lifetime of each Entry is the same as the lifetime of the entire Graph,
      // I can't figure out how to iterate over one immutable Entry while mutating a different
      // mutable Entry... so I clone() here. Perhaps this is completely sane, because what's to say
      // they're not the same Entry after all? But regardless, less efficient than it could be.
      for dependency in self.ensure_entry(*node).dependencies.clone() {
        match self.nodes.get_mut(&dependency) {
          Some(entry) => { entry.dependents.remove(node); () },
          _ => {},
        }
      }

      // delete each Node
      self.nodes.remove(node);
    }

    nodes.len()
  }
}

/**
 * Represents the state of a particular topological walk through a Graph. Implements Iterator and
 * has the same lifetime as the Graph itself.
 */
struct Walk<'a, P: Fn(&Entry)->bool> {
  graph: &'a Graph,
  dependents: bool,
  deque: VecDeque<Node>,
  walked: HashSet<Node>,
  predicate: P,
}

impl<'a, P: Fn(&Entry)->bool> Iterator for Walk<'a, P> {
  type Item = Node;

  fn next(&mut self) -> Option<Node> {
    while let Some(node) = self.deque.pop_front() {
      if self.walked.contains(&node) {
        continue;
      }
      self.walked.insert(node);

      match self.graph.nodes.get(&node) {
        Some(entry) if (self.predicate)(entry) => {
          if self.dependents {
            self.deque.extend(&entry.dependents);
          } else {
            self.deque.extend(&entry.dependencies);
          }
          return Some(entry.node);
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
  dependencies_ptr: *mut Node,
  dependencies_len: u64,
  cyclic_dependencies_ptr: *mut Node,
  cyclic_dependencies_len: u64,
}

pub struct RawSteps {
  steps_ptr: *mut RawStep,
  steps_len: u64,
}

/**
 * Represents the state of an execution of (a subgraph of) a Graph.
 */
pub struct Execution {
  candidates: HashSet<Node>,
  ready: Vec<RawStep>,
  ready_raw: *mut RawSteps,
}

impl Execution {
  /**
   * Begins an Execution from the given root Nodes.
   */
  fn new(roots: &Vec<Node>) -> Execution {
    let mut execution =
      Execution {
        candidates: roots.iter().map(|n| *n).collect(),
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
  fn next(
    &mut self,
    graph: &mut Graph,
    waiting: &Vec<Node>,
    completed: &Vec<Node>,
    completed_states: &Vec<StateType>
  ) {
    assert!(
      completed.len() == completed_states.len(),
      "The completed Node and State vectors did not have the same length: {} vs {}",
      completed.len(),
      completed_states.len()
    );

    // Complete any completed Nodes and mark their dependents as candidates.
    for (&node, &state) in completed.iter().zip(completed_states.iter()) {
      assert!(
        graph.is_ready(node),
        "Node {} is already completed, or has incomplete deps.",
        node,
      );
      let entry = graph.ensure_entry(node);
      self.candidates.extend(&entry.dependents);
      entry.state = state;
    }

    // Mark the dependencies of any waiting Nodes as candidates.
    for &node in waiting {
      match graph.nodes.get(&node) {
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
            self.candidates.extend(incomplete_deps);
          } else {
            // All deps are already completed: mark this Node as a candidate for another step.
            self.candidates.insert(node);
          }
        },
        _ => {
          // Node has no deps yet: mark as a candidate for another step.
          self.candidates.insert(node);
        },
      };
    }

    // Move all ready candidates to the ready set.
    let (ready_candidates, next_candidates) =
      self.candidates.iter().map(|c| *c).partition(|&c| graph.is_ready(c));
    self.candidates = next_candidates;

    // Create a new set of steps in the raw ready struct.
    self.ready.clear();
    self.ready.extend(
      ready_candidates.iter().map(|&node| {
        let entry = graph.ensure_entry(node);
        RawStep {
          node: node,
          dependencies_ptr: entry.dependencies.as_mut_ptr(),
          dependencies_len: entry.dependencies.len() as u64,
          cyclic_dependencies_ptr: entry.cyclic_dependencies.as_mut_ptr(),
          cyclic_dependencies_len: entry.cyclic_dependencies.len() as u64,
        }
      })
    );
    with_raw_steps(self.ready_raw, |rr| {
      rr.steps_ptr = self.ready.as_mut_ptr();
      rr.steps_len = self.ready.len() as u64;
    });
  }
}

/** TODO: Make the next four functions generic in the type being operated on? */

fn with_execution<F,T>(execution_ptr: *mut Execution, mut f: F) -> T
    where F: FnMut(&mut Execution)->T {
  let mut execution = unsafe { Box::from_raw(execution_ptr) };
  let t = f(&mut execution);
  std::mem::forget(execution);
  t
}

fn with_raw_steps<F,T>(raw_steps_ptr: *mut RawSteps, mut f: F) -> T
    where F: FnMut(&mut RawSteps)->T {
  let mut raw_steps = unsafe { Box::from_raw(raw_steps_ptr) };
  let t = f(&mut raw_steps);
  std::mem::forget(raw_steps);
  t
}

fn with_graph<F,T>(graph_ptr: *mut Graph, f: F) -> T
    where F: Fn(&mut Graph)->T {
  let mut graph = unsafe { Box::from_raw(graph_ptr) };
  let t = f(&mut graph);
  std::mem::forget(graph);
  t
}

fn with_nodes<F,T>(nodes_ptr: *mut Node, nodes_len: usize, mut f: F) -> T
    where F: FnMut(&Vec<Node>)->T {
  let nodes = unsafe { Vec::from_raw_parts(nodes_ptr, nodes_len, nodes_len) };
  let t = f(&nodes);
  std::mem::forget(nodes);
  t
}

fn with_states<F,T>(states_ptr: *mut StateType, states_len: usize, mut f: F) -> T
    where F: FnMut(&Vec<StateType>)->T {
  let states = unsafe { Vec::from_raw_parts(states_ptr, states_len, states_len) };
  let t = f(&states);
  std::mem::forget(states);
  t
}

#[no_mangle]
pub extern fn graph_create(empty_state: StateType) -> *const Graph {
  // allocate on the heap via `Box` and return a raw pointer to the boxed value.
  let raw = Box::into_raw(Box::new(Graph::new(empty_state)));
  raw
}

#[no_mangle]
pub extern fn graph_destroy(graph_ptr: *mut Graph) {
  // convert the raw pointer back to a Box (without `forget`ing it) in order to cause it
  // to be destroyed at the end of this function.
  let _ = unsafe { Box::from_raw(graph_ptr) };
}

#[no_mangle]
pub extern fn len(graph_ptr: *mut Graph) -> u64 {
  with_graph(graph_ptr, |graph| {
    graph.len()
  })
}

#[no_mangle]
pub extern fn add_dependencies(graph_ptr: *mut Graph, src: Node, dsts_ptr: *mut Node, dsts_len: u64) {
  with_graph(graph_ptr, |graph| {
    with_nodes(dsts_ptr, dsts_len as usize, |dsts| {
      graph.add_dependencies(src, dsts);
    })
  })
}

#[no_mangle]
pub extern fn invalidate(graph_ptr: *mut Graph, roots_ptr: *mut Node, roots_len: u64) -> u64 {
  with_graph(graph_ptr, |graph| {
    with_nodes(roots_ptr, roots_len as usize, |roots| {
      graph.invalidate(roots) as u64
    })
  })
}

#[no_mangle]
pub extern fn execution_create(roots_ptr: *mut Node, roots_len: u64) -> *const Execution {
  with_nodes(roots_ptr, roots_len as usize, |roots| {
    // create on the heap, and return a raw pointer to the boxed value.
    Box::into_raw(Box::new(Execution::new(roots)))
  })
}

#[no_mangle]
pub extern fn execution_next(
  graph_ptr: *mut Graph,
  execution_ptr: *mut Execution,
  waiting_ptr: *mut Node,
  waiting_len: u64,
  completed_ptr: *mut Node,
  completed_len: u64,
  states_ptr: *mut StateType,
  states_len: u64,
) -> *const RawSteps {
  with_graph(graph_ptr, |graph| {
    with_execution(execution_ptr, |execution| {
      with_nodes(waiting_ptr, waiting_len as usize, |waiting| {
        with_nodes(completed_ptr, completed_len as usize, |completed| {
          with_states(states_ptr, states_len as usize, |states| {
            execution.next(graph, waiting, completed, states);
            execution.ready_raw
          })
        })
      })
    })
  })
}

#[no_mangle]
pub extern fn execution_destroy(execution_ptr: *mut Execution) {
  // convert the raw pointers back to Boxes (without `forget`ing them) in order to cause them
  // to be destroyed at the end of this function.
  unsafe {
    let execution = Box::from_raw(execution_ptr);
    let _ = Box::from_raw(execution.ready_raw);
  };
}
