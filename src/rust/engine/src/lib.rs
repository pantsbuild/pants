mod core;
mod graph;
mod nodes;
mod selectors;
mod tasks;

use std::collections::{HashMap, HashSet};

use core::{Key, TypeId};
use graph::{Entry, EntryId, Graph};
use nodes::{Node, Runnable};
use selectors::{Selector, Select, SelectDependencies, SelectVariant, SelectLiteral, SelectProjection};
use tasks::Tasks;

/**
 * Represents the state of an execution of (a subgraph of) a Graph.
 */
pub struct Execution {
  tasks: Tasks,
  // Roots of the Execution, in the order they were declared.
  roots: Vec<Node>,
  // Currently ready Runnables.
  ready: Vec<Runnable>,
}

impl Execution {
  /**
   * Begins an Execution with an initially empty set of roots and tasks.
   */
  fn new(tasks: Tasks) -> Execution {
    Execution {
      tasks: tasks,
      roots: Vec::new(),
      ready: Vec::new(),
    }
  }

  fn add_root_node_select(&mut self, subject: Key, product: TypeId) {
    self.roots.push(
      Node::create(
        Selector::Select(Select { product: product, optional: false }),
        subject,
        Vec::new(),
      )
    );
  }

  fn add_root_node_select_dependencies(
    &mut self,
    subject: Key,
    product: TypeId,
    dep_product: TypeId,
    field: String
  ) {
    self.roots.push(
      Node::create(
        Selector::SelectDependencies(
          SelectDependencies { product: product, dep_product: dep_product, field: field }),
        subject,
        Vec::new(),
      )
    );
  }

  /**
   * Continues execution after the given Nodes have changed.
   */
  fn next(&mut self, graph: &mut Graph, changed: &Vec<Node>) {
    let mut candidates: HashSet<EntryId> = HashSet::new();

    // For each changed node, determine whether its dependents or itself are a candidate.
    for &node in changed {
      match graph.entry(&node) {
        Some(entry) if entry.is_complete() => {
          // Mark any dependents of the Node as candidates.
          candidates.extend(entry.dependents());
        },
        Some(entry) => {
          // If all dependencies of the Node are completed, the Node itself is a candidate.
          let incomplete_deps: Vec<EntryId> =
            entry.dependencies().iter()
              .filter_map(|&d| graph.entry_for_id(d))
              .filter(|e| !e.is_complete())
              .map(|e| e.id())
              .collect();
          if incomplete_deps.len() > 0 {
            // Mark incomplete deps as candidates for steps.
            candidates.extend(incomplete_deps);
          } else {
            // All deps are already completed: mark this Node as a candidate for another step.
            candidates.insert(entry.id());
          }
        },
        _ => {
          // Node has no deps yet: initialize it and mark it as a candidate.
          candidates.insert(graph.ensure_entry(node).id());
        },
      };
    }

    // Record the ready candidate entries.
    self.ready =
      candidates.iter()
        .filter_map(|&id| graph.entry_for_id(id))
        .filter_map(|entry| {
          if graph.is_ready_entry(entry) {
            Some(entry)
          } else {
            None
          }
        })
        .collect();
  }
}
