// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::cmp;
use std::collections::{HashMap, HashSet};
use std::hash::{Hash, Hasher};
use std::sync::atomic::{self, AtomicUsize};
use std::sync::{mpsc, Arc};
use std::thread;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use futures::future;
use parking_lot::Mutex;
use rand::{self, Rng};
use task_executor::Executor;
use tokio::time::{error::Elapsed, sleep, timeout};

use crate::context::Context;
use crate::{Graph, InvalidationResult, Node, NodeError};

fn empty_graph() -> Arc<Graph<TNode>> {
  Arc::new(Graph::new(Executor::new()))
}

macro_rules! assert_atomic_usize_eq {
  ($actual: expr, $expected: expr) => {{
    assert_eq!($actual.load(atomic::Ordering::SeqCst), $expected);
  }};
}

#[tokio::test]
async fn create() {
  let graph = empty_graph();
  let context = graph.context(TContext::new());
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
}

#[tokio::test]
async fn invalidate_and_clean() {
  let graph = empty_graph();
  let context = graph.context(TContext::new());

  // Create three nodes.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(
    context.runs(),
    vec![TNode::new(2), TNode::new(1), TNode::new(0)]
  );

  // Clear the middle Node, which dirties the upper node.
  assert_eq!(
    graph.invalidate_from_roots(true, |n| n.id == 1),
    InvalidationResult {
      cleared: 1,
      dirtied: 1
    }
  );

  // Confirm that the cleared Node re-runs, and the upper node is cleaned without re-running.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(
    context.runs(),
    vec![TNode::new(2), TNode::new(1), TNode::new(0), TNode::new(1)]
  );
}

#[tokio::test]
async fn invalidate_and_rerun() {
  let graph = empty_graph();
  let context = graph.context(TContext::new());

  // Create three nodes.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(
    context.runs(),
    vec![TNode::new(2), TNode::new(1), TNode::new(0)]
  );

  // Clear the middle Node, which dirties the upper node.
  assert_eq!(
    graph.invalidate_from_roots(true, |n| n.id == 1),
    InvalidationResult {
      cleared: 1,
      dirtied: 1
    }
  );

  // Request with a different salt, which will cause both the middle and upper nodes to rerun since
  // their input values have changed.
  let context = graph.context(TContext::new().with_salt(1));
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 1), T(2, 1)])
  );
  assert_eq!(context.runs(), vec![TNode::new(1), TNode::new(2)]);
}

#[tokio::test]
async fn invalidate_uncacheable() {
  let graph = empty_graph();

  // Create three nodes, with the middle node as uncacheable.
  let context = {
    let mut uncacheable = HashSet::new();
    uncacheable.insert(TNode::new(1));
    graph.context(TContext::new().with_uncacheable(uncacheable))
  };
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(
    context.runs(),
    vec![TNode::new(2), TNode::new(1), TNode::new(0)]
  );

  // Clear the bottom Node, which dirties the middle and upper node.
  assert_eq!(
    graph.invalidate_from_roots(true, |n| n.id == 0),
    InvalidationResult {
      cleared: 1,
      dirtied: 2
    }
  );

  // Re-request in the same session with new salt, and validate that all three re-run.
  let context = graph.context((*context).clone().with_salt(1));
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 1), T(1, 1), T(2, 1)])
  );
  assert_eq!(
    context.runs(),
    vec![
      TNode::new(2),
      TNode::new(1),
      TNode::new(0),
      TNode::new(1),
      TNode::new(0),
      TNode::new(2)
    ]
  );
}

