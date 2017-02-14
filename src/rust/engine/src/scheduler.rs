
use std::io;
use std::path::Path;
use std::sync::Arc;

use futures::future::Future;
use futures::future;
use futures_cpupool::{CpuPool, CpuFuture};

use core::{Field, Key, TypeConstraint, TypeId, Value};
use externs::LogLevel;
use graph::{EntryId, Graph};
use nodes::{Context, ContextFactory, Failure, Node, NodeResult, Select, SelectDependencies};
use selectors;
use tasks::Tasks;

/**
 * Represents the state of an execution of (a subgraph of) a Graph.
 */
pub struct Scheduler {
  pub graph: Arc<Graph>,
  pub tasks: Arc<Tasks>,
  // Initial set of roots for the execution, in the order they were declared.
  roots: Vec<Root>,
}

impl Scheduler {
  /**
   * Roots are limited to either `SelectDependencies` and `Select`, which are known to
   * produce Values. But this method exists to satisfy Graph APIs which only need instances
   * of the Node enum.
   */
  fn root_nodes(&self) -> Vec<Node> {
    self.roots.iter()
      .map(|r| match r {
        &Root::Select(ref s) => Node::Select(s.clone()),
        &Root::SelectDependencies(ref s) => Node::SelectDependencies(s.clone()),
      })
      .collect()
  }

  /**
   * Creates a Scheduler with an initially empty set of roots.
   */
  pub fn new(graph: Graph, tasks: Tasks) -> Scheduler {
    Scheduler {
      graph: Arc::new(graph),
      tasks: Arc::new(tasks),
      roots: Vec::new(),
    }
  }

  pub fn visualize(&self, path: &Path) -> io::Result<()> {
    self.graph.visualize(&self.root_nodes(), path, &self.tasks.externs)
  }

  pub fn trace(&self, path: &Path) -> io::Result<()> {
    for root in self.root_nodes() {
      self.graph.trace(&root, path, &self.tasks.externs)?;
    }
    Ok(())
  }

  pub fn reset(&mut self) {
    self.roots.clear();
  }

  pub fn root_states(&self) -> Vec<(&Key, &TypeConstraint, Option<RootResult>)> {
    self.roots.iter()
      .map(|root| match root {
        &Root::Select(s) =>
          (&s.subject, &s.selector.product, self.graph.peek(s, &self.tasks.externs)),
        &Root::SelectDependencies(s) =>
          (&s.subject, &s.selector.product, self.graph.peek(s, &self.tasks.externs)),
      })
      .collect()
  }

  pub fn add_root_select(&mut self, subject: Key, product: TypeConstraint) {
    self.roots.push(
      Root::Select(Select::new(product, subject, Default::default()))
    );
  }

  pub fn add_root_select_dependencies(
    &mut self,
    subject: Key,
    product: TypeConstraint,
    dep_product: TypeConstraint,
    field: Field,
    field_types: Vec<TypeId>,
    transitive: bool,
  ) {
    self.roots.push(
      Root::SelectDependencies(
        SelectDependencies::new(
          selectors::SelectDependencies {
            product: product,
            dep_product: dep_product,
            field: field,
            field_types: field_types,
            transitive: transitive
          },
          subject,
          Default::default(),
        )
      )
    );
  }

  /**
   * Starts running a Node, and returns a Future that will succeed regardless of the
   * success of the node.
   */
  fn launch(&self, context_factory: BootstrapContextFactory, node: Node) -> CpuFuture<(), ()> {
    context_factory.pool.clone().spawn_fn(move || {
      context_factory.graph.create(node, &context_factory)
        .then::<_, Result<(), ()>>(|_| Ok(()))
    })
  }

  /**
   * Starting from existing roots, execute a graph to completion.
   */
  pub fn execute(&mut self) -> ExecutionStat {
    // TODO: Restore counts.
    let runnable_count = 0;
    let scheduling_iterations = 0;

    // We create a new pool per-execution to avoid worrying about re-initializing them
    // if the daemon has forked.
    let context_factory =
      BootstrapContextFactory {
        graph: self.graph.clone(),
        tasks: self.tasks.clone(),
        pool: CpuPool::new_num_cpus(),
      };

    // Bootstrap tasks for the roots, and then wait for all of them.
    self.tasks.externs.log(LogLevel::Debug, &format!("Launching {} roots.", self.roots.len()));
    let roots_res =
      future::join_all(
        self.root_nodes().into_iter()
          .map(|root| {
            self.launch(context_factory.clone(), root)
          })
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

/**
 * Root requests are limited to Selectors that produce (python) Values.
 */
enum Root {
  Select(Select),
  SelectDependencies(SelectDependencies),
}

pub type RootResult = Result<Value, Failure>;

#[derive(Clone)]
struct BootstrapContextFactory {
  graph: Arc<Graph>,
  tasks: Arc<Tasks>,
  pool: CpuPool,
}

impl ContextFactory for BootstrapContextFactory {
  fn create(&self, entry_id: EntryId) -> Context {
    Context::new(entry_id, self.graph.clone(), self.tasks.clone(), self.pool.clone())
  }
}

#[repr(C)]
pub struct ExecutionStat {
  runnable_count: u64,
  scheduling_iterations: u64,
}
