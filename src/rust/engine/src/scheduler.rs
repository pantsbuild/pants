use std::collections::{HashSet, VecDeque};

use std::io;
use std::path::Path;

use core::{FNV, Field, Key, TypeConstraint};
use graph::{EntryId, Graph};
use handles::drain_handles;
use nodes::{Complete, Node, Runnable, State};
use selectors::{Selector, SelectDependencies};
use tasks::Tasks;

/**
 * Represents the state of an execution of (a subgraph of) a Graph.
 */
pub struct Scheduler {
  pub graph: Graph,
  pub tasks: Tasks,
  // Initial set of roots for the execution, in the order they were declared.
  roots: Vec<Node>,
  // Candidates for execution.
  candidates: VecDeque<EntryId>,
  // Outstanding ids. This will always contain at least as many entries as the `ready` set. If
  // it contains more ids than the `ready` set, it is because entries that were previously
  // declared to be ready are still outstanding.
  outstanding: HashSet<EntryId, FNV>,
  runnable: HashSet<EntryId, FNV>,
}

impl Scheduler {
  /**
   * Creates a Scheduler with an initially empty set of roots.
   */
  pub fn new(graph: Graph, tasks: Tasks) -> Scheduler {
    Scheduler {
      graph: graph,
      tasks: tasks,
      roots: Vec::new(),
      candidates: VecDeque::new(),
      outstanding: HashSet::default(),
      runnable: HashSet::default(),
    }
  }

  pub fn visualize(&self, path: &Path) -> io::Result<()> {
    self.graph.visualize(&self.roots, path, &self.tasks.externs)
  }

  pub fn trace(&self, path: &Path) -> io::Result<()> {
    for root in &self.roots {
      let result = self.graph.trace(&root, path, &self.tasks.externs);
      if result.is_err() {
        return result;
      }
    }
    Ok(())
  }

  pub fn reset(&mut self) {
    self.roots.clear();
    self.candidates.clear();
    self.outstanding.clear();
  }

  pub fn root_states(&self) -> Vec<(&Key, &TypeConstraint, Option<&Complete>)> {
    self.roots.iter()
      .map(|root| {
        let state = self.graph.entry(root).and_then(|e| e.state());
        (root.subject(), root.product(), state)
      })
      .collect()
  }

  pub fn add_root_select(&mut self, subject: Key, product: TypeConstraint) {
    self.add_root(Node::create(Selector::select(product), subject, Default::default()));
  }

  pub fn add_root_select_dependencies(
    &mut self,
    subject: Key,
    product: TypeConstraint,
    dep_product: TypeConstraint,
    field: Field,
    transitive: bool,
  ) {
    self.add_root(
      Node::create(
        Selector::SelectDependencies(
          SelectDependencies { product: product, dep_product: dep_product, field: field, transitive: transitive }),
        subject,
        Default::default(),
      )
    );
  }

  fn add_root(&mut self, node: Node) {
    self.roots.push(node.clone());
    self.candidates.push_back(self.graph.ensure_entry(node));
  }

  /**
   * Attempt to run a step with the currently available dependencies of the given Node. If
   * a step runs, the new State of the Node will be returned.
   */
  fn attempt_step(&mut self, id: EntryId) -> Option<State> {
    if !self.graph.is_ready_entry(id) {
      return None;
    }

    // Run a step.
    // NB: Needing to clone the Node here is unfortunate, but allows the Node to be borrowed
    // immutably while the graph is borrowed mutably for the declaration of new dependencies.
    let node = self.graph.entry_for_id(id).node().clone();
    Some(node.step(&mut self.graph.context(id), &self.tasks))
  }

  /**
   * Collects incomplete deps into the candidates list, asserting that there is at least one.
   */
  fn collect_candidates(graph: &Graph, candidates: &mut VecDeque<EntryId>, entry_id: EntryId) {
    let mut incomplete_deps =
      graph.entry_for_id(entry_id).dependencies().iter()
        .map(|&d| graph.entry_for_id(d))
        .filter(|e| !e.is_complete())
        .map(|e| e.id())
        .peekable();
    assert!(
      incomplete_deps.peek().is_some(),
      "Node {:?} returned `Waiting` without declaring dependencies.",
      graph.entry_for_id(entry_id),
    );
    candidates.extend(incomplete_deps);
  }

  /**
   * Continues execution after the given runnables have completed execution.
   *
   * Returns an ordered batch of `Staged<EntryId>` for which every `StagedArg::Promise` is
   * satisfiable by an entry earlier in the list. This "mini graph" can be executed linearly, or in
   * parallel as long as those promise dependencies are observed.
   */
  pub fn next(&mut self, completed: Vec<(EntryId, Complete)>) -> Vec<(EntryId, Runnable)> {
    let mut ready = Vec::new();

    // Mark any completed entries as such.
    for (id, state) in completed {
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
        Some(State::Complete(s)) => {
          if self.graph.is_ready_entry(entry_id) {
            // Node completed statically; mark any dependents of the Node as candidates.
            self.graph.complete(entry_id, s);
            self.candidates.extend(self.graph.entry_for_id(entry_id).dependents());
          } else {
            // Node cannot complete until its dependencies do.
            Scheduler::collect_candidates(&self.graph, &mut self.candidates, entry_id);
          }
        },
        Some(State::Waiting) => {
          // Node cannot complete until its dependencies do.
          Scheduler::collect_candidates(&self.graph, &mut self.candidates, entry_id);
        },
        None =>
          // Not ready to step.
          continue,
      }
    }

    self.runnable.clear();
    self.tasks.externs.drop_handles(drain_handles());
    ready
  }
}
