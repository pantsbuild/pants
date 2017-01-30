
use std::io;
use std::path::Path;
use std::sync::Arc;

use futures::future::Future;
use futures::future;
use futures_cpupool::{CpuPool, CpuFuture};

use context::Core;
use core::{Field, Key, TypeConstraint};
use externs::Externs;
use graph::{EntryId, Graph};
use nodes::{Node, NodeResult, Context, ContextFactory};
use selectors::{Selector, SelectDependencies};
use tasks::Tasks;
use types::Types;

/**
 * Represents the state of an execution of (a subgraph of) a Graph.
 */
pub struct Scheduler {
  pub core: Arc<Core>,
  // Initial set of roots for the execution, in the order they were declared.
  roots: Vec<Node>,
}

impl Scheduler {
  /**
   * Creates a Scheduler with an initially empty set of roots.
   */
  pub fn new(
    tasks: Tasks,
    types: Types,
    externs: Externs,
  ) -> Scheduler {
    Scheduler {
      core: Arc::new(
        Core {
          graph: Graph::new(),
          tasks: tasks,
          types: types,
          externs: externs,
          pool: CpuPool::new_num_cpus(),
        }
      ),
      roots: Vec::new(),
    }
  }

  pub fn visualize(&self, path: &Path) -> io::Result<()> {
    self.core.graph.visualize(&self.roots, path, &self.core.externs)
  }

  pub fn trace(&self, path: &Path) -> io::Result<()> {
    for root in &self.roots {
      let result = self.core.graph.trace(&root, path, &self.core.externs);
      if result.is_err() {
        return result;
      }
    }
    Ok(())
  }

  pub fn reset(&mut self) {
    self.roots.clear();
  }

  pub fn root_states(&self) -> Vec<(&Key, &TypeConstraint, Option<NodeResult>)> {
    self.roots.iter()
      .map(|root| {
        (root.subject(), root.product(), self.core.graph.wait(root, &self.core.externs))
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
   * Starts running a Node, and returns a Future that will succeed regardless of the
   * success of the node.
   */
  fn launch(&self, node: Node) -> CpuFuture<(), ()> {
    let core = self.core.clone();
    self.core.pool.spawn_fn(move || core.graph.create(node, &core)
      .then::<_, Result<(), ()>>(|_| Ok(()))
    )
  }

  /**
   * Starting from existing roots, execute a graph to completion.
   */
  pub fn execute(&mut self) -> ExecutionStat {
    // TODO: Restore counts.
    let runnable_count = 0;
    let scheduling_iterations = 0;

    // Bootstrap tasks for the roots, and then wait for all of them.
    let roots_res =
      future::join_all(
        self.roots.iter()
          .map(|root| self.launch(root.clone()))
          .collect::<Vec<_>>()
      );

    // Wait for all roots to complete. Failure here should be impossible, because each
    // individual Future in the join was mapped into success regardless of its result.
    roots_res.wait().expect("Execution failed.");

    ExecutionStat {
      runnable_count: runnable_count,
      scheduling_iterations: scheduling_iterations,
    }
  }
}

impl ContextFactory for Arc<Core> {
  fn create(&self, entry_id: EntryId) -> Context {
    Context::new(entry_id, self.clone())
  }
}

#[repr(C)]
pub struct ExecutionStat {
  runnable_count: u64,
  scheduling_iterations: u64,
}
