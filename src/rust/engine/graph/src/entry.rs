// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::mem;
use std::pin::pin;
use std::sync::{atomic, Arc};

use crate::context::{Context, DepState};
use crate::node::{EntryId, Node, NodeError};
use crate::test_trace_log;

use async_value::{AsyncValue, AsyncValueReceiver, AsyncValueSender};
use futures::channel::oneshot;
use futures::future::{self, BoxFuture, FutureExt};
use parking_lot::Mutex;
use workunit_store::RunId;

///
/// A token that uniquely identifies one run of a Node in the Graph. Each run of a Node has a
/// different RunToken associated with it. When a run completes, if the current RunToken of its
/// Node no longer matches the RunToken of the spawned work (because the Node was `cleared`), the
/// work is discarded. See `Entry::complete` for more information.
///
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RunToken(u32);

impl RunToken {
    pub fn initial() -> RunToken {
        RunToken(0)
    }

    fn next(self) -> RunToken {
        RunToken(self.0 + 1)
    }
}

///
/// A token associated with a Node that is incremented whenever its output value has (or might
/// have) changed. When a dependent consumes a dependency at a particular generation, that
/// generation is recorded on the consuming edge, and can later used to determine whether the
/// inputs to a node have changed.
///
/// Unlike the RunToken (which is incremented whenever a node re-runs), the Generation is only
/// incremented when the output of a node has changed.
///
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct Generation(u32);

impl Generation {
    pub fn initial() -> Generation {
        Generation(0)
    }

    fn next(self) -> Generation {
        Generation(self.0 + 1)
    }
}

#[derive(Debug)]
pub(crate) enum NodeInterrupt<N: Node> {
    Dirtied,
    Aborted(NodeResult<N>),
}

///
/// A result from running a Node.
///
#[derive(Clone, Debug)]
pub enum EntryResult<N: Node> {
    /// A value that is immediately readable by any consumer, with no constraints.
    Clean(N::Item),
    /// A consumer should check whether the dependencies of the Node have the same values as they
    /// did when this Node was last run; if so, the value can be re-used (and can move to "Clean").
    Dirty(N::Item),
    /// Similar to Clean, but the value may only be consumed in the same Run that produced it, and
    /// _must_ (unlike UncacheableDependencies) be recomputed in a new Run.
    Uncacheable(N::Item, RunId),
    /// A value that was computed from an Uncacheable node, and is thus Run-specific. If the Run id
    /// of a consumer matches, the value can be considered to be Clean: otherwise, is considered to
    /// be Dirty.
    UncacheableDependencies(N::Item, RunId),
}

impl<N: Node> EntryResult<N> {
    fn new(
        item: N::Item,
        context: &Context<N>,
        cacheable: bool,
        has_uncacheable_deps: bool,
    ) -> EntryResult<N> {
        if !cacheable {
            EntryResult::Uncacheable(item, context.run_id())
        } else if has_uncacheable_deps {
            EntryResult::UncacheableDependencies(item, context.run_id())
        } else {
            EntryResult::Clean(item)
        }
    }

    fn is_clean(&self, context: &Context<N>) -> bool {
        match self {
            EntryResult::Clean(..) => true,
            EntryResult::Uncacheable(_, run_id) => context.run_id() == *run_id,
            EntryResult::UncacheableDependencies(.., run_id) => context.run_id() == *run_id,
            EntryResult::Dirty(..) => false,
        }
    }

    fn has_uncacheable_deps(&self) -> bool {
        match self {
            EntryResult::Uncacheable(_, _) | EntryResult::UncacheableDependencies(_, _) => true,
            EntryResult::Clean(..) | EntryResult::Dirty(..) => false,
        }
    }

    /// Returns true if this result should block for polling (because there is no work to do
    /// currently to clean it).
    fn poll_should_wait(&self, context: &Context<N>) -> bool {
        match self {
            EntryResult::Uncacheable(_, run_id) => context.run_id() == *run_id,
            EntryResult::Dirty(..) => false,
            EntryResult::Clean(..) | EntryResult::UncacheableDependencies(_, _) => true,
        }
    }

