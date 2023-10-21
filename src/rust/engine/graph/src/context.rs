// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::ops::Deref;
use std::sync::atomic::{self, AtomicU32, AtomicUsize};
use std::sync::Arc;

use parking_lot::Mutex;
use workunit_store::RunId;

use crate::entry::Generation;
use crate::node::{CompoundNode, EntryId, Node, NodeError};
use crate::Graph;

struct InnerContext<N: Node + Send> {
    context: N::Context,
    run_id: AtomicU32,
    stats: Stats,
    graph: Graph<N>,
}

#[derive(Clone, Default)]
pub(crate) struct DepState {
    pub(crate) generations: Vec<(EntryId, Generation)>,
    pub(crate) has_uncacheable_deps: bool,
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
    dep_state: Arc<Mutex<Option<DepState>>>,
    inner: Arc<InnerContext<N>>,
}

impl<N: Node + Send> Context<N> {
    pub(crate) fn new(graph: Graph<N>, context: N::Context, run_id: RunId) -> Self {
        Self {
            entry_id: None,
            dep_state: Arc::default(),
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
        let (node_result, _generation) = self
            .inner
            .graph
            .get_inner(self.entry_id, self, node.into())
            .await;

        node_result?.try_into().map_err(|_| {
            N::Error::generic(format!(
                "The CompoundNode implementation for {} was ambiguous.",
                std::any::type_name::<CN>()
            ))
        })
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

    pub(crate) fn dep_record(
        &self,
        dep_id: EntryId,
        generation: Generation,
        uncacheable: bool,
    ) -> Result<(), N::Error> {
        let mut maybe_dep_state = self.dep_state.lock();
        if let Some(dep_state) = maybe_dep_state.as_mut() {
            dep_state.generations.push((dep_id, generation));
            dep_state.has_uncacheable_deps |= uncacheable;
            Ok(())
        } else {
            // This case can occur if a Node has spawned background work which continues to attempt
            // to request dependencies in the background.
            Err(N::Error::generic(format!(
                "Could not request additional dependencies for {:?}: the Node has completed.",
                self.entry_id
            )))
        }
    }

    ///
    /// Gets the dependency generations which have been computed for this Node so far. May not be
    /// called after `complete` has been called for a node.
    ///
    pub(crate) fn dep_generations_so_far(&self, node: &N) -> Vec<(EntryId, Generation)> {
        (*self.dep_state.lock())
            .clone()
            .unwrap_or_else(|| panic!("Node {node} has already completed."))
            .generations
    }

    ///
    /// Completes the Context for this EntryId, returning the dependency generations that were
    /// recorded while it was running. May only be called once.
    ///
    pub(crate) fn complete(&self, node: &N) -> DepState {
        self.dep_state
            .lock()
            .take()
            .unwrap_or_else(|| panic!("Node {node} was completed multiple times."))
    }

    ///
    /// Creates a clone of this Context to be used for a different Node.
    ///
    /// To clone a Context for use by the _same_ Node, `Clone` is used directly.
    ///
    pub(crate) fn clone_for(&self, entry_id: EntryId) -> Self {
        Self {
            entry_id: Some(entry_id),
            dep_state: Arc::new(Mutex::new(Some(DepState::default()))),
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