#[tokio::test]
async fn invalidate_with_changed_dependencies() {
  let graph = empty_graph();
  let context = graph.context(TContext::new());

  // Create three nodes.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );

  // Clear the middle Node, which dirties the upper node.
  assert_eq!(
    graph.invalidate_from_roots(true, |n| n.id == 1),
    InvalidationResult {
      cleared: 1,
      dirtied: 1
    }
  );

  // Request with a new context that truncates execution at the middle Node.
  let context = graph.context(
    TContext::new().with_dependencies(vec![(TNode::new(1), vec![])].into_iter().collect()),
  );
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(1, 0), T(2, 0)])
  );

  // Confirm that dirtying the bottom Node does not affect the middle/upper Nodes, which no
  // longer depend on it.
  assert_eq!(
    graph.invalidate_from_roots(true, |n| n.id == 0),
    InvalidationResult {
      cleared: 1,
      dirtied: 0,
    }
  );
}

// Historically flaky: https://github.com/pantsbuild/pants/issues/10839
#[tokio::test]
async fn invalidate_randomly() {
  let graph = empty_graph();

  let invalidations = 10;
  let sleep_per_invalidation = Duration::from_millis(100);
  let range = 100;

  // Spawn a background thread to randomly invalidate in the relevant range. Hold its handle so
  // it doesn't detach.
  let graph2 = graph.clone();
  let (send, recv) = mpsc::channel();
  let _join = thread::spawn(move || {
    let mut rng = rand::thread_rng();
    let mut invalidations = invalidations;
    while invalidations > 0 {
      invalidations -= 1;

      // Invalidate a random node in the graph.
      let candidate = rng.gen_range(0..range);
      graph2.invalidate_from_roots(true, |n: &TNode| n.id == candidate);

      thread::sleep(sleep_per_invalidation);
    }
    send.send(()).unwrap();
  });

  // Continuously re-request the root with increasing context values, and assert that Node and
  // context values are ascending.
  let mut iterations = 0;
  let mut max_distinct_context_values = 0;
  loop {
    let context = graph.context(TContext::new().with_salt(iterations));

    // Compute the root, and validate its output.
    let node_output = match graph.create(TNode::new(range), &context).await {
      Ok(output) => output,
      Err(TError::Invalidated) => {
        // Some amount of concurrent invalidation is expected: retry.
        continue;
      }
      Err(e) => panic!("Did not expect any errors other than Invalidation. Got: {e:?}"),
    };
    max_distinct_context_values = cmp::max(
      max_distinct_context_values,
      TNode::validate(&node_output).unwrap(),
    );

    // Poll the channel to see whether the background thread has exited.
    if recv.try_recv().is_ok() {
      break;
    }
    iterations += 1;
  }

  assert!(
    max_distinct_context_values > 1,
    "In {iterations} iterations, observed a maximum of {max_distinct_context_values} distinct context values."
  );
}

#[tokio::test]
async fn poll_cacheable() {
  let _logger = env_logger::try_init();
  let graph = empty_graph();
  let context = graph.context(TContext::new());

  // Poll with an empty graph should succeed.
  let (result, token1) = graph.poll(TNode::new(2), None, None, &context).await;
  assert_eq!(result.unwrap(), vec![T(0, 0), T(1, 0), T(2, 0)]);

  // Re-polling on a non-empty graph but with no LastObserved token should return immediately with
  // the same value, and the same token.
  let (result, token2) = graph.poll(TNode::new(2), None, None, &context).await;
  assert_eq!(result.unwrap(), vec![T(0, 0), T(1, 0), T(2, 0)]);
  assert_eq!(token1, token2);

  // But polling with the previous token should wait, since nothing has changed.
  let request = graph.poll(TNode::new(2), Some(token2), None, &context);
  match timeout(Duration::from_millis(1000), request).await {
    Err(Elapsed { .. }) => (),
    e => panic!("Should have timed out, instead got: {e:?}"),
  }

  // Invalidating something and re-polling should re-compute.
  graph.invalidate_from_roots(true, |n| n.id == 0);
  let result = graph
    .poll(TNode::new(2), Some(token2), None, &context)
    .await
    .0
    .unwrap();
  assert_eq!(result, vec![T(0, 0), T(1, 0), T(2, 0)]);
}