    fn peek(&self, context: &Context<N>) -> Option<N::Item> {
        if self.is_clean(context) {
            Some(self.as_ref().clone())
        } else {
            None
        }
    }

    /// If the value is in a Clean state, mark it Dirty.
    fn dirty(&mut self) {
        match self {
            EntryResult::Clean(v)
            | EntryResult::UncacheableDependencies(v, _)
            | EntryResult::Uncacheable(v, _) => {
                *self = EntryResult::Dirty(v.clone());
            }
            EntryResult::Dirty(_) => {}
        }
    }

    /// Assert that the value is in "a dirty state", and move it to a clean state.
    fn clean(&mut self, context: &Context<N>, cacheable: bool, has_uncacheable_deps: bool) {
        let value = match self {
            EntryResult::Dirty(value) => value.clone(),
            EntryResult::UncacheableDependencies(value, _) => value.clone(),
            x => unreachable!("A node in state {:?} should not have been cleaned.", x),
        };

        *self = EntryResult::new(value, context, cacheable, has_uncacheable_deps);
    }
}

impl<N: Node> AsRef<N::Item> for EntryResult<N> {
    fn as_ref(&self) -> &N::Item {
        match self {
            EntryResult::Clean(v) => v,
            EntryResult::Dirty(v) => v,
            EntryResult::Uncacheable(v, _) => v,
            EntryResult::UncacheableDependencies(v, _) => v,
        }
    }
}

pub type NodeResult<N> = (
    Result<<N as Node>::Item, <N as Node>::Error>,
    Generation,
    bool,
);

#[derive(Debug)]
pub(crate) enum EntryState<N: Node> {
    // A node that has either been explicitly cleared, or has not yet started Running. In this state
    // there is no need for a dirty bit because the RunToken is either in its initial state, or has
    // been explicitly incremented when the node was cleared.
    //
    // The previous_result value is _not_ a valid value for this Entry: rather, it is preserved in
    // order to compute the generation value for this Node by comparing it to the new result the next
    // time the Node runs.
    NotStarted {
        run_token: RunToken,
        generation: Generation,
        pollers: Vec<oneshot::Sender<()>>,
        previous_result: Option<EntryResult<N>>,
    },
    // A node that is running. A running node that has been marked dirty re-runs rather than
    // completing.
    //
    // Holds an AsyncValue, which is canceled if either 1) all AsyncValueReceivers go away, 2) the
    // AsyncValue itself is dropped.
    //
    // The `previous_result` value for a Running node is not a valid value. See NotStarted.
    Running {
        run_token: RunToken,
        pending_value: AsyncValue<NodeResult<N>, NodeInterrupt<N>>,
        generation: Generation,
        previous_result: Option<EntryResult<N>>,
        is_cleaning: bool,
    },
    // A node that has completed, and then possibly been marked dirty. Because marking a node
    // dirty does not eagerly re-execute any logic, it will stay this way until a caller moves it
    // back to Running.
    //
    // A Completed entry can have "pollers" whom are waiting for the Node to either be dirtied or
    // otherwise invalidated.
    Completed {
        run_token: RunToken,
        generation: Generation,
        pollers: Vec<oneshot::Sender<()>>,
        result: EntryResult<N>,
        dep_generations: Vec<(EntryId, Generation)>,
    },
}

impl<N: Node> EntryState<N> {
    fn initial() -> EntryState<N> {
        EntryState::NotStarted {
            run_token: RunToken::initial(),
            generation: Generation::initial(),
            pollers: Vec::new(),
            previous_result: None,
        }
    }
}

///
/// An Entry and its adjacencies.
///
#[derive(Clone, Debug)]
pub(crate) struct Entry<N: Node> {
    node: Arc<N>,

