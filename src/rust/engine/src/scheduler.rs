// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::io;
use std::path::Path;
use std::sync::Arc;

use futures::future::{self, Future};

use context::{Context, ContextFactory, Core};
use core::{Failure, Field, Key, TypeConstraint, TypeId, Value};
use externs::{self, LogLevel};
use graph::EntryId;
use nodes::{NodeKey, Select, SelectDependencies};
use rule_graph;
use selectors;

///
/// Represents the state of an execution of (a subgraph of) a Graph.
///
pub struct Scheduler {
  pub core: Arc<Core>,
  // Initial set of roots for the execution, in the order they were declared.
  roots: Vec<Root>,
}

impl Scheduler {
  ///
  /// Roots are limited to either `SelectDependencies` and `Select`, which are known to
  /// produce Values. But this method exists to satisfy Graph APIs which only need instances
  /// of the NodeKey enum.
  ///
  fn root_nodes(&self) -> Vec<NodeKey> {
    self.roots.iter()
      .map(|r| match r {
        &Root::Select(ref s) => s.clone().into(),
        &Root::SelectDependencies(ref s) => s.clone().into(),
      })
      .collect()
  }

  ///
  /// Creates a Scheduler with an initially empty set of roots.
  ///
  pub fn new(core: Core) -> Scheduler {
    Scheduler {
      core: Arc::new(core),
      roots: Vec::new(),
    }
  }

  pub fn visualize(&self, path: &Path) -> io::Result<()> {
    self.core.graph.visualize(&self.root_nodes(), path)
  }

  pub fn trace(&self, path: &Path) -> io::Result<()> {
    for root in self.root_nodes() {
      self.core.graph.trace(&root, path)?;
    }
    Ok(())
  }

  pub fn reset(&mut self) {
    self.roots.clear();
  }

  pub fn root_states(&self) -> Vec<(&Key, &TypeConstraint, Option<RootResult>)> {
    self.roots.iter()
      .map(|root| match root {
        &Root::Select(ref s) =>
          (&s.subject, &s.selector.product, self.core.graph.peek(s.clone())),
        &Root::SelectDependencies(ref s) =>
          (&s.subject, &s.selector.product, self.core.graph.peek(s.clone())),
      })
      .collect()
  }

  pub fn add_root_select(&mut self, subject: Key, product: TypeConstraint) {
    let edges = self.find_root_edges_or_update_rule_graph(
      subject.type_id().clone(),
      selectors::Selector::Select(selectors::Select::without_variant(product))
    );
    self.roots.push(
      Root::Select(Select::new(product,
                               subject,
                               Default::default(),
                               &edges)
      )
    );
  }

  pub fn add_root_select_dependencies(
    &mut self,
    subject: Key,
    product: TypeConstraint,
    dep_product: TypeConstraint,
    field: Field,
    field_types: Vec<TypeId>
  ) {
    let selector = selectors::SelectDependencies {
      product: product,
      dep_product: dep_product,
      field: field,
      field_types: field_types,
    };

    let edges = self.find_root_edges_or_update_rule_graph(
      subject.type_id().clone(),
      selectors::Selector::SelectDependencies(selector.clone()));
    self.roots.push(
      Root::SelectDependencies(
        SelectDependencies::new(
          selector.clone(),
          subject,
          Default::default(),
          &edges
        )
      )
    );
  }

  fn find_root_edges_or_update_rule_graph(&self, subject_type: TypeId, selector: selectors::Selector) -> rule_graph::RuleEdges {
    // TODO what to do if there isn't a match, ie if there is a root type that hasn't been specified
    // TODO up front.
    // TODO Handle the case where the requested root is not in the list of roots that the graph was
    //      created with.
    //
    //      Options
    //        1. Toss the graph and make a subgraph specific graph, blowing up if that fails.
    //           I can do this with minimal changes.
    //        2. Update the graph & check result,

    self.core.rule_graph.find_root_edges(
      subject_type.clone(),
      selector.clone()
    ).expect(&format!("Edges to have been found TODO handle this selector: {:?}, subject {:?}", selector, subject_type))
  }

  ///
  /// Starting from existing roots, execute a graph to completion.
  ///
  pub fn execute(&mut self) -> ExecutionStat {
    // TODO: Restore counts.
    let runnable_count = 0;
    let scheduling_iterations = 0;

    // Bootstrap tasks for the roots, and then wait for all of them.
    externs::log(LogLevel::Debug, &format!("Launching {} roots.", self.roots.len()));
    let roots_res =
      future::join_all(
        self.root_nodes().into_iter()
          .map(|root| {
            self.core.graph.create(root.clone(), &self.core)
              .then::<_, Result<(), ()>>(move |_| {
                externs::log(LogLevel::Debug, &format!("Root {} completed.", root.format()));
                Ok(())
              })
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

///
/// Root requests are limited to Selectors that produce (python) Values.
///
enum Root {
  Select(Select),
  SelectDependencies(SelectDependencies),
}

pub type RootResult = Result<Value, Failure>;

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
