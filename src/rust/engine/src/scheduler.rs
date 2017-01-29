
use std::collections::{HashSet, VecDeque};
use std::io;
use std::path::Path;
use std::sync::Arc;

use futures::future::Future;
use futures::future;
use futures_cpupool::CpuPool;

use core::{FNV, Field, Key, TypeConstraint};
use graph::{EntryId, Graph};
use handles::drain_handles;
use nodes::{Complete, Node, Runnable, State, StepContext};
use selectors::{Selector, SelectDependencies};
use tasks::Tasks;

/**
 * Represents the state of an execution of (a subgraph of) a Graph.
 */
pub struct Scheduler {
  pub graph: Arc<Graph>,
  pub tasks: Arc<Tasks>,
  pool: CpuPool,
  // Initial set of roots for the execution, in the order they were declared.
  roots: Vec<Node>,
  // Candidates for execution.
}

#[repr(C)]
pub struct ExecutionStat {
  runnable_count: u64,
  scheduling_iterations: u64,
}

impl Scheduler {
  /**
   * Creates a Scheduler with an initially empty set of roots.
   */
  pub fn new(graph: Graph, tasks: Tasks) -> Scheduler {
    Scheduler {
      graph: Arc::new(graph),
      tasks: Arc::new(tasks),
      pool: CpuPool::new_num_cpus(),
      roots: Vec::new(),
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
  }

  /**
   * Starting from existing roots, execute a graph to completion.
   */
  pub fn execute(&mut self) -> ExecutionStat {
    let mut runnable_count = 0;
    let mut scheduling_iterations = 0;

    // Bootstrap tasks for the roots, and then wait for all of them.
    let roots_res =
      future::join_all(
        self.roots.iter()
          .map(|root| {
            let entry_id = self.graph.ensure_entry(root.clone());
            self.graph.entry_for_id(entry_id)
              .started(&StepContext::new(entry_id, self.graph, self.tasks))
              .then(|_| {
                // Ignore the result of each Node to ensure the entire run succeeds.
                Ok(())
              })
          })
      );

    // Wait for all roots to complete.
    roots_res.wait();

    // TODO: restore.
    ExecutionStat {
      runnable_count: runnable_count,
      scheduling_iterations: scheduling_iterations,
    }
  }
}