    state: Arc<Mutex<EntryState<N>>>,
}

impl<N: Node> Entry<N> {
    ///
    /// Creates an Entry without starting it. This indirection exists because we cannot know
    /// the EntryId of an Entry until after it is stored in the Graph, and we need the EntryId
    /// in order to run the Entry.
    ///
    pub(crate) fn new(node: N) -> Entry<N> {
        Entry {
            node: Arc::new(node),
            state: Arc::new(Mutex::new(EntryState::initial())),
        }
    }

    pub fn node(&self) -> &N {
        &self.node
    }

    pub(crate) fn cacheable_with_output(&self, output: Option<&N::Item>) -> bool {
        let output_cacheable = if let Some(item) = output {
            self.node.cacheable_item(item)
        } else {
            false
        };

        output_cacheable && self.node.cacheable()
    }

    ///
    /// If this Node is currently complete and clean with the given Generation, then waits for it to
    /// be changed in any way. If the node is not clean, or the generation mismatches, returns
    /// immediately.
    ///
    pub async fn poll(&self, context: &Context<N>, last_seen_generation: Generation) {
        let recv = {
            let mut state = self.state.lock();
            let pollers = match *state {
                EntryState::Completed {
                    ref result,
                    generation,
                    ref mut pollers,
                    ..
                } if generation == last_seen_generation && result.poll_should_wait(context) => {
                    // The Node is clean in this context, and the last seen generation matches.
                    pollers
                }
                EntryState::NotStarted {
                    generation,
                    ref mut pollers,
                    ..
                } if generation == last_seen_generation => {
                    // The Node has not yet been started, but the last seen generation matches. This
                    // means that an error occurred on a previous run of the node, but it has already been
                    // observed by the caller.
                    pollers
                }
                _ => {
                    // The generation didn't match or the Node wasn't Completed. It should be requested
                    // without waiting.
                    return;
                }
            };

            // Add a poller on the node that will be notified when it is dirtied or dropped. If the Node
            // moves to another state, the receiver will be notified that the sender was dropped.
            let (send, recv) = oneshot::channel();
            pollers.push(send);
            recv
        };
        // Wait outside of the lock.
        let _ = recv.await;
    }

    ///
    /// If the Future for this Node has already completed, returns a clone of its result.
    ///
    pub fn peek(&self, context: &Context<N>) -> Option<N::Item> {
        let state = self.state.lock();
        match *state {
            EntryState::Completed { ref result, .. } => result.peek(context),
            _ => None,
        }
    }