#[tokio::test]
async fn poll_uncacheable() {
  let _logger = env_logger::try_init();
  let graph = empty_graph();
  // Create a context where the middle node is uncacheable.
  let context = {
    let mut uncacheable = HashSet::new();
    uncacheable.insert(TNode::new(1));
    graph.context(TContext::new().with_uncacheable(uncacheable))
  };

  // Poll with an empty graph should succeed.
  let (result, token1) = graph.poll(TNode::new(2), None, None, &context).await;
  assert_eq!(result.unwrap(), vec![T(0, 0), T(1, 0), T(2, 0)]);

  // Polling with the previous token (in the same session) should wait, since nothing has changed.
  let request = graph.poll(TNode::new(2), Some(token1), None, &context);
  match timeout(Duration::from_millis(1000), request).await {
    Err(Elapsed { .. }) => (),
    e => panic!("Should have timed out, instead got: {e:?}"),
  }

  // Invalidating something and re-polling should re-compute.
  graph.invalidate_from_roots(true, |n| n.id == 0);
  let result = graph
    .poll(TNode::new(2), Some(token1), None, &context)
    .await
    .0
    .unwrap();
  assert_eq!(result, vec![T(0, 0), T(1, 0), T(2, 0)]);
}

#[tokio::test]
async fn poll_errored() {
  let _logger = env_logger::try_init();
  let graph = empty_graph();
  let context =
    graph.context(TContext::new().with_errors(vec![TNode::new(0)].into_iter().collect()));

  // Poll should error.
  let (result, token1) = graph.poll(TNode::new(2), None, None, &context).await;
  assert_eq!(result.err().unwrap(), TError::Error);

  // Polling with the previous token should wait, since nothing has changed.
  let request = graph.poll(TNode::new(2), Some(token1), None, &context);
  match timeout(Duration::from_millis(1000), request).await {
    Err(Elapsed { .. }) => (),
    e => panic!("Should have timed out, instead got: {e:?}"),
  }
}

#[tokio::test]
async fn uncacheable_dependents_of_uncacheable_node() {
  let graph = empty_graph();

  // Create a context for which the bottommost Node is not cacheable.
  let context = {
    let mut uncacheable = HashSet::new();
    uncacheable.insert(TNode::new(0));
    graph.context(TContext::new().with_uncacheable(uncacheable))
  };

  // Create three nodes.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(
    context.runs(),
    vec![TNode::new(2), TNode::new(1), TNode::new(0)]
  );

  // Re-request the root in a new session and confirm that only the bottom node re-runs.
  let context = graph.context(TContext::new());
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(context.runs(), vec![TNode::new(0)]);

  // Re-request with a new session and different salt, and confirm that everything re-runs bottom
  // up (the order of node cleaning).
  let context = graph.context(TContext::new().with_salt(1));
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 1), T(1, 1), T(2, 1)])
  );
  assert_eq!(
    context.runs(),
    vec![TNode::new(0), TNode::new(1), TNode::new(2)]
  );
}

#[tokio::test]
async fn non_restartable_node_only_runs_once() {
  let _logger = env_logger::try_init();
  let graph = empty_graph();

  let context = {
    let mut non_restartable = HashSet::new();
    non_restartable.insert(TNode::new(1));
    let sleep_root = Duration::from_millis(1000);
    let mut delays = HashMap::new();
    delays.insert(TNode::new(0), sleep_root);
    graph.context(
      TContext::new()
        .with_non_restartable(non_restartable)
        .with_delays_pre(delays),
    )
  };

  let graph2 = graph.clone();
  let (send, recv) = mpsc::channel::<()>();
  let _join = thread::spawn(move || {
    recv.recv_timeout(Duration::from_secs(10)).unwrap();
    thread::sleep(Duration::from_millis(50));
    graph2.invalidate_from_roots(true, |n| n.id == 0);
  });

  send.send(()).unwrap();
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  // TNode(0) is cleared before completing, and so will run twice. But the non_restartable node and its
  // dependent each run once.
  assert_eq!(
    context.runs(),
    vec![TNode::new(2), TNode::new(1), TNode::new(0), TNode::new(0),]
  );
}

