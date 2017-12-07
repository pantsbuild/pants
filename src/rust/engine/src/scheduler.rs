// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::io;
use std::path::Path;
use std::sync::Arc;

use futures::future::{self, Future};

use boxfuture::Boxable;
use context::{Context, ContextFactory, Core};
use core::{Failure, Key, TypeConstraint, TypeId, throw, Value};
use externs::{self, LogLevel};
use graph::EntryId;
use nodes::{NodeFuture, NodeKey, Select};
use rule_graph;
use selectors;

pub struct ExecutionRequest {
  // Set of roots for an execution, in the order they were declared.
  pub roots: Vec<Root>,
}

impl ExecutionRequest {
  pub fn new() -> ExecutionRequest {
    ExecutionRequest { roots: Vec::new() }
  }

  ///
  /// Roots are limited to `Select`, which is known to produce a Value. This method
  /// exists to satisfy Graph APIs which need instances of the NodeKey enum.
  ///
  fn root_nodes(&self) -> Vec<NodeKey> {
    self.roots.iter().map(|r| r.clone().into()).collect()
  }
}

///
/// Represents the state of an execution of a Graph.
///
pub struct Scheduler {
  pub core: Arc<Core>,
}

impl Scheduler {
  pub fn new(core: Core) -> Scheduler {
    Scheduler { core: Arc::new(core) }
  }

  pub fn visualize(&self, request: &ExecutionRequest, path: &Path) -> io::Result<()> {
    self.core.graph.visualize(&request.root_nodes(), path)
  }

  pub fn trace(&self, request: &ExecutionRequest, path: &Path) -> io::Result<()> {
    for root in request.root_nodes() {
      self.core.graph.trace(&root, path)?;
    }
    Ok(())
  }

  pub fn add_root_select(
    &self,
    request: &mut ExecutionRequest,
    subject: Key,
    product: TypeConstraint,
  ) {
    let edges = self.find_root_edges_or_update_rule_graph(
      subject.type_id().clone(),
      selectors::Selector::Select(selectors::Select::without_variant(product)),
    );
    request.roots.push(Select::new(
      product,
      subject,
      Default::default(),
      &edges,
    ));
  }

  fn find_root_edges_or_update_rule_graph(
    &self,
    subject_type: TypeId,
    selector: selectors::Selector,
  ) -> rule_graph::RuleEdges {
    // TODO what to do if there isn't a match, ie if there is a root type that hasn't been specified
    // TODO up front.
    // TODO Handle the case where the requested root is not in the list of roots that the graph was
    //      created with.
    //
    //      Options
    //        1. Toss the graph and make a subgraph specific graph, blowing up if that fails.
    //           I can do this with minimal changes.
    //        2. Update the graph & check result,

    self
      .core
      .rule_graph
      .find_root_edges(subject_type.clone(), selector.clone())
      .expect(&format!(
        "Edges to have been found TODO handle this selector: {:?}, subject {:?}",
        selector,
        subject_type
      ))
  }

  ///
  /// Attempts to complete a Node, recovering from `Failure::Invalidated` up to `count` times.
  ///
  /// In common usage, graph entries won't be repeatedly invalidated, but in a case where they
  /// were (say by an automated process changing files under pants), we'd want to eventually
  /// give up.
  ///
  fn create(core: Arc<Core>, root: Root, count: usize) -> NodeFuture<Value> {
    if count == 0 {
      future::err(throw("Exhausted retries due to changed files.")).to_boxed()
    } else {
      core
        .graph
        .create(root.clone(), &core)
        .or_else(move |e| match e {
          Failure::Invalidated => Scheduler::create(core, root, count - 1),
          x => future::err(x).to_boxed(),
        })
        .to_boxed()
    }
  }

  ///
  /// Compute the results for roots in the given request.
  ///
  pub fn execute<'e>(
    &mut self,
    request: &'e ExecutionRequest,
  ) -> Vec<(&'e Key, &'e TypeConstraint, RootResult)> {
    // Bootstrap tasks for the roots, and then wait for all of them.
    externs::log(
      LogLevel::Debug,
      &format!("Launching {} roots.", request.roots.len()),
    );
    let roots_res = future::join_all(
      request
        .roots
        .iter()
        .map(|root| {
          Scheduler::create(self.core.clone(), root.clone(), 8)
            .then::<_, Result<Result<Value, Failure>, ()>>(move |r| {
              externs::log(
                LogLevel::Debug,
                &format!("Root {} completed.", NodeKey::Select(root.clone()).format()),
              );
              Ok(r)
            })
        })
        .collect::<Vec<_>>(),
    );

    // Wait for all roots to complete. Failure here should be impossible, because each
    // individual Future in the join was mapped into success.
    let results = roots_res.wait().expect("Execution failed.");

    request
      .roots
      .iter()
      .zip(results.into_iter())
      .map(|(s, r)| (&s.subject, &s.selector.product, r))
      .collect()
  }
}

///
/// Root requests are limited to Selectors that produce (python) Values.
///
type Root = Select;

pub type RootResult = Result<Value, Failure>;

impl ContextFactory for Arc<Core> {
  fn create(&self, entry_id: EntryId) -> Context {
    Context::new(entry_id, self.clone())
  }
}
