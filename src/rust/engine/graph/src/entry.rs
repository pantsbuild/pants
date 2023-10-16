use std::mem;
use std::sync::Arc;

use crate::node::{EntryId, Node, NodeContext, NodeError};
use crate::test_trace_log;

use async_value::{AsyncValue, AsyncValueReceiver, AsyncValueSender};
use futures::channel::oneshot;
use futures::future::{self, BoxFuture, FutureExt};
use parking_lot::Mutex;

///
/// A token that uniquely identifies one run of a Node in the Graph. Each run of a Node (via
/// `N::Context::spawn`) has a different RunToken associated with it. When a run completes, if
/// the current RunToken of its Node no longer matches the RunToken of the spawned work (because
/// the Node was `cleared`), the work is discarded. See `Entry::complete` for more information.
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
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Generation(u32);

impl Generation {
    pub fn initial() -> Generation {
        Generation(0)
    }

    fn next(self) -> Generation {
        Generation(self.0 + 1)
    }
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
    Uncacheable(N::Item, <<N as Node>::Context as NodeContext>::RunId),
    /// A value that was computed from an Uncacheable node, and is thus Run-specific. If the Run id
    /// of a consumer matches, the value can be considered to be Clean: otherwise, is considered to
    /// be Dirty.
    UncacheableDependencies(N::Item, <<N as Node>::Context as NodeContext>::RunId),
}

impl<N: Node> EntryResult<N> {
    fn new(
        item: N::Item,
        context: &N::Context,
        cacheable: bool,
        has_uncacheable_deps: bool,
    ) -> EntryResult<N> {
        if !cacheable {
            EntryResult::Uncacheable(item, context.run_id().clone())
        } else if has_uncacheable_deps {
            EntryResult::UncacheableDependencies(item, context.run_id().clone())
        } else {
            EntryResult::Clean(item)
        }
    }