#[tokio::test]
async fn uncacheable_deps_is_cleaned_for_the_session() {
  let _logger = env_logger::try_init();
  let graph = empty_graph();

  let context = {
    let mut uncacheable = HashSet::new();
    uncacheable.insert(TNode::new(1));
    graph.context(TContext::new().with_uncacheable(uncacheable))
  };

  // Request twice in a row in the same session, and confirm that nothing re-runs or is cleaned
  // on the second attempt.
  let assert_no_change_within_session = |context: &Context<TNode>| {
    assert_eq!(
      context.runs(),
      vec![TNode::new(2), TNode::new(1), TNode::new(0)]
    );
    assert_atomic_usize_eq!(context.stats().cleaning_succeeded, 0);
    assert_atomic_usize_eq!(context.stats().cleaning_failed, 0);
  };

  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_no_change_within_session(&context);

  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_no_change_within_session(&context);
}

#[tokio::test]
async fn dirtied_uncacheable_deps_node_re_runs() {
  let _logger = env_logger::try_init();
  let graph = empty_graph();

  let mut uncacheable = HashSet::new();
  uncacheable.insert(TNode::new(0));

  let context = graph.context(TContext::new().with_uncacheable(uncacheable.clone()));

  // Request two nodes above an uncacheable node.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(
    context.runs(),
    vec![TNode::new(2), TNode::new(1), TNode::new(0)]
  );
  assert_atomic_usize_eq!(context.stats().cleaning_succeeded, 0);
  assert_atomic_usize_eq!(context.stats().cleaning_failed, 0);
  assert_atomic_usize_eq!(context.stats().ran, 3);

  let assert_stable_after_cleaning = |context: &Context<TNode>| {
    assert_eq!(
      context.runs(),
      vec![TNode::new(2), TNode::new(1), TNode::new(0), TNode::new(1)]
    );
    assert_atomic_usize_eq!(context.stats().cleaning_failed, 0);
    assert_atomic_usize_eq!(context.stats().ran, 4);
    assert_atomic_usize_eq!(context.stats().cleaning_succeeded, 1);
  };

  // Clear the middle node, which will dirty the top node, and then clean both of them.
  graph.invalidate_from_roots(true, |n| n.id == 1);
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_stable_after_cleaning(&context);

  // We expect that the two upper nodes went to the UncacheableDependencies state for the session:
  // re-requesting should be a noop.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_stable_after_cleaning(&context);

  // Finally, confirm that in a new session/run the UncacheableDependencies nodes trigger detection
  // of the Uncacheable node (which runs), and are then cleaned themselves.
  let context = graph.context(TContext::new().with_uncacheable(uncacheable));
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(context.runs(), vec![TNode::new(0)]);
  assert_atomic_usize_eq!(context.stats().cleaning_succeeded, 2);
  assert_atomic_usize_eq!(context.stats().cleaning_failed, 0);
}

#[tokio::test]
async fn retries() {
  let _logger = env_logger::try_init();
  let graph = empty_graph();

  let context = {
    let sleep_root = Duration::from_millis(100);
    let mut delays = HashMap::new();
    delays.insert(TNode::new(0), sleep_root);
    graph.context(TContext::new().with_delays_pre(delays))
  };

  // Spawn a thread that will invalidate in a loop for one second (much less than our timeout).
  let sleep_per_invalidation = Duration::from_millis(10);
  let invalidation_deadline = Instant::now() + Duration::from_secs(1);
  let graph2 = graph.clone();
  let join_handle = thread::spawn(move || loop {
    thread::sleep(sleep_per_invalidation);
    graph2.invalidate_from_roots(true, |n| n.id == 0);
    if Instant::now() > invalidation_deadline {
      break;
    }
  });

  // Should succeed anyway.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  join_handle.join().unwrap();
}

