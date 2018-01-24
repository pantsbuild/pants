// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::io;
use std::path::Path;
use std::sync::Arc;

use futures::future::{self, Future};

use boxfuture::{Boxable, BoxFuture};
use context::{Context, ContextFactory, Core};
use core::{Failure, Key, TypeConstraint, TypeId, Value};
use externs::{self, LogLevel};
use graph::EntryId;
use nodes::{NodeKey, Select};
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
        rule_graph::selector_str(&selector),
        subject_type
      ))
  }

  ///
  /// Attempts to complete all of the given roots, retrying the entire set (up to `count`
  /// times) if any of them fail with `Failure::Invalidated`.
  ///
  /// In common usage, graph entries won't be repeatedly invalidated, but in a case where they
  /// were (say by an automated process changing files under pants), we'd want to eventually
  /// give up.
  ///
  fn execute_helper(
    core: Arc<Core>,
    roots: Vec<Root>,
    count: usize,
  ) -> BoxFuture<Vec<Result<Value, Failure>>, ()> {
    // Attempt all roots in parallel, failing fast to retry for `Invalidated`.
    let roots_res = future::join_all(
      roots
        .clone()
        .into_iter()
        .map(|root| {
          core
            .graph
            .create(root.clone(), &core)
            .then::<_, Result<Result<Value, Failure>, Failure>>(move |r| {
              match r {
                Err(Failure::Invalidated) if count > 0 => {
                  // A node was invalidated: fail quickly so that all roots can be retried.
                  Err(Failure::Invalidated)
                }
                other => {
                  // Otherwise (if it is a success, some other type of Failure, or if we've run
                  // out of retries) recover to complete the join, which will cause the results to
                  // propagate to the user.
                  externs::log(
                    LogLevel::Debug,
                    &format!("Root {} completed.", NodeKey::Select(root).format()),
                  );
                  Ok(other)
                }
              }
            })
        })
        .collect::<Vec<_>>(),
    );

    // If the join failed (due to `Invalidated`, since that is the only error we propagate), retry
    // the entire set of roots.
    roots_res
      .or_else(move |_| Scheduler::execute_helper(core, roots, count - 1))
      .to_boxed()
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

    // Wait for all roots to complete. Failure here should be impossible, because each
    // individual Future in the join was (eventually) mapped into success.
    let results = Scheduler::execute_helper(self.core.clone(), request.roots.clone(), 8)
      .wait()
      .expect("Execution failed.");

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
