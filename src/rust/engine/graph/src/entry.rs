use std::mem;
use std::sync::Arc;
use std::time::{Duration, Instant};

use node::{EntryId, Node, NodeContext, NodeError};

use futures::future::{self, Future};
use futures::sync::oneshot;
use parking_lot::Mutex;

use boxfuture::{BoxFuture, Boxable};

///
/// A token that uniquely identifies one run of a Node in the Graph. Each run of a Node (via
/// `N::Context::spawn`) has a different RunToken associated with it. When a run completes, if
/// the current RunToken of its Node no longer matches the RunToken of the spawned work (because
/// the Node was `cleared`), the work is discarded. See `Entry::complete` for more information.
///
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct RunToken(u32);

impl RunToken {
  fn initial() -> RunToken {
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
pub(crate) struct Generation(u32);

impl Generation {
  fn initial() -> Generation {
    Generation(0)
  }

  fn next(self) -> Generation {
    Generation(self.0 + 1)
  }
}

#[cfg_attr(feature = "cargo-clippy", allow(type_complexity))]
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
    previous_result: Option<Result<N::Item, N::Error>>,
  },
  // A node that is running. A running node that has been marked dirty re-runs rather than
  // completing.
  //
  // The `previous_result` value for a Running node is not a valid value. See NotStarted.
  Running {
    run_token: RunToken,
    generation: Generation,
    start_time: Instant,
    waiters: Vec<oneshot::Sender<Result<(N::Item, Generation), N::Error>>>,
    previous_result: Option<Result<N::Item, N::Error>>,
    dirty: bool,
  },
  // A node that has completed, and then possibly been marked dirty. Because marking a node
  // dirty does not eagerly re-execute any logic, it will stay this way until a caller moves it
  // back to Running.
  Completed {
    run_token: RunToken,
    generation: Generation,
    result: Result<N::Item, N::Error>,
    dep_generations: Vec<Generation>,
    dirty: bool,
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
/// Because there are guaranteed to be more edges than nodes in Graphs, we mark cyclic
/// dependencies via a wrapper around the Node (rather than adding a byte to every
/// valid edge).
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub(crate) enum EntryKey<N: Node> {
  Valid(N),
  Cyclic(N),
}

impl<N: Node> EntryKey<N> {
  pub(crate) fn content(&self) -> &N {
    match self {
      &EntryKey::Valid(ref v) => v,
      &EntryKey::Cyclic(ref v) => v,
    }
  }
}

///
/// An Entry and its adjacencies.
///
#[derive(Clone)]
pub struct Entry<N: Node> {
  // TODO: This is a clone of the Node, which is also kept in the `nodes` map. It would be
  // nice to avoid keeping two copies of each Node, but tracking references between the two
  // maps is painful.
  node: EntryKey<N>,

  state: Arc<Mutex<EntryState<N>>>,
}

impl<N: Node> Entry<N> {
  ///
  /// Creates an Entry without starting it. This indirection exists because we cannot know
  /// the EntryId of an Entry until after it is stored in the Graph, and we need the EntryId
  /// in order to run the Entry.
  ///
  pub(crate) fn new(node: EntryKey<N>) -> Entry<N> {
    Entry {
      node: node,
      state: Arc::new(Mutex::new(EntryState::initial())),
    }
  }

  pub fn node(&self) -> &N {
    self.node.content()
  }

  ///
  /// If the Future for this Node has already completed, returns a clone of its result.
  ///
  pub fn peek(&self) -> Option<Result<N::Item, N::Error>> {
    let state = self.state.lock();
    match *state {
      EntryState::Completed {
        ref result, dirty, ..
      }
        if !dirty =>
      {
        Some(result.clone())
      }
      _ => None,
    }
  }

  ///
  /// Spawn the execution of the node on an Executor, which will cause it to execute outside of
  /// the Graph lock and call back into the graph lock to set the final value.
  ///
  pub(crate) fn run<C>(
    context_factory: &C,
    entry_key: &EntryKey<N>,
    entry_id: EntryId,
    run_token: RunToken,
    generation: Generation,
    previous_dep_generations: Option<Vec<Generation>>,
    previous_result: Option<Result<N::Item, N::Error>>,
  ) -> EntryState<N>
  where
    C: NodeContext<Node = N>,
  {
    // Increment the RunToken to uniquely identify this work.
    let run_token = run_token.next();
    match entry_key {
      &EntryKey::Valid(ref n) => {
        let context = context_factory.clone_for(entry_id);
        let node = n.clone();

        context_factory.spawn(future::lazy(move || {
          // If we have previous result generations, compare them to all current dependency
          // generations (which, if they are dirty, will cause recursive cleaning). If they
          // match, we can consider the previous result value to be clean for reuse.
          let was_clean = if let Some(previous_dep_generations) = previous_dep_generations {
            let context2 = context.clone();
            context
              .graph()
              .dep_generations(entry_id, &context)
              .then(move |generation_res| match generation_res {
                Ok(ref dep_generations) if dep_generations == &previous_dep_generations => {
                  // Dependencies have not changed: Node is clean.
                  Ok(true)
                }
                _ => {
                  // If dependency generations mismatched or failed to fetch, clear its
                  // dependencies and indicate that it should re-run.
                  context2.graph().clear_deps(entry_id, run_token);
                  Ok(false)
                }
              }).to_boxed()
          } else {
            future::ok(false).to_boxed()
          };

          // If the Node was clean, complete it. Otherwise, re-run.
          was_clean.and_then(move |was_clean| {
            if was_clean {
              // No dependencies have changed: we can complete the Node without changing its
              // previous_result or generation.
              context
                .graph()
                .complete(&context, entry_id, run_token, None);
              future::ok(()).to_boxed()
            } else {
              // The Node needs to (re-)run!
              let context2 = context.clone();
              node
                .run(context)
                .then(move |res| {
                  context2
                    .graph()
                    .complete(&context2, entry_id, run_token, Some(res));
                  Ok(())
                }).to_boxed()
            }
          })
        }));

        EntryState::Running {
          waiters: Vec::new(),
          start_time: Instant::now(),
          run_token,
          generation,
          previous_result,
          dirty: false,
        }
      }
      &EntryKey::Cyclic(_) => EntryState::Completed {
        result: Err(N::Error::cyclic()),
        dep_generations: Vec::new(),
        run_token,
        generation,
        dirty: false,
      },
    }
  }

  ///
  /// Returns a Future for the Node's value and Generation.
  ///
  /// The two separate state matches handle two cases: in the first case we simply want to mutate
  /// or clone the state, so we take it by reference without swapping it. In the second case, we
  /// need to consume the state (which avoids cloning some of the values held there), so we take it
  /// by value.
  ///
  pub(crate) fn get<C>(
    &mut self,
    context: &C,
    entry_id: EntryId,
  ) -> BoxFuture<(N::Item, Generation), N::Error>
  where
    C: NodeContext<Node = N>,
  {
    {
      let mut state = self.state.lock();

      // First check whether the Node is already complete, or is currently running: in both of these
      // cases we don't swap the state of the Node.
      match &mut *state {
        &mut EntryState::Running {
          ref mut waiters, ..
        } => {
          let (send, recv) = oneshot::channel();
          waiters.push(send);
          return recv
            .map_err(|_| N::Error::invalidated())
            .flatten()
            .to_boxed();
        }
        &mut EntryState::Completed {
          ref result,
          generation,
          dirty,
          ..
        }
          if !dirty =>
        {
          return future::result(result.clone())
            .map(move |res| (res, generation))
            .to_boxed();
        }
        _ => {
          // Fall through to the second match.
        }
      };

      // Otherwise, we'll need to swap the state of the Node, so take it by value.
      let next_state = match mem::replace(&mut *state, EntryState::initial()) {
        EntryState::NotStarted {
          run_token,
          generation,
          previous_result,
        } => Self::run(
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
          dirty,
        } => {
          assert!(
            dirty,
            "A clean Node should not reach this point: {:?}",
            result
          );
          // The Node has already completed but is now marked dirty. This indicates that we are the
          // first caller to request it since it was marked dirty. We attempt to clean it (which will
          // cause it to re-run if the dep_generations mismatch).
          Self::run(
            context,
            &self.node,
            entry_id,
            run_token,
            generation,
            Some(dep_generations),
            Some(result),
          )
        }
        EntryState::Running { .. } => {
          panic!("A Running Node should not reach this point.");
        }
      };

      // Swap in the new state and then recurse.
      *state = next_state;
    }
    self.get(context, entry_id)
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
  pub(crate) fn complete<C>(
    &mut self,
    context: &C,
    entry_id: EntryId,
    result_run_token: RunToken,
    dep_generations: Vec<Generation>,
    result: Option<Result<N::Item, N::Error>>,
    _graph: &mut super::InnerGraph<N>,
  ) where
    C: NodeContext<Node = N>,
  {
    let mut state = self.state.lock();

    // We care about exactly one case: a Running state with the same run_token. All other states
    // represent various (legal) race conditions. See `RunToken`'s docs for more information.
    match *state {
      EntryState::Running { run_token, .. } if result_run_token == run_token => {}
      _ => {
        // We care about exactly one case: a Running state with the same run_token. All other states
        // represent various (legal) race conditions.
        return;
      }
    }

    *state = match mem::replace(&mut *state, EntryState::initial()) {
      EntryState::Running {
        waiters,
        run_token,
        generation,
        previous_result,
        dirty,
        ..
      } => {
        if result == Some(Err(N::Error::invalidated())) {
          // Because it is always ephemeral, invalidation is the only type of Err that we do not
          // persist in the Graph. Instead, swap the Node to NotStarted to drop all waiters,
          // causing them to also experience invalidation (transitively).
          EntryState::NotStarted {
            run_token: run_token.next(),
            generation,
            previous_result,
          }
        } else if dirty {
          // The node was dirtied while it was running. The dep_generations and new result cannot
          // be trusted and were never published. We continue to use the previous result.
          Self::run(
            context,
            &self.node,
            entry_id,
            run_token,
            generation,
            None,
            previous_result,
          )
        } else {
          // If the new result does not match the previous result, the generation increments.
          let (generation, next_result) = if let Some(result) = result {
            if Some(&result) == previous_result.as_ref() {
              // Node was re-executed, but had the same result value.
              (generation, result)
            } else {
              (generation.next(), result)
            }
          } else {
            // Node was marked clean.
            // NB: The `expect` here avoids a clone and a comparison: see the method docs.
            (
              generation,
              previous_result.expect("A Node cannot be marked clean without a previous result."),
            )
          };
          // Notify all waiters (ignoring any that have gone away), and then store the value.
          // A waiter will go away whenever they drop the `Future` `Receiver` of the value, perhaps
          // due to failure of another Future in a `join` or `join_all`, or due to a timeout at the
          // root of a request.
          for waiter in waiters {
            let _ = waiter.send(next_result.clone().map(|res| (res, generation)));
          }
          EntryState::Completed {
            result: next_result,
            dep_generations,
            run_token,
            generation,
            dirty: false,
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
  /// If the Node has started and has not yet completed, returns its runtime.
  ///
  pub(crate) fn current_running_duration(&self, now: Instant) -> Option<Duration> {
    match *self.state.lock() {
      EntryState::Running { start_time, .. } => Some(now.duration_since(start_time)),
      _ => None,
    }
  }

  ///
  /// Clears the state of this Node, forcing it to be recomputed.
  ///
  pub(crate) fn clear(&mut self) {
    let mut state = self.state.lock();

    let (run_token, generation, previous_result) =
      match mem::replace(&mut *state, EntryState::initial()) {
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
        } => (run_token, generation, previous_result),
        EntryState::Completed {
          run_token,
          generation,
          result,
          ..
        } => (run_token, generation, Some(result)),
      };

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
    match &mut *self.state.lock() {
      &mut EntryState::Running { ref mut dirty, .. }
      | &mut EntryState::Completed { ref mut dirty, .. } => {
        // Mark dirty.
        *dirty = true;
      }
      &mut EntryState::NotStarted { .. } => {}
    }
  }

  pub(crate) fn format(&self) -> String {
    let state = match self.peek() {
      Some(Ok(ref nr)) => format!("{:?}", nr),
      Some(Err(ref x)) => format!("{:?}", x),
      None => "<None>".to_string(),
    };
    format!("{} == {}", self.node.content().format(), state).replace("\"", "\\\"")
  }
}