#[tokio::test]
async fn eager_cleaning_success() {
  // Test that invalidation does not cause a Running node to restart if the dependencies that it
  // has already requested can successfully be cleaned.
  let _logger = env_logger::try_init();
  let invalidation_delay = Duration::from_millis(100);
  let graph = Arc::new(Graph::<TNode>::new_with_invalidation_delay(
    Executor::new(),
    invalidation_delay,
  ));

  let sleep_middle = Duration::from_millis(2000);
  let context = {
    let mut delays = HashMap::new();
    delays.insert(TNode::new(1), sleep_middle);
    graph.context(TContext::new().with_delays_pre(delays))
  };

  // Invalidate the bottom Node (after the middle node has already requested it).
  assert!(sleep_middle > invalidation_delay * 3);
  let graph2 = graph.clone();
  let _join = thread::spawn(move || {
    thread::sleep(invalidation_delay);
    graph2.invalidate_from_roots(true, |n| n.id == 0);
  });
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );

  // No nodes should have seen aborts, since the dirtied nodes had already completed, and the
  // running node should not have been interrupted.
  assert!(context.aborts().is_empty(), "{:?}", context.aborts());
}

#[tokio::test]
async fn eager_cleaning_failure() {
  // Test that invalidation causes a Running node to restart if the dependencies that it
  // has already requested end up with new values before it completes.
  let _logger = env_logger::try_init();
  let invalidation_delay = Duration::from_millis(100);
  let sleep_middle = Duration::from_millis(2000);
  let graph = Arc::new(Graph::new_with_invalidation_delay(
    Executor::new(),
    invalidation_delay,
  ));

  let context = {
    let mut delays = HashMap::new();
    delays.insert(TNode::new(1), sleep_middle);
    graph.context(TContext::new().with_delays_post(delays))
  };

  // Invalidate the bottom Node with a new salt (after the middle node has already requested it).
  assert!(sleep_middle > invalidation_delay * 3);
  let graph2 = graph.clone();
  let context2 = Context::<TNode>::clone(&context);
  let _join = thread::spawn(move || {
    thread::sleep(invalidation_delay);
    context2.set_salt(1);
    graph2.invalidate_from_roots(true, |n| n.id == 0);
  });
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 1), T(1, 1), T(2, 0)])
  );

  // The middle node should have seen an abort, since it already observed its dependency, and that
  // dependency could not be cleaned. But the top Node will not abort, because it will not yet have
  // received a value for its dependency, and so will be successfully cleaned.
  assert_eq!(vec![TNode::new(1)], context.aborts());
}

#[tokio::test]
async fn canceled_on_loss_of_interest() {
  let _logger = env_logger::try_init();
  let graph = empty_graph();

  let sleep_middle = Duration::from_millis(2000);
  let start_time = Instant::now();
  let context = {
    let mut delays = HashMap::new();
    delays.insert(TNode::new(1), sleep_middle);
    graph.context(TContext::new().with_delays_pre(delays))
  };

  // Start a run, but cancel it well before the delayed middle node can complete.
  tokio::select! {
    _ = sleep(Duration::from_millis(100)) => {},
    _ = graph.create(TNode::new(2), &context) => { panic!("Should have timed out.") }
  }

  // Then start again, and allow to run to completion.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );

  // We should have waited more than the delay, but less than the time it would have taken to
  // run twice.
  assert!(Instant::now() >= start_time + sleep_middle);
  assert!(Instant::now() < start_time + (sleep_middle * 2));

  // And the top nodes should have seen one abort each.
  assert_eq!(vec![TNode::new(2), TNode::new(1),], context.aborts(),);
}

