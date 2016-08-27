use std::collections::{HashMap, HashSet, VecDeque};

use std::io;
use std::path::Path;

use externs::ToStrFunction;
use core::{Field, Function, Key, TypeId};
use graph::{Entry, EntryId, Graph};
use nodes::{Complete, Node, Staged, State};
use selectors::{Selector, SelectDependencies};
use tasks::Tasks;

/**
 * Represents the state of an execution of (a subgraph of) a Graph.
 */
pub struct Scheduler {
  pub to_str: ToStrFunction,
  pub graph: Graph,
  pub tasks: Tasks,
  // Initial set of roots for the execution.
  roots: Vec<Node>,
  // Candidates for Scheduler, in the order they were declared.
  candidates: VecDeque<EntryId>,
  // Ready ids. This will always contain at least as many entries as the `ready` Vec. If
  // it contains more ids than the `ready` Vec, it is because entries that were previously
  // declared to be ready are still outstanding.
  outstanding: HashSet<EntryId>,
}

impl Scheduler {
  /**
   * Creates a Scheduler with an initially empty set of roots.
   */
  pub fn new(to_str: ToStrFunction, graph: Graph, tasks: Tasks) -> Scheduler {
    Scheduler {
      to_str: to_str,
      graph: graph,
      tasks: tasks,
      roots: Vec::new(),
      candidates: VecDeque::new(),
      outstanding: HashSet::new(),
    }
  }

  pub fn visualize(&self, path: &Path) -> io::Result<()> {
    self.graph.visualize(&self.roots, path, &self.to_str)
  }

  pub fn reset(&mut self) {
    self.roots.clear();
    self.candidates.clear();
    self.outstanding.clear();
  }

  pub fn root_states(&self) -> Vec<(&Key,&TypeId,Option<&Complete>)> {
    self.roots.iter()
      .map(|root| {
        let subject = root.subject();
        let product = root.product();
        // TODO: Expose all States?
        let state =
          self.graph.entry(root).and_then(|e| {
            match e.state() {
              &State::Complete(ref c) => Some(c),
              _ => None,
            }
          });
        (subject, product, state)
      })
      .collect()
  }

  pub fn add_root_select(&mut self, subject: Key, product: TypeId) {
    self.add_root(Node::create(Selector::select(product), subject, Vec::new()));
  }

  pub fn add_root_select_dependencies(
    &mut self,
    subject: Key,
    product: TypeId,
    dep_product: TypeId,
    field: Field,
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
   * Attempt to run a step with the currently available dependencies of the given Node. If
   * a step runs, the new State of the Node will be returned.
   */
  fn attempt_step(&self, id: EntryId) -> Option<State<Node>> {
    let entry = self.graph.entry_for_id(id);

    // Collect complete deps.
    let mut dep_map = HashMap::new();
    for &dep_id in entry.dependencies() {
      let dep_entry = self.graph.entry_for_id(dep_id);
      match dep_entry.state() {
        &State::Complete(ref c) =>
          dep_map.insert(dep_entry.node(), c),
        _ =>
          // A dep is not complete.
          return None,
      };
    }

    // Additionally, gather cyclic deps.
    let cyclic_deps: Vec<(&Entry, Complete)> =
      entry.cyclic_dependencies().iter()
        .map(|&id| {
          let entry = self.graph.entry_for_id(id);
          (entry, Complete::Noop("Dep would be cyclic: {}.", Some(entry.node().clone())))
        })
        .collect();
    for &(e, ref s) in cyclic_deps.iter() {
      dep_map.insert(e.node(), &s);
    }

    // And finally, run!
    Some(entry.node().step(dep_map, &self.tasks, &self.to_str))
  }

  /**
   * Continues execution after the given runnables have completed execution.
   *
   * Returns a batch of `Staged<EntryId>` for which every `StagedArg::Promise` is satisfiable
   * by an entry which is already outstanding. This "mini graph" can be executed in parallel as
   * long as those promise dependencies are observed.
   */
  pub fn next(&mut self, completed: Vec<(EntryId, Complete)>) -> Vec<(EntryId, Staged<EntryId>)> {
    let mut ready = Vec::new();

    // Mark any completed entries as such.
    for (id, state) in completed {
      self.outstanding.remove(&id);
      self.candidates.extend(self.graph.entry_for_id(id).dependents());
      self.graph.set_state(id, State::Complete(state));
    }

    // For each changed node, determine whether its dependents or itself are a candidate.
    while let Some(entry_id) = self.candidates.pop_front() {
      if self.outstanding.contains(&entry_id) {
        // Already running.
        continue;
      }

      // Determine whether the node needs additional steps, or whether it is runnable.
      let new_state =
        match self.graph.entry_for_id(entry_id).state() {
          &State::Waiting(_) => {
            // See whether we can run a step for this node.
            match self.attempt_step(entry_id) {
              // Ran a step!
              Some(s) => self.graph.set_state(entry_id, s),
              // Not ready.
              None => continue,
            }
          },
          &State::Staged(ref s) if self.graph.dependencies_all(entry_id, Entry::is_staged) => {
            // All of the deps of a staged Node are staged, so it is runnable!
            ready.push((entry_id, s.clone()));
            self.outstanding.insert(entry_id);
            continue;
          },
          &State::Complete(_) =>
            // Already complete!
            continue,
          &State::Staged(_) =>
            // Deps aren't ready: continue waiting.
            continue,
        };

      // The node ran a step! Determine which nodes are affected.
      match new_state {
        &State::Staged(s) => {
          // If all dependencies of the Node are staged, the node is still a candidate.
          let ref graph = self.graph;
          let mut incomplete_deps =
            self.graph.entry_for_id(entry_id).dependencies().iter()
              .map(|&d| graph.entry_for_id(d))
              .filter(|e| !e.is_staged())
              .map(|e| e.id())
              .peekable();
          if incomplete_deps.peek().is_some() {
            // Mark incomplete deps as candidates for steps.
            self.candidates.extend(incomplete_deps);
          } else {
            // All newly declared deps are already completed: still a candidate.
            self.candidates.push_front(entry_id);
          }
        },
        &State::Complete(_) =>
          // Statically completed: mark any dependents of the Node as candidates.
          self.candidates.extend(self.graph.entry_for_id(entry_id).dependents()),
        &State::Waiting(_) => {
          // If all dependencies of the Node are completed, the Node is still a candidate.
          let ref graph = self.graph;
          let mut incomplete_deps =
            self.graph.entry_for_id(entry_id).dependencies().iter()
              .map(|&d| graph.entry_for_id(d))
              .filter(|e| !e.is_complete())
              .map(|e| e.id())
              .peekable();
          if incomplete_deps.peek().is_some() {
            // Mark incomplete deps as candidates for steps.
            self.candidates.extend(incomplete_deps);
          } else {
            // All newly declared deps are already completed: still a candidate.
            self.candidates.push_front(entry_id);
          }
        },
      }
    }

    ready
  }
}