    fn is_clean(&self, context: &N::Context) -> bool {
        match self {
            EntryResult::Clean(..) => true,
            EntryResult::Uncacheable(_, run_id) => context.run_id() == run_id,
            EntryResult::UncacheableDependencies(.., run_id) => context.run_id() == run_id,
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
    fn poll_should_wait(&self, context: &N::Context) -> bool {
        match self {
            EntryResult::Uncacheable(_, run_id) => context.run_id() == run_id,
            EntryResult::Dirty(..) => false,
            EntryResult::Clean(..) | EntryResult::UncacheableDependencies(_, _) => true,
        }
    }

    fn peek(&self, context: &N::Context) -> Option<N::Item> {
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
    fn clean(&mut self, context: &N::Context, cacheable: bool, has_uncacheable_deps: bool) {
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

pub type NodeResult<N> = Result<(<N as Node>::Item, Generation), <N as Node>::Error>;

#[derive(Debug)]
pub enum EntryState<N: Node> {
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
        pending_value: AsyncValue<NodeResult<N>>,
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
        dep_generations: Vec<Generation>,
    },
}

impl<N: Node> EntryState<N> {
    fn initial() -> EntryState<N> {
        EntryState::NotStarted {
            run_token: RunToken::initial(),
            generation: Generation::initial(),
            previous_result: None,
        }
    }
}

///
/// An Entry and its adjacencies.
///
#[derive(Clone, Debug)]
pub struct Entry<N: Node> {
    // TODO: This is a clone of the Node, which is also kept in the `nodes` map. It would be
    // nice to avoid keeping two copies of each Node, but tracking references between the two
    // maps is painful.
    node: N,

    pub state: Arc<Mutex<EntryState<N>>>,
}

impl<N: Node> Entry<N> {
    ///
    /// Creates an Entry without starting it. This indirection exists because we cannot know
    /// the EntryId of an Entry until after it is stored in the Graph, and we need the EntryId
    /// in order to run the Entry.
    ///
    pub(crate) fn new(node: N) -> Entry<N> {
        Entry {
            node,
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
    pub async fn poll(&self, context: &N::Context, last_seen_generation: Generation) {
        let recv = {
            let mut state = self.state.lock();
            match *state {
                EntryState::Completed {
                    ref result,
                    generation,
                    ref mut pollers,
                    ..
                } if generation == last_seen_generation && result.poll_should_wait(context) => {
                    // The Node is currently clean with the observed generation: add a poller on the
                    // Completed node that will be notified when it is dirtied or dropped. If the Node moves
                    // to another state, the received will be notified that the sender was dropped, and it
                    // will be converted into a successful result.
                    let (send, recv) = oneshot::channel();
                    pollers.push(send);
                    recv
                }
                _ => {
                    // The generation didn't match or the Node wasn't Completed. It should be requested
                    // without waiting.
                    return;
                }
            }
        };
        // Wait outside of the lock.
        let _ = recv.await;
    }

    ///
    /// If the Future for this Node has already completed, returns a clone of its result.
    ///
    pub fn peek(&self, context: &N::Context) -> Option<N::Item> {
        let state = self.state.lock();
        match *state {
            EntryState::Completed { ref result, .. } => result.peek(context),
            _ => None,
        }
    }

    ///
    /// Spawn the execution of the node on an Executor, which will cause it to execute outside of
    /// the Graph lock and call back into the graph lock to set the final value.
    ///
    pub(crate) fn spawn_node_execution(
        context_factory: &N::Context,
        node: &N,
        entry_id: EntryId,
        run_token: RunToken,
        generation: Generation,
        previous_dep_generations: Option<Vec<Generation>>,
        previous_result: Option<EntryResult<N>>,
    ) -> (EntryState<N>, AsyncValueReceiver<NodeResult<N>>) {
        // Increment the RunToken to uniquely identify this work.
        let run_token = run_token.next();
        let context = context_factory.clone_for(entry_id);
        let context2 = context.clone();
        let node = node.clone();
        let (value, mut sender, receiver) = AsyncValue::<NodeResult<N>>::new();
        let is_cleaning = previous_dep_generations.is_some();

        let run_or_clean = async move {
            // If we have previous result generations, compare them to all current dependency
            // generations (which, if they are dirty, will cause recursive cleaning). If they
            // match, we can consider the previous result value to be clean for reuse.
            let was_clean = if let Some(previous_dep_generations) = previous_dep_generations {
                if context
                    .graph()
                    .dependencies_changed(entry_id, previous_dep_generations, &context)
                    .await
                {
                    // If dependency generations mismatched or failed to fetch, clear the node's dependencies
                    // and indicate that it should re-run.
                    context.graph().cleaning_failed(entry_id, run_token);
                    context.stats().cleaning_failed += 1;
                    false
                } else {
                    // Dependencies have not changed: Node is clean.
                    context.stats().cleaning_succeeded += 1;
                    true
                }
            } else {
                false
            };

            // If the Node was clean, complete it. Otherwise, re-run.
            if was_clean {
                // No dependencies have changed: we can complete the Node without changing its
                // previous_result or generation.
                None
            } else {
                // The Node needs to (re-)run!
                let res = node.run(context.clone()).await;
                context.stats().ran += 1;
                Some(res)
            }
        };

        context_factory.spawn(async move {
            let maybe_res = tokio::select! {
              abort_item = sender.aborted() => {
                if let Some(res) = abort_item {
                  // We were aborted via terminate: complete with the given res.
                  Some(res.map(|v| v.0))
                } else {
                  // We were aborted via drop: exit.
                  context2
                    .graph()
                    .cancel(entry_id, run_token);
                  return;
                }
              }
              maybe_res = run_or_clean => {
                maybe_res
              }
            };
            // The node completed.
            context2
                .graph()
                .complete(&context2, entry_id, run_token, sender, maybe_res);
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
        &mut self,
        context: &N::Context,
        entry_id: EntryId,
    ) -> BoxFuture<NodeResult<N>> {
        let mut state = self.state.lock();

        // First check whether the Node is already complete, or is currently running: in both of these
        // cases we return early without swapping the state of the Node.
        match *state {
            EntryState::Running {
                ref pending_value, ..
            } => {
                if let Some(receiver) = pending_value.receiver() {
                    return async move { receiver.recv().await.ok_or_else(N::Error::invalidated)? }
                        .boxed();
                }
                // Else: this node was just canceled: fall through to restart it.
            }
            EntryState::Completed {
                ref result,
                generation,
                ..
            } if result.is_clean(context) => {
                return future::ready(Ok((result.as_ref().clone(), generation))).boxed();
            }
            _ => (),
        };

        // Otherwise, we'll need to swap the state of the Node, so take it by value.
        let (next_state, receiver) = match mem::replace(&mut *state, EntryState::initial()) {
            EntryState::NotStarted {
                run_token,
                generation,
                previous_result,
            }
            | EntryState::Running {
                run_token,
                generation,
                previous_result,
                ..
            } => Self::spawn_node_execution(
                context,
                &self.node,
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
                    "A clean Node should not reach this point: {:?}",
                    result
                );
                // The Node has already completed but needs to re-run. If the Node is dirty, we are the
                // first caller to request it since it was marked dirty. We attempt to clean it (which
                // will cause it to re-run if the dep_generations mismatch).
                //
                // On the other hand, if the Node is uncacheable, we store the previous result as
                // Uncacheable, which allows its value to be used only within the current Run.
                Self::spawn_node_execution(
                    context,
                    &self.node,
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

        async move { receiver.recv().await.ok_or_else(N::Error::invalidated)? }.boxed()
    }

    ///
    /// Called from the Executor when a Node is cancelled.
    ///
    /// See also: `Self::complete`.
    ///
    pub(crate) fn cancel(&mut self, result_run_token: RunToken) {
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
    /// Takes a &mut InnerGraph to ensure that completing nodes doesn't race with dirtying them.
    /// The important relationship being guaranteed here is that if the Graph is calling
    /// invalidate_from_roots, it may mark us, or our dependencies, as dirty. We don't want to
    /// complete _while_ a batch of nodes are being marked as dirty, and this exclusive access ensures
    /// that can't happen.
    ///
    /// See also: `Self::cancel`.
    ///
    pub(crate) fn complete(
        &mut self,
        context: &N::Context,
        result_run_token: RunToken,
        dep_generations: Vec<Generation>,
        sender: AsyncValueSender<NodeResult<N>>,
        result: Option<Result<N::Item, N::Error>>,
        has_uncacheable_deps: bool,
        _graph: &mut super::InnerGraph<N>,
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
                        sender.send(Err(e));
                        EntryState::NotStarted {
                            run_token: run_token.next(),
                            generation,
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
                        sender.send(Ok((next_result.as_ref().clone(), generation)));
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
                        sender.send(Ok((result.as_ref().clone(), generation)));
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
    /// Get the current Generation of this entry.
    ///
    /// TODO: Consider moving the Generation and RunToken out of the EntryState once we decide what
    /// we want the per-Entry locking strategy to be.
    ///
    pub(crate) fn generation(&self) -> Generation {
        match *self.state.lock() {
            EntryState::NotStarted { generation, .. }
            | EntryState::Running { generation, .. }
            | EntryState::Completed { generation, .. } => generation,
        }
    }

    ///
    /// Get the current RunToken of this entry.
    ///
    /// TODO: Consider moving the Generation and RunToken out of the EntryState once we decide what
    /// we want the per-Entry locking strategy to be.
    ///
    pub(crate) fn run_token(&self) -> RunToken {
        match *self.state.lock() {
            EntryState::NotStarted { run_token, .. }
            | EntryState::Running { run_token, .. }
            | EntryState::Completed { run_token, .. } => run_token,
        }
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
            previous_result,
        };
    }

    ///
    /// Dirties this Node, which will cause it to examine its dependencies the next time it is
    /// requested, and re-run if any of them have changed generations.
    ///
    /// See comment on complete for information about _graph argument.
    ///
    pub(crate) fn dirty(&mut self, _graph: &mut super::InnerGraph<N>) {
        let state = &mut *self.state.lock();
        test_trace_log!("Dirtying node {:?}", self.node);
        match state {
            &mut EntryState::Completed {
                ref mut result,
                ref mut pollers,
                ..
            } => {
                // Notify all pollers (ignoring any that have gone away.)
                for poller in pollers.drain(..) {
                    let _ = poller.send(());
                }
                result.dirty();
                return;
            }
            &mut EntryState::NotStarted { .. } => return,
            &mut EntryState::Running { .. } if !self.node.cacheable() => {
                // An uncacheable node cannot be interrupted.
                return;
            }
            &mut EntryState::Running { .. } => {
                // Handled below: we need to move back to NotStarted.
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
                // Dirtying a Running node immediately cancels it.
                test_trace_log!("Node {:?} was dirtied while running.", self.node);
                std::mem::drop(pending_value);
                EntryState::NotStarted {
                    run_token,
                    generation,
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
        if let EntryState::Running { pending_value, .. } = state {
            let _ = pending_value.try_abort(Err(err));
        };
    }

    ///
    /// Indicates that cleaning this Node has failed.
    ///
    pub(crate) fn cleaning_failed(&mut self) {
        let state = &mut *self.state.lock();
        if let EntryState::Running { is_cleaning, .. } = state {
            *is_cleaning = false;
        };
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

    pub fn is_clean(&self, context: &N::Context) -> bool {
        match *self.state.lock() {
            EntryState::NotStarted {
                ref previous_result,
                ..
            }
            | EntryState::Running {
                ref previous_result,
                ..
            } => {
                if let Some(result) = previous_result {
                    result.is_clean(context)
                } else {
                    true
                }
            }
            EntryState::Completed { ref result, .. } => result.is_clean(context),
        }
    }

    pub(crate) fn has_uncacheable_deps(&self) -> bool {
        match *self.state.lock() {
            EntryState::Completed { ref result, .. } => result.has_uncacheable_deps(),
            EntryState::NotStarted { .. } | EntryState::Running { .. } => false,
        }
    }

    pub(crate) fn format(&self, context: &N::Context) -> String {
        let state = match self.peek(context) {
            Some(ref nr) => format!("{:?}", nr),
            None => "<None>".to_string(),
        };
        format!("{} == {}", self.node, state).replace('"', "\\\"")
    }
}