#[tokio::test]
async fn clean_speculatively() {
  let _logger = env_logger::try_init();
  let graph = empty_graph();

  // Create a graph with a node with two dependencies, one of which takes much longer
  // to run.
  let mut dependencies = vec![
    (TNode::new(3), vec![TNode::new(2), TNode::new(1)]),
    (TNode::new(2), vec![TNode::new(0)]),
    (TNode::new(1), vec![TNode::new(0)]),
  ]
  .into_iter()
  .collect::<HashMap<_, _>>();
  let delay = Duration::from_millis(2000);
  let context = {
    let mut delays = HashMap::new();
    delays.insert(TNode::new(2), delay);
    graph.context(
      TContext::new()
        .with_delays_pre(delays)
        .with_dependencies(dependencies.clone()),
    )
  };

  // Run it to completion, and then clear a node at the bottom of the graph to force cleaning of
  // both dependencies.
  assert_eq!(
    graph.create(TNode::new(3), &context).await,
    Ok(vec![T(0, 0), T(2, 0), T(3, 0)])
  );
  graph.invalidate_from_roots(true, |n| n == &TNode::new(0));

  // Then request again with the slow node removed from the dependencies, and confirm that it is
  // cleaned much sooner than it would been if it had waited for the slow node.
  dependencies.insert(TNode::new(3), vec![TNode::new(1)]);
  let context = graph.context(
    (*context)
      .clone()
      .with_salt(1)
      .with_dependencies(dependencies),
  );
  let start_time = Instant::now();
  assert_eq!(
    graph.create(TNode::new(3), &context).await,
    Ok(vec![T(0, 1), T(1, 1), T(3, 1)])
  );
  assert!(Instant::now() < start_time + delay);
  assert_atomic_usize_eq!(context.stats().cleaning_failed, 3);
}

#[tokio::test]
async fn cyclic_failure() {
  // Confirms that an attempt to create a cycle fails.
  let graph = empty_graph();
  let top = TNode::new(2);
  let context = graph.context(TContext::new().with_dependencies(
    // Request creation of a cycle by sending the bottom most node to the top.
    vec![(TNode::new(0), vec![top])].into_iter().collect(),
  ));

  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Err(TError::Cyclic(vec![0, 2, 1]))
  );
}

#[tokio::test]
async fn cyclic_dirtying() {
  let _logger = env_logger::try_init();
  // Confirms that a dirtied path between two nodes is able to reverse direction while being
  // cleaned.
  let graph = empty_graph();
  let initial_top = TNode::new(2);
  let initial_bot = TNode::new(0);

  // Request with a context that creates a path downward.
  let context_down = graph.context(TContext::new());
  assert_eq!(
    graph.create(initial_top.clone(), &context_down).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );

  // Clear the bottom node, and then clean it with a context that causes the path to reverse.
  graph.invalidate_from_roots(true, |n| n == &initial_bot);
  let context_up = graph.context(
    (*context_down).clone().with_salt(1).with_dependencies(
      // Reverse the path from bottom to top.
      vec![
        (TNode::new(1), vec![]),
        (TNode::new(0), vec![TNode::new(1)]),
      ]
      .into_iter()
      .collect(),
    ),
  );

  let res = graph.create(initial_bot, &context_up).await;

  assert_eq!(res, Ok(vec![T(1, 1), T(0, 1)]));

  let res = graph.create(initial_top, &context_up).await;

  assert_eq!(res, Ok(vec![T(1, 1), T(2, 1)]));
}

///
/// A token containing the id of a Node and the id of a Context, respectively. Has a short name
/// to minimize the verbosity of tests.
///
#[derive(Clone, Debug, Eq, PartialEq)]
struct T(usize, usize);

///
/// A node that builds a Vec of tokens by recursively requesting itself and appending its value
/// to the result.
///
#[derive(Clone, Debug)]
struct TNode {
  pub id: usize,
  restartable: bool,
  cacheable: bool,
}
impl TNode {
  fn new(id: usize) -> Self {
    TNode {
      id,
      restartable: true,
      cacheable: true,
    }
  }
}
impl PartialEq for TNode {
  fn eq(&self, other: &Self) -> bool {
    self.id == other.id
  }
}
impl Eq for TNode {}
impl Hash for TNode {
  fn hash<H: Hasher>(&self, state: &mut H) {
    self.id.hash(state);
  }
}
#[async_trait]
impl Node for TNode {
  type Context = TContext;