    ///
    /// Spawn the execution of the node on an Executor, which will cause it to execute outside of
    /// the Graph and Entry locks and call back to the Entry to complete.
    ///
    pub(crate) fn spawn_node_execution(
        context_factory: &Context<N>,
        entry: Entry<N>,
        entry_id: EntryId,
        run_token: RunToken,
        generation: Generation,
        previous_dep_generations: Option<Vec<(EntryId, Generation)>>,
        previous_result: Option<EntryResult<N>>,
    ) -> (EntryState<N>, AsyncValueReceiver<NodeResult<N>>, Generation) {
        // Increment the RunToken to uniquely identify this work.
        let run_token = run_token.next();
        let context = context_factory.clone_for(entry_id);
        let context2 = context.clone();
        let entry2 = entry.clone();
        let (value, mut sender, receiver) = AsyncValue::<NodeResult<N>, NodeInterrupt<N>>::new();
        let is_cleaning = previous_dep_generations.is_some();

        let run_or_clean = async move {
            // If we have previous result generations, compare them to all current dependency
            // generations (which, if they are dirty, will cause recursive cleaning). If they
            // match, we can consider the previous result value to be clean for reuse.
            let clean_with_cacheability =
                if let Some(previous_dep_generations) = previous_dep_generations {
                    match context
                        .graph()
                        .attempt_cleaning(entry_id, run_token, &previous_dep_generations, &context)
                        .await
                    {
                        Err(()) => {
                            // If dependency generations mismatched, then the node's deps have already been
                            // cleared, and it should attempt to re-run.
                            context
                                .stats()
                                .cleaning_failed
                                .fetch_add(1, atomic::Ordering::SeqCst);
                            Err(())
                        }
                        Ok(uncacheable) => {
                            // Dependencies have not changed: Node is clean.
                            context
                                .stats()
                                .cleaning_succeeded
                                .fetch_add(1, atomic::Ordering::SeqCst);
                            Ok(DepState {
                                generations: previous_dep_generations,
                                has_uncacheable_deps: uncacheable,
                            })
                        }
                    }
                } else {
                    Err(())
                };

            // If the Node was clean, complete it. Otherwise, re-run.
            match clean_with_cacheability {
                Ok(dep_state) => {
                    // No dependencies have changed: we can complete the Node without changing its
                    // previous_result or generation.
                    (None, dep_state)
                }
                Err(()) => {
                    // The Node needs to (re-)run!
                    let res = entry.node().clone().run(context.clone()).await;
                    context.stats().ran.fetch_add(1, atomic::Ordering::SeqCst);
                    (Some(res), context.complete(entry.node()))
                }
            }
        };

        let _join = context2.graph().executor.clone().native_spawn(async move {
      let mut run_or_clean = pin!(run_or_clean);
      let (maybe_res, dep_state) = loop {
        tokio::select! {
          interrupt_item = sender.interrupted() => {
            match interrupt_item {
              Some(NodeInterrupt::Aborted(res)) => {
                  // We were aborted via terminate: complete with the given res.
                  break (Some(res.0), context2.complete(entry2.node()))
              }
              Some(NodeInterrupt::Dirtied) => {
                  // Attempt to clean the Node, and cancel it if we fail.
                  let dep_generations_so_far = context2.dep_generations_so_far(entry2.node());
                  if context2
                    .graph()
                    .attempt_cleaning(entry_id, run_token, &dep_generations_so_far, &context2)
                    .await.is_err() {
                    // The dependencies requested by the Node so far have changed: return to cancel
                    // the work so that it can be retried from the beginning.
                    return;
                  } else {
                    // No dependencies have actually changed: continue waiting.
                    continue;
                  }
              }
              None => {
                  // We were aborted via drop: exit.
                  entry2.cancel(run_token);
                  return;
              }
            }
          }
          maybe_res_and_state = &mut run_or_clean => {
            // Running (or cleaning) the Node completed.
            break maybe_res_and_state
          }
        }
      };
      // The node completed or was cleaned.
      entry2.complete(
        &context2,
        run_token,
        sender,
        dep_state.generations,
        dep_state.has_uncacheable_deps,
        maybe_res,
      );
    });

        (
            EntryState::Running {
                run_token,
                pending_value: value,
                generation,
                previous_result,
                is_cleaning,
            },
            receiver,
            generation,
        )
    }

