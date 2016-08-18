use std::collections::{HashMap, HashSet, VecDeque};

use core::{Key, TypeId};
use graph::{Entry, EntryId, Graph};
use nodes::{Complete, Node, Runnable, State};
use selectors::{Selector, SelectDependencies};
use tasks::Tasks;

/**
 * Represents the state of an execution of (a subgraph of) a Graph.
 */
pub struct Execution<'g,'t> {
  graph: &'g mut Graph,
  tasks: &'t Tasks,
  // Initial set of roots for the execution.
  roots: Vec<Node>,
  // Candidates for Execution, in the order they were declared.
  candidates: VecDeque<EntryId>,
  // Ready ids. This will always contain at least as many entries as the `ready` Vec. If
  // it contains more ids than the `ready` Vec, it is because entries that were previously
  // declared to be ready are still outstanding.
  outstanding: HashSet<EntryId>,
}

impl<'g,'t> Execution<'g,'t> {
  /**
   * Begins an Execution with an initially empty set of roots and tasks.
   */
  pub fn new(graph: &'g mut Graph, tasks: &'t Tasks) -> Execution<'g,'t> {
    Execution {
      graph: graph,
      tasks: tasks,
      roots: Vec::new(),
      candidates: VecDeque::new(),
      outstanding: HashSet::new(),
    }
  }

  pub fn add_root_node_select(&mut self, subject: Key, product: TypeId) {
    self.add_root(Node::create(Selector::select(product), subject, Vec::new()));
  }

  pub fn add_root_node_select_dependencies(
    &mut self,
    subject: Key,
    product: TypeId,
    dep_product: TypeId,
    field: String
  ) {
    self.add_root(
      Node::create(
        Selector::SelectDependencies(
          SelectDependencies { product: product, dep_product: dep_product, field: field }),
        subject,
        Vec::new(),
      )
    );
  }

  fn add_root(&mut self, node: Node) {
    self.roots.push(node.clone());
    self.candidates.push_back(self.graph.ensure_entry(node));
  }

  /**
   * Attempt to run a Step with the currently available dependencies of the given Node.
   *
   * If the currently declared dependencies of the Entry are not yet available, returns None. If
   * they are available, runs a Step and returns the resulting State.
   */
  fn attempt_step(&self, id: EntryId) -> Option<State> {
    let entry = self.graph.entry_for_id(id);
    if entry.is_complete() {
      // Already complete.
      return None;
    }

    let dep_entries: Vec<&Entry> =
      entry.dependencies().iter()
        .map(|&d| self.graph.entry_for_id(d))
        .collect();
    if dep_entries.iter().any(|d| !d.is_complete()) {
      // Dep is not complete.
      return None;
    }

    // All deps are complete: gather them.
    let cyclic = Complete::Noop("Dep would be cyclic.".to_string());
    let mut dep_map: HashMap<&Node, &Complete> =
      dep_entries.iter()
        .filter_map(|e| {
          e.state().map(|s| (e.node(), s))
        })
        .collect();
    for &id in entry.cyclic_dependencies() {
      dep_map.insert(self.graph.entry_for_id(id).node(), &cyclic);
    }

    // And finally, run!
    Some(entry.node().step(dep_map, self.tasks))
  }

  /**
   * Continues execution after the given runnables have completed execution.
   */
  pub fn next(&mut self, completed: Vec<(&EntryId, &Complete)>) -> Vec<(EntryId, Runnable)> {
    let mut ready = Vec::new();

    // Mark any completed entries as such.
    for (&id, &state) in completed {
      self.outstanding.remove(&id);
      self.candidates.extend(self.graph.entry_for_id(id).dependents());
      self.graph.complete(id, state);
    }

    // For each changed node, determine whether its dependents or itself are a candidate.
    while let Some(entry_id) = self.candidates.pop_front() {
      if self.outstanding.contains(&entry_id) {
        // Already running.
        continue;
      }

      // Attempt to run a step for the Node.
      match self.attempt_step(entry_id) {
        Some(State::Runnable(s)) => {
          // The node is ready to run!
          ready.push((entry_id, s));
          self.outstanding.insert(entry_id);
        },
        Some(State::Complete(_)) =>
          // Node completed statically; mark any dependents of the Node as candidates.
          self.candidates.extend(self.graph.entry_for_id(entry_id).dependents()),
        Some(State::Waiting(w)) => {
          // Add the new dependencies.
          self.graph.add_dependencies(entry_id, w);
          let ref graph = self.graph;
          // If all dependencies of the Node are completed, the Node is still a candidate.
          let mut incomplete_deps =
            self.graph.entry_for_id(entry_id).dependencies().iter()
              .map(|&d| graph.entry_for_id(d))
              .filter(|e| !e.is_complete())
              .map(|e| e.id());
          if let Some(first) = incomplete_deps.next() {
            // Mark incomplete deps as candidates for steps.
            self.candidates.push_back(first);
            self.candidates.extend(incomplete_deps);
          } else {
            // All newly declared deps are already completed: still a candidate.
            self.candidates.push_front(entry_id);
          }
        },
        None => continue,
      }
    }

    ready
  }
}