  type Item = Vec<T>;
  type Error = TError;

  async fn run(self, context: Context<Self>) -> Result<Vec<T>, TError> {
    let mut abort_guard = context.abort_guard(self.clone());
    context.ran(self.clone());
    if context.errors.contains(&self) {
      return Err(TError::Error);
    }
    let token = T(self.id, context.salt());
    context.maybe_delay_pre(&self).await;
    let res = match context.dependencies_of(&self) {
      deps if !deps.is_empty() => {
        // Request all dependencies, but include only the first in our output value.
        let mut values = future::try_join_all(
          deps
            .into_iter()
            .map(|dep| context.get(dep))
            .collect::<Vec<_>>(),
        )
        .await?;
        let mut v = values.swap_remove(0);
        v.push(token);
        Ok(v)
      }
      _ => Ok(vec![token]),
    };
    context.maybe_delay_post(&self).await;
    abort_guard.did_not_abort();
    res
  }

  fn restartable(&self) -> bool {
    self.restartable
  }

  fn cacheable(&self) -> bool {
    self.cacheable
  }

  fn cyclic_error(path: &[&Self]) -> Self::Error {
    TError::Cyclic(path.iter().map(|n| n.id).collect())
  }
}

impl std::fmt::Display for TNode {
  fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
    write!(f, "{self:?}")
  }
}

impl TNode {
  ///
  /// Validates the given TNode output. Both node ids and context ids should increase left to
  /// right: node ids monotonically, and context ids non-monotonically.
  ///
  /// Valid:
  ///   (0,0), (1,1), (2,2), (3,3)
  ///   (0,0), (1,0), (2,1), (3,1)
  ///
  /// Invalid:
  ///   (0,0), (1,1), (2,1), (3,0)
  ///   (0,0), (1,0), (2,0), (1,0)
  ///
  /// If successful, returns the count of distinct context ids in the path.
  ///
  fn validate(output: &Vec<T>) -> Result<usize, String> {
    let (node_ids, context_ids): (Vec<_>, Vec<_>) = output
      .iter()
      .map(|&T(node_id, context_id)| {
        // We cast to isize to allow comparison to -1.
        (node_id as isize, context_id)
      })
      .unzip();
    // Confirm monotonically ordered.
    let mut previous: isize = -1;
    for node_id in node_ids {
      if previous + 1 != node_id {
        return Err(format!(
          "Node ids in {output:?} were not monotonically ordered."
        ));
      }
      previous = node_id;
    }
    // Confirm ordered (non-monotonically).
    let mut previous: usize = 0;
    for &context_id in &context_ids {
      if previous > context_id {
        return Err(format!("Context ids in {output:?} were not ordered."));
      }
      previous = context_id;
    }

    Ok(context_ids.into_iter().collect::<HashSet<_>>().len())
  }
}

///
/// A context that keeps a record of Nodes that have been run.
///
#[derive(Clone)]
struct TContext {
  // A value that is included in every value computed by this context. Stands in for "the state of the
  // outside world". A test that wants to "change the outside world" and observe its effect on the
  // graph should change the salt to do so.
  salt: Arc<AtomicUsize>,
  // A mapping from source to destinations that drives what values each TNode depends on.
  // If there is no entry in this map for a node, then TNode::run will default to requesting
  // the next smallest node.
  edges: Arc<HashMap<TNode, Vec<TNode>>>,
  delays_pre: Arc<HashMap<TNode, Duration>>,
  delays_post: Arc<HashMap<TNode, Duration>>,
  // Nodes which should error when they run.
  errors: Arc<HashSet<TNode>>,
  non_restartable: Arc<HashSet<TNode>>,
  uncacheable: Arc<HashSet<TNode>>,
  aborts: Arc<Mutex<Vec<TNode>>>,
  runs: Arc<Mutex<Vec<TNode>>>,
}

