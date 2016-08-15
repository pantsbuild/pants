mod core;
mod graph;
mod nodes;
mod selectors;
mod tasks;

use std::collections::{HashMap, HashSet, VecDeque};

use core::{Key, TypeId};
use graph::{Entry, EntryId, Graph};
use nodes::{Complete, Node, Runnable, State};
use selectors::{Selector, Select, SelectDependencies, SelectVariant, SelectLiteral, SelectProjection};
use tasks::Tasks;

/**
 * Represents the state of an execution of (a subgraph of) a Graph.
 */
pub struct Execution<'g,'t> {
  // TODO: Graph and Tasks should both be references.
  graph: &'g Graph<'g>,
  tasks: &'t Tasks,
  // Initial set of roots for the execution.
  roots: Vec<&'g Node>,
  // Candidates for Execution, in the order they were declared.
  candidates: VecDeque<EntryId>,
  // Currently ready Runnables.
  ready: Vec<(EntryId, Runnable)>,
  // Ready ids. This will always contain at least as many entries as the `ready` Vec. If
  // it contains more ids than the `ready` Vec, it is because entries that were previously
  // declared to be ready are still outstanding.
  outstanding: HashSet<EntryId>,
}

impl<'g,'t> Execution<'g,'t> {
  /**
   * Begins an Execution with an initially empty set of roots and tasks.
   */
  pub fn new(graph: &'g Graph, tasks: &'t Tasks) -> Execution<'g,'t> {
    Execution {
      graph: graph,
      tasks: tasks,
      roots: Vec::new(),
      candidates: VecDeque::new(),
      ready: Vec::new(),
      outstanding: HashSet::new(),
    }
  }

  pub fn add_root_node_select(&mut self, subject: Key, product: TypeId) {
    self.add_root(
      Node::create(
        Selector::Select(Select { product: product, optional: false }),
        subject,
        Vec::new(),
      )
    );
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
    let entry = self.graph.ensure_entry(node);
    self.roots.push(entry.node());
    self.candidates.push_back(entry.id());
  }

  fn attempt_step(&self, entry: &Entry) -> Option<State> {
  }

  /**
   * Continues execution after the given runnables have completed execution.
   */
  pub fn next(&mut self, completed: Vec<(EntryId, Complete)>) {
    // Mark any completed entries as such, and clear the ready list.
    for (id, state) in completed {
      self.outstanding.remove(&id);
      self.candidates.push_back(id);
      self.graph.complete(id, state);
    }
    self.ready.clear();

    // For each changed node, determine whether its dependents or itself are a candidate.
    while let Some(candidate_id) = self.candidates.pop_front() {
      if self.outstanding.contains(&candidate_id) {
        // Already running.
        continue;
      }
      let entry = self.graph.entry_for_id(candidate_id);
      if entry.is_complete() {
        // Already complete.
        continue;
      }

      // Attempt to run a step for the Node.
      match self.attempt_step(entry) {
        Some(State::Complete(s)) =>
          // Mark any dependents of the Node as candidates.
          self.candidates.extend(entry.dependents()),
        Some(State::Waiting(w)) => {
          // Add the new dependencies.
          self.graph.add_dependencies(entry, w);
          // If all dependencies of the Node are completed, the Node is still a candidate.
          let dep_entries: Vec<&Entry> =
            entry.dependencies().iter()
              .map(|&d| &*self.graph.entry_for_id(d))
              .collect();
          let incomplete_deps =
            dep_entries.iter()
              .filter(|e| !e.is_complete())
              .map(|e| e.id());
          if let Some(first) = incomplete_deps.next() {
            // Mark incomplete deps as candidates for steps.
            self.candidates.push_back(first);
            self.candidates.extend(incomplete_deps);
          } else {
            // All newly declared deps are already completed: still a candidate.
            self.candidates.push_front(entry.id());
          }
        },
      }
    }
  }
}