    ///
    /// Returns a Future for the Node's value and Generation.
    ///
    /// The two separate state matches handle two cases: in the first case we simply want to mutate
    /// or clone the state, so we take it by reference without swapping it. In the second case, we
    /// need to consume the state (which avoids cloning some of the values held there), so we take it
    /// by value.
    ///
    pub(crate) fn get_node_result(
        &self,
        context: &Context<N>,
        entry_id: EntryId,
    ) -> BoxFuture<NodeResult<N>> {
        let mut state = self.state.lock();

        // First check whether the Node is already complete, or is currently running: in both of these
        // cases we return early without swapping the state of the Node.
        match *state {
            EntryState::Running {
                ref pending_value,
                generation,
                ..
            } => {
                if let Some(receiver) = pending_value.receiver() {
                    return async move {
                        receiver.recv().await.unwrap_or_else(|| {
                            (Err(N::Error::invalidated()), generation.next(), true)
                        })
                    }
                    .boxed();
                }
                // Else: this node was just canceled: fall through to restart it.
            }
            EntryState::Completed {
                ref result,
                generation,
                ..
            } if result.is_clean(context) => {
                return future::ready((
                    Ok(result.as_ref().clone()),
                    generation,
                    result.has_uncacheable_deps(),
                ))
                .boxed();
            }
            _ => (),
        };

        // Otherwise, we'll need to swap the state of the Node, so take it by value.
        let (next_state, receiver, generation) =
            match mem::replace(&mut *state, EntryState::initial()) {
                EntryState::NotStarted {
                    run_token,
                    generation,
                    previous_result,
                    ..
                }
                | EntryState::Running {
                    run_token,
                    generation,
                    previous_result,
                    ..
                } => Self::spawn_node_execution(
                    context,
                    self.clone(),
                    entry_id,
                    run_token,
                    generation,
                    None,
                    previous_result,
                ),
                EntryState::Completed {
                    run_token,
                    generation,
                    result,
                    dep_generations,
                    ..
                } => {
                    test_trace_log!(
                        "Re-starting node {:?}. It was: previous_result={:?}",
                        self.node,
                        result,
                    );
                    assert!(
                        !result.is_clean(context),
                        "A clean Node should not reach this point: {result:?}"
                    );
                    // The Node has already completed but needs to re-run. If the Node is dirty, we are the
                    // first caller to request it since it was marked dirty. We attempt to clean it (which
                    // will cause it to re-run if the dep_generations mismatch).
                    //
                    // On the other hand, if the Node is uncacheable, we store the previous result as
                    // Uncacheable, which allows its value to be used only within the current Run.
                    Self::spawn_node_execution(
                        context,
                        self.clone(),
                        entry_id,
                        run_token,
                        generation,
                        // TODO: This check shouldn't matter... it's whether we recompute the generations that
                        // matters.
                        if self.cacheable_with_output(Some(result.as_ref())) {
                            Some(dep_generations)
                        } else {
                            None
                        },
                        Some(result),
                    )
                }
            };

        // Swap in the new state, and return the receiver.
        *state = next_state;

        async move {
            receiver
                .recv()
                .await
                .unwrap_or_else(|| (Err(N::Error::invalidated()), generation.next(), true))
        }
        .boxed()
    }

    ///
    /// Called from the Executor when a Node is cancelled.
    ///
    /// See also: `Self::complete`.
    ///
    pub(crate) fn cancel(&self, result_run_token: RunToken) {
        let mut state = self.state.lock();

        // We care about exactly one case: a Running state with the same run_token. All other states
        // represent various (legal) race conditions. See `RunToken`'s docs for more information.
        match *state {
            EntryState::Running { run_token, .. } if result_run_token == run_token => {}
            _ => {
                return;
            }
        }

        *state = match mem::replace(&mut *state, EntryState::initial()) {
            EntryState::Running {
                run_token,
                generation,
                previous_result,
                ..
            } => {
                test_trace_log!("Canceling {:?} of {}.", run_token, self.node);
                EntryState::NotStarted {
                    run_token: run_token.next(),
                    generation,
                    pollers: Vec::new(),
                    previous_result,
                }
            }
            s => s,
        };
    }