impl TContext {
  fn new() -> TContext {
    TContext {
      salt: Arc::new(AtomicUsize::new(0)),
      edges: Arc::default(),
      delays_pre: Arc::default(),
      delays_post: Arc::default(),
      errors: Arc::default(),
      non_restartable: Arc::default(),
      uncacheable: Arc::default(),
      aborts: Arc::default(),
      runs: Arc::default(),
    }
  }

  fn with_dependencies(mut self, edges: HashMap<TNode, Vec<TNode>>) -> TContext {
    self.edges = Arc::new(edges);
    self
  }

  /// Delays incurred before a node has requested its dependencies.
  fn with_delays_pre(mut self, delays: HashMap<TNode, Duration>) -> TContext {
    self.delays_pre = Arc::new(delays);
    self
  }

  /// Delays incurred after a node has requested its dependencies.
  fn with_delays_post(mut self, delays: HashMap<TNode, Duration>) -> TContext {
    self.delays_post = Arc::new(delays);
    self
  }

  fn with_errors(mut self, errors: HashSet<TNode>) -> TContext {
    self.errors = Arc::new(errors);
    self
  }

  fn with_non_restartable(mut self, non_restartable: HashSet<TNode>) -> TContext {
    self.non_restartable = Arc::new(non_restartable);
    self
  }

  fn with_uncacheable(mut self, uncacheable: HashSet<TNode>) -> TContext {
    self.uncacheable = Arc::new(uncacheable);
    self
  }

  fn with_salt(mut self, salt: usize) -> TContext {
    self.salt = Arc::new(AtomicUsize::new(salt));
    self
  }

  fn salt(&self) -> usize {
    self.salt.load(atomic::Ordering::SeqCst)
  }

  fn set_salt(&self, salt: usize) {
    self.salt.store(salt, atomic::Ordering::SeqCst)
  }

  fn abort_guard(&self, node: TNode) -> AbortGuard {
    AbortGuard {
      context: self.clone(),
      node: Some(node),
    }
  }

  fn aborted(&self, node: TNode) {
    let mut aborts = self.aborts.lock();
    aborts.push(node);
  }

  fn ran(&self, node: TNode) {
    let mut runs = self.runs.lock();
    runs.push(node);
  }

  async fn maybe_delay_pre(&self, node: &TNode) {
    if let Some(delay) = self.delays_pre.get(node) {
      sleep(*delay).await;
    }
  }

  async fn maybe_delay_post(&self, node: &TNode) {
    if let Some(delay) = self.delays_post.get(node) {
      sleep(*delay).await;
    }
  }

  ///
  /// If the given TNode should declare a dependency on another TNode, returns that dependency.
  ///
  fn dependencies_of(&self, node: &TNode) -> Vec<TNode> {
    match self.edges.get(node) {
      Some(deps) => deps.clone(),
      None if node.id > 0 => {
        let new_node_id = node.id - 1;
        vec![TNode {
          id: new_node_id,
          restartable: !self.non_restartable.contains(&TNode::new(new_node_id)),
          cacheable: !self.uncacheable.contains(&TNode::new(new_node_id)),
        }]
      }
      None => vec![],
    }
  }

  fn aborts(&self) -> Vec<TNode> {
    self.aborts.lock().clone()
  }

  fn runs(&self) -> Vec<TNode> {
    self.runs.lock().clone()
  }
}

///
/// A guard that if dropped, records that the given Node was aborted. When a future is canceled, it
/// is dropped without re-running.
///
struct AbortGuard {
  context: TContext,
  node: Option<TNode>,
}

impl AbortGuard {
  fn did_not_abort(&mut self) {
    self.node = None;
  }
}

impl Drop for AbortGuard {
  fn drop(&mut self) {
    if let Some(node) = self.node.take() {
      self.context.aborted(node);
    }
  }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum TError {
  Error,
  Cyclic(Vec<usize>),
  Invalidated,
}
impl NodeError for TError {
  fn invalidated() -> Self {
    TError::Invalidated
  }

  fn generic(_message: String) -> Self {
    TError::Error
  }
}
