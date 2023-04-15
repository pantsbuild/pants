// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::ops::Deref;
use std::sync::atomic::{self, AtomicU32, AtomicUsize};
use std::sync::Arc;

use workunit_store::RunId;

use crate::node::{CompoundNode, EntryId, Node};
use crate::Graph;

struct InnerContext<N: Node + Send> {
  context: N::Context,
  run_id: AtomicU32,
  stats: Stats,
  graph: Graph<N>,
}

///
/// A context passed between running Nodes which is used to request and record dependencies.
///
/// Parametrized by:
///     N: Node - The Node type that this Context is being used for.
///
#[derive(Clone)]
pub struct Context<N: Node + Send> {
  entry_id: Option<EntryId>,
  inner: Arc<InnerContext<N>>,
}

impl<N: Node + Send> Context<N> {
  pub(crate) fn new(graph: Graph<N>, context: N::Context, run_id: RunId) -> Self {
    Self {
      entry_id: None,
      inner: Arc::new(InnerContext {
        context,
        run_id: AtomicU32::new(run_id.0),
        stats: Stats::default(),
        graph,
      }),
    }
  }

  ///
  /// Get the future value for the given Node implementation.
  ///
  pub async fn get<CN: CompoundNode<N>>(&self, node: CN) -> Result<CN::Item, N::Error> {
    let node_result = self
      .inner
      .graph
      .get(self.entry_id, self, node.into())
      .await?;
    Ok(
      node_result
        .try_into()
        .unwrap_or_else(|_| panic!("A Node implementation was ambiguous.")),
    )
  }

  pub fn run_id(&self) -> RunId {
    RunId(self.inner.run_id.load(atomic::Ordering::SeqCst))
  }

  pub fn new_run_id(&self) {
    self.inner.run_id.store(
      self.inner.graph.generate_run_id().0,
      atomic::Ordering::SeqCst,
    );
  }

  pub fn context(&self) -> &N::Context {
    &self.inner.context
  }

  pub fn graph(&self) -> &Graph<N> {
    &self.inner.graph
  }

  pub(crate) fn stats(&self) -> &Stats {
    &self.inner.stats
  }

  ///
  /// Creates a clone of this Context to be used for a different Node.
  ///
  /// To clone a Context for use by the _same_ Node, `Clone` is used directly.
  ///
  pub(crate) fn clone_for(&self, entry_id: EntryId) -> Self {
    Context {
      entry_id: Some(entry_id),
      inner: self.inner.clone(),
    }
  }
}

impl<N: Node> Deref for Context<N> {
  type Target = N::Context;

  fn deref(&self) -> &Self::Target {
    &self.inner.context
  }
}

#[derive(Default)]
pub(crate) struct Stats {
  pub ran: AtomicUsize,
  pub cleaning_succeeded: AtomicUsize,
  pub cleaning_failed: AtomicUsize,
}