    ///
    /// Called from the Executor when a Node completes.
    ///
    /// A `result` value of `None` indicates that the Node was found to be clean, and its previous
    /// result should be used. This special case exists to avoid 1) cloning the result to call this
    /// method, and 2) comparing the current/previous results unnecessarily.
    ///
    /// See also: `Self::cancel`.
    ///
    fn complete(
        &self,
        context: &Context<N>,
        result_run_token: RunToken,
        sender: AsyncValueSender<NodeResult<N>, NodeInterrupt<N>>,
        dep_generations: Vec<(EntryId, Generation)>,
        has_uncacheable_deps: bool,
        result: Option<Result<N::Item, N::Error>>,
    ) {
        let mut state = self.state.lock();

        // We care about exactly one case: a Running state with the same run_token. All other states
        // represent various (legal) race conditions. See `RunToken`'s docs for more information.
        match *state {
            EntryState::Running { run_token, .. } if result_run_token == run_token => {}
            _ => {
                // We care about exactly one case: a Running state with the same run_token. All other states
                // represent various (legal) race conditions.
                test_trace_log!(
                    "Not completing node {:?} because it was invalidated.",
                    self.node
                );
                return;
            }
        }

        *state = match mem::replace(&mut *state, EntryState::initial()) {
            EntryState::Running {
                run_token,
                mut generation,
                mut previous_result,
                ..
            } => {
                match result {
                    Some(Err(e)) => {
                        if let Some(previous_result) = previous_result.as_mut() {
                            previous_result.dirty();
                        }
                        generation = generation.next();
                        sender.send((Err(e), generation, true));
                        EntryState::NotStarted {
                            run_token: run_token.next(),
                            generation,
                            pollers: Vec::new(),
                            previous_result,
                        }
                    }
                    Some(Ok(result)) => {
                        let cacheable = self.cacheable_with_output(Some(&result));
                        let next_result: EntryResult<N> =
                            EntryResult::new(result, context, cacheable, has_uncacheable_deps);
                        if Some(next_result.as_ref())
                            != previous_result.as_ref().map(EntryResult::as_ref)
                        {
                            // Node was re-executed (ie not cleaned) and had a different result value.
                            generation = generation.next()
                        };
                        sender.send((
                            Ok(next_result.as_ref().clone()),
                            generation,
                            next_result.has_uncacheable_deps(),
                        ));
                        EntryState::Completed {
                            result: next_result,
                            pollers: Vec::new(),
                            dep_generations,
                            run_token,
                            generation,
                        }
                    }
                    None => {
                        // Node was clean.
                        // NB: The `expect` here avoids a clone and a comparison: see the method docs.
                        let mut result = previous_result
                            .expect("A Node cannot be marked clean without a previous result.");
                        result.clean(
                            context,
                            self.cacheable_with_output(Some(result.as_ref())),
                            has_uncacheable_deps,
                        );
                        sender.send((
                            Ok(result.as_ref().clone()),
                            generation,
                            result.has_uncacheable_deps(),
                        ));
                        EntryState::Completed {
                            result,
                            pollers: Vec::new(),
                            dep_generations,
                            run_token,
                            generation,
                        }
                    }
                }
            }
            s => s,
        };
    }

    ///
    /// Clears the state of this Node, forcing it to be recomputed.
    ///
    /// # Arguments
    ///
    /// * `graph_still_contains_edges` - If the caller has guaranteed that all edges from this Node
    ///   have been removed from the graph, they should pass false here, else true. We may want to
    ///   remove this parameter, and force this method to remove the edges, but that would require
    ///   acquiring the graph lock here, which we currently don't do.
    ///
    pub(crate) fn clear(&mut self, graph_still_contains_edges: bool) {
        let mut state = self.state.lock();

        let (run_token, generation, mut previous_result) =
            match mem::replace(&mut *state, EntryState::initial()) {
                EntryState::NotStarted {
                    run_token,
                    generation,
                    previous_result,
                    ..
                } => (run_token, generation, previous_result),
                EntryState::Running {
                    run_token,
                    pending_value,
                    generation,
                    previous_result,
                    ..
                } => {
                    std::mem::drop(pending_value);
                    (run_token, generation, previous_result)
                }
                EntryState::Completed {
                    run_token,
                    generation,
                    result,
                    ..
                } => (run_token, generation, Some(result)),
            };

        test_trace_log!("Clearing node {:?}", self.node);

        if graph_still_contains_edges {
            if let Some(previous_result) = previous_result.as_mut() {
                previous_result.dirty();
            }
        }

        // Swap in a state with a new RunToken value, which invalidates any outstanding work.
        *state = EntryState::NotStarted {
            run_token: run_token.next(),
            generation,
            pollers: Vec::new(),
            previous_result,
        };
    }

    ///
    /// Dirties this Node, which will cause it to examine its dependencies the next time it is
    /// requested, and re-run if any of them have changed generations.
    ///
    pub(crate) fn dirty(&mut self) {
        let state = &mut *self.state.lock();
        test_trace_log!("Dirtying node {:?}", self.node);
        match state {
            &mut EntryState::Completed {
                ref mut result,
                ref mut pollers,
                ..
            } => {
                // Drop the pollers, which will notify them of a change.
                pollers.clear();
                result.dirty();
                return;
            }
            &mut EntryState::NotStarted {
                ref mut pollers, ..
            } => {
                // Drop the pollers, which will notify them of a change.
                pollers.clear();
                return;
            }
            &mut EntryState::Running {
                ref mut pending_value,
                ..
            } => {
                // Attempt to interrupt the Running node with a notification that it has been dirtied. If
                // we fail to interrupt, fall through to move back to NotStarted.
                if pending_value.try_interrupt(NodeInterrupt::Dirtied).is_ok() {
                    return;
                }
            }
        };

        *state = match mem::replace(&mut *state, EntryState::initial()) {
            EntryState::Running {
                run_token,
                pending_value,
                generation,
                previous_result,
                ..
            } => {
                // We failed to interrupt the Running node, so cancel it.
                test_trace_log!(
                    "Failed to interrupt {:?} while running: canceling instead.",
                    self.node
                );
                std::mem::drop(pending_value);
                EntryState::NotStarted {
                    run_token,
                    generation,
                    pollers: Vec::new(),
                    previous_result,
                }
            }
            _ => unreachable!(),
        }
    }

    ///
    /// Terminates this Node with the given error iff it is Running.
    ///
    /// This method is asynchronous: the task running the Node will take some time to notice that it
    /// has been terminated, and to update the state of the Node.
    ///
    pub(crate) fn terminate(&mut self, err: N::Error) {
        let state = &mut *self.state.lock();
        test_trace_log!("Terminating node {:?} with {:?}", self.node, err);
        if let EntryState::Running {
            pending_value,
            generation,
            ..
        } = state
        {
            let _ = pending_value.try_interrupt(NodeInterrupt::Aborted((
                Err(err),
                generation.next(),
                true,
            )));
        };
    }

    ///
    /// Indicates that cleaning this Node has failed, returning an error if the RunToken has changed.
    ///
    pub(crate) fn cleaning_failed(&mut self, expected_run_token: RunToken) -> Result<(), ()> {
        let state = &mut *self.state.lock();
        match state {
            EntryState::Running {
                is_cleaning,
                run_token,
                ..
            } if *run_token == expected_run_token => {
                *is_cleaning = false;
                Ok(())
            }
            _ => Err(()),
        }
    }

    pub fn is_started(&self) -> bool {
        match *self.state.lock() {
            EntryState::NotStarted { .. } => false,
            EntryState::Completed { .. } | EntryState::Running { .. } => true,
        }
    }

    pub fn is_running(&self) -> bool {
        match *self.state.lock() {
            EntryState::Running { .. } => true,
            EntryState::Completed { .. } | EntryState::NotStarted { .. } => false,
        }
    }

    pub fn is_cleaning(&self) -> bool {
        match *self.state.lock() {
            EntryState::Running { is_cleaning, .. } => is_cleaning,
            EntryState::Completed { .. } | EntryState::NotStarted { .. } => false,
        }
    }

    pub(crate) fn format(&self, context: &Context<N>) -> String {
        let state = match self.peek(context) {
            Some(ref nr) => {
                let item = format!("{nr:?}");
                if item.len() <= 1024 {
                    item
                } else {
                    item.chars().take(1024).collect()
                }
            }
            None => "<None>".to_string(),
        };
        format!("{} == {}", self.node, state)
    }
}
