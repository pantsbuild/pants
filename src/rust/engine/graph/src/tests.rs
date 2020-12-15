use std::cmp;
use std::collections::{HashMap, HashSet};
use std::future::Future;
use std::hash::{Hash, Hasher};
use std::ops::DerefMut;
use std::sync::{mpsc, Arc};
use std::thread;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use futures::future;
use parking_lot::Mutex;
use rand::{self, Rng};
use tokio::time::{delay_for, timeout, Elapsed};

use crate::{EntryId, Graph, InvalidationResult, Node, NodeContext, NodeError, Stats};

#[tokio::test]
async fn create() {
  let graph = Arc::new(Graph::new());
  let context = TContext::new(graph.clone());
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
}

#[tokio::test]
async fn invalidate_and_clean() {
  let graph = Arc::new(Graph::new());
  let context = TContext::new(graph.clone());

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
    graph.invalidate_from_roots(|&TNode(n, _)| n == 1),
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
  let graph = Arc::new(Graph::new());
  let context = TContext::new(graph.clone());

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
    graph.invalidate_from_roots(|&TNode(n, _)| n == 1),
    InvalidationResult {
      cleared: 1,
      dirtied: 1
    }
  );

  // Request with a different salt, which will cause both the middle and upper nodes to rerun since
  // their input values have changed.
  let context = context.new_run(1).with_salt(1);
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 1), T(2, 1)])
  );
  assert_eq!(context.runs(), vec![TNode::new(1), TNode::new(2)]);
}

#[tokio::test]
async fn invalidate_with_changed_dependencies() {
  let graph = Arc::new(Graph::new());
  let context = TContext::new(graph.clone());

  // Create three nodes.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );

  // Clear the middle Node, which dirties the upper node.
  assert_eq!(
    graph.invalidate_from_roots(|&TNode(n, _)| n == 1),
    InvalidationResult {
      cleared: 1,
      dirtied: 1
    }
  );

  // Request with a new context that truncates execution at the middle Node.
  let context = TContext::new(graph.clone())
    .with_dependencies(vec![(TNode::new(1), vec![])].into_iter().collect());
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(1, 0), T(2, 0)])
  );

  // Confirm that dirtying the bottom Node does not affect the middle/upper Nodes, which no
  // longer depend on it.
  assert_eq!(
    graph.invalidate_from_roots(|&TNode(n, _)| n == 0),
    InvalidationResult {
      cleared: 1,
      dirtied: 0,
    }
  );
}

#[ignore] // flaky: https://github.com/pantsbuild/pants/issues/10839
#[tokio::test]
async fn invalidate_randomly() {
  let graph = Arc::new(Graph::new());

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
      let candidate = rng.gen_range(0, range);
      graph2.invalidate_from_roots(|&TNode(n, _)| n == candidate);

      thread::sleep(sleep_per_invalidation);
    }
    send.send(()).unwrap();
  });

  // Continuously re-request the root with increasing context values, and assert that Node and
  // context values are ascending.
  let mut iterations = 0;
  let mut max_distinct_context_values = 0;
  loop {
    let context = TContext::new(graph.clone()).with_salt(iterations);

    // Compute the root, and validate its output.
    let node_output = match graph.create(TNode::new(range), &context).await {
      Ok(output) => output,
      Err(TError::Invalidated) => {
        // Some amount of concurrent invalidation is expected: retry.
        continue;
      }
      Err(e) => panic!(
        "Did not expect any errors other than Invalidation. Got: {:?}",
        e
      ),
    };
    max_distinct_context_values = cmp::max(
      max_distinct_context_values,
      TNode::validate(&node_output).unwrap(),
    );

    // Poll the channel to see whether the background thread has exited.
    if let Ok(_) = recv.try_recv() {
      break;
    }
    iterations += 1;
  }

  assert!(
    max_distinct_context_values > 1,
    "In {} iterations, observed a maximum of {} distinct context values.",
    iterations,
    max_distinct_context_values
  );
}

#[tokio::test]
async fn poll_cacheable() {
  let graph = Arc::new(Graph::new());
  let context = TContext::new(graph.clone());

  // Poll with an empty graph should succeed.
  let (result, token1) = graph
    .poll(TNode::new(2), None, None, &context)
    .await
    .unwrap();
  assert_eq!(result, vec![T(0, 0), T(1, 0), T(2, 0)]);

  // Re-polling on a non-empty graph but with no LastObserved token should return immediately with
  // the same value, and the same token.
  let (result, token2) = graph
    .poll(TNode::new(2), None, None, &context)
    .await
    .unwrap();
  assert_eq!(result, vec![T(0, 0), T(1, 0), T(2, 0)]);
  assert_eq!(token1, token2);

  // But polling with the previous token should wait, since nothing has changed.
  let request = graph.poll(TNode::new(2), Some(token2), None, &context);
  match timeout(Duration::from_millis(1000), request).await {
    Err(Elapsed { .. }) => (),
    e => panic!("Should have timed out, instead got: {:?}", e),
  }

  // Invalidating something and re-polling should re-compute.
  graph.invalidate_from_roots(|&TNode(n, _)| n == 0);
  let (result, _) = graph
    .poll(TNode::new(2), Some(token2), None, &context)
    .await
    .unwrap();
  assert_eq!(result, vec![T(0, 0), T(1, 0), T(2, 0)]);
}

#[tokio::test]
async fn poll_uncacheable() {
  let _logger = env_logger::try_init();
  let graph = Arc::new(Graph::new());
  // Create a context where the middle node is uncacheable.
  let context = {
    let mut uncacheable = HashSet::new();
    uncacheable.insert(TNode::new(1));
    TContext::new(graph.clone()).with_uncacheable(uncacheable)
  };

  // Poll with an empty graph should succeed.
  let (result, token1) = graph
    .poll(TNode::new(2), None, None, &context)
    .await
    .unwrap();
  assert_eq!(result, vec![T(0, 0), T(1, 0), T(2, 0)]);

  // Polling with the previous token (in the same session) should wait, since nothing has changed.
  let request = graph.poll(TNode::new(2), Some(token1), None, &context);
  match timeout(Duration::from_millis(1000), request).await {
    Err(Elapsed { .. }) => (),
    e => panic!("Should have timed out, instead got: {:?}", e),
  }

  // Invalidating something and re-polling should re-compute.
  graph.invalidate_from_roots(|&TNode(n, _)| n == 0);
  let (result, _) = graph
    .poll(TNode::new(2), Some(token1), None, &context)
    .await
    .unwrap();
  assert_eq!(result, vec![T(0, 0), T(1, 0), T(2, 0)]);
}

#[tokio::test]
async fn uncacheable_dependents_of_uncacheable_node() {
  let graph = Arc::new(Graph::new());

  // Create a context for which the bottommost Node is not cacheable.
  let context = {
    let mut uncacheable = HashSet::new();
    uncacheable.insert(TNode::new(0));
    TContext::new(graph.clone()).with_uncacheable(uncacheable)
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
  let context = context.new_run(1);
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(context.runs(), vec![TNode::new(0)]);

  // Re-request with a new session and different salt, and confirm that everything re-runs bottom
  // up (the order of node cleaning).
  let context = context.new_run(2).with_salt(1);
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
async fn uncacheable_node_only_runs_once() {
  let _logger = env_logger::try_init();
  let graph = Arc::new(Graph::new());

  let context = {
    let mut uncacheable = HashSet::new();
    uncacheable.insert(TNode::new(1));
    let delay_for_root = Duration::from_millis(1000);
    let mut delays = HashMap::new();
    delays.insert(TNode::new(0), delay_for_root);
    TContext::new(graph.clone())
      .with_uncacheable(uncacheable)
      .with_delays(delays)
  };

  let graph2 = graph.clone();
  let (send, recv) = mpsc::channel::<()>();
  let _join = thread::spawn(move || {
    recv.recv_timeout(Duration::from_secs(10)).unwrap();
    thread::sleep(Duration::from_millis(50));
    graph2.invalidate_from_roots(|&TNode(n, _)| n == 0);
  });

  send.send(()).unwrap();
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  // TNode(0) is cleared before completing, and so will run twice. But the uncacheable node and its
  // dependee each run once.
  assert_eq!(
    context.runs(),
    vec![TNode::new(2), TNode::new(1), TNode::new(0), TNode::new(0),]
  );
}

#[tokio::test]
async fn uncacheable_deps_is_cleaned_for_the_session() {
  let _logger = env_logger::try_init();
  let graph = Arc::new(Graph::new());

  let context = {
    let mut uncacheable = HashSet::new();
    uncacheable.insert(TNode::new(1));
    TContext::new(graph.clone()).with_uncacheable(uncacheable)
  };

  // Request twice in a row in the same session, and confirm that nothing re-runs or is cleaned
  // on the second attempt.
  let assert_no_change_within_session = |context: &TContext| {
    assert_eq!(
      context.runs(),
      vec![TNode::new(2), TNode::new(1), TNode::new(0)]
    );
    assert_eq!(context.stats().cleaning_succeeded, 0);
    assert_eq!(context.stats().cleaning_failed, 0);
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
  let graph = Arc::new(Graph::new());

  let context = {
    let mut uncacheable = HashSet::new();
    uncacheable.insert(TNode::new(0));
    TContext::new(graph.clone()).with_uncacheable(uncacheable)
  };

  // Request two nodes above an uncacheable node.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(
    context.runs(),
    vec![TNode::new(2), TNode::new(1), TNode::new(0)]
  );
  assert_eq!(context.stats().cleaning_succeeded, 0);
  assert_eq!(context.stats().cleaning_failed, 0);

  let assert_stable_after_cleaning = |context: &TContext| {
    assert_eq!(
      context.runs(),
      vec![TNode::new(2), TNode::new(1), TNode::new(0), TNode::new(1)]
    );
    assert_eq!(context.stats().cleaning_succeeded, 1);
    assert_eq!(context.stats().cleaning_failed, 0);
  };

  // Clear the middle node, which will dirty the top node, and then clean both of them.
  graph.invalidate_from_roots(|&TNode(n, _)| n == 1);
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
  let context = context.new_run(1);
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(context.runs(), vec![TNode::new(0)]);
  assert_eq!(context.stats().cleaning_succeeded, 2);
  assert_eq!(context.stats().cleaning_failed, 0);
}

#[tokio::test]
async fn retries() {
  let _logger = env_logger::try_init();
  let graph = Arc::new(Graph::new());

  let context = {
    let delay_for_root = Duration::from_millis(100);
    let mut delays = HashMap::new();
    delays.insert(TNode::new(0), delay_for_root);
    TContext::new(graph.clone()).with_delays(delays)
  };

  // Spawn a thread that will invalidate in a loop for one second (much less than our timeout).
  let sleep_per_invalidation = Duration::from_millis(10);
  let invalidation_deadline = Instant::now() + Duration::from_secs(1);
  let graph2 = graph.clone();
  let join_handle = thread::spawn(move || loop {
    thread::sleep(sleep_per_invalidation);
    graph2.invalidate_from_roots(|&TNode(n, _)| n == 0);
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
async fn canceled_on_invalidation() {
  let _logger = env_logger::try_init();
  let invalidation_delay = Duration::from_millis(10);
  let graph = Arc::new(Graph::new_with_invalidation_delay(invalidation_delay));

  let delay_for_middle = Duration::from_millis(2000);
  let start_time = Instant::now();
  let context = {
    let mut delays = HashMap::new();
    delays.insert(TNode::new(1), delay_for_middle);
    TContext::new(graph.clone()).with_delays(delays)
  };

  // We invalidate three times: the mid should only actually run to completion once, because we
  // should cancel it the other times. We wait longer than the invalidation_delay for each
  // invalidation to ensure that work actually starts before being invalidated.
  let iterations = 3;
  let sleep_per_invalidation = invalidation_delay * 10;
  assert!(delay_for_middle > sleep_per_invalidation * 3);
  let graph2 = graph.clone();
  let _join = thread::spawn(move || {
    for _ in 0..iterations {
      thread::sleep(sleep_per_invalidation);
      graph2.invalidate_from_roots(|&TNode(n, _)| n == 1);
    }
  });
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );

  // We should have waited much less than the time it would have taken to complete three times.
  assert!(Instant::now() < start_time + (delay_for_middle * iterations));

  // And the top nodes should have seen three aborts.
  assert_eq!(
    vec![
      TNode::new(1),
      TNode::new(2),
      TNode::new(1),
      TNode::new(2),
      TNode::new(1),
      TNode::new(2)
    ],
    context.aborts(),
  );
}

#[tokio::test]
async fn canceled_on_loss_of_interest() {
  let _logger = env_logger::try_init();
  let graph = Arc::new(Graph::new());

  let delay_for_middle = Duration::from_millis(2000);
  let start_time = Instant::now();
  let context = {
    let mut delays = HashMap::new();
    delays.insert(TNode::new(1), delay_for_middle);
    TContext::new(graph.clone()).with_delays(delays)
  };

  // Start a run, but cancel it well before the delayed middle node can complete.
  tokio::select! {
    _ = delay_for(Duration::from_millis(100)) => {},
    _ = graph.create(TNode::new(2), &context) => { panic!("Should have timed out.") }
  }

  // Then start again, and allow to run to completion.
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );

  // We should have waited more than the delay, but less than the time it would have taken to
  // run twice.
  assert!(Instant::now() >= start_time + delay_for_middle);
  assert!(Instant::now() < start_time + (delay_for_middle * 2));

  // And the top nodes should have seen one abort each.
  assert_eq!(vec![TNode::new(2), TNode::new(1),], context.aborts(),);
}

#[tokio::test]
async fn clean_speculatively() {
  let _logger = env_logger::try_init();
  let graph = Arc::new(Graph::new());

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
    TContext::new(graph.clone())
      .with_delays(delays)
      .with_dependencies(dependencies.clone())
  };

  // Run it to completion, and then clear a node at the bottom of the graph to force cleaning of
  // both dependencies.
  assert_eq!(
    graph.create(TNode::new(3), &context).await,
    Ok(vec![T(0, 0), T(2, 0), T(3, 0)])
  );
  graph.invalidate_from_roots(|n| n == &TNode::new(0));

  // Then request again with the slow node removed from the dependencies, and confirm that it is
  // cleaned much sooner than it would been if it had waited for the slow node.
  dependencies.insert(TNode::new(3), vec![TNode::new(1)]);
  let context = context.with_salt(1).with_dependencies(dependencies);
  let start_time = Instant::now();
  assert_eq!(
    graph.create(TNode::new(3), &context).await,
    Ok(vec![T(0, 1), T(1, 1), T(3, 1)])
  );
  assert!(Instant::now() < start_time + delay);
  assert_eq!(context.stats().cleaning_failed, 3);
}

#[tokio::test]
async fn cyclic_failure() {
  // Confirms that an attempt to create a cycle fails.
  let graph = Arc::new(Graph::new());
  let top = TNode::new(2);
  let context = TContext::new(graph.clone()).with_dependencies(
    // Request creation of a cycle by sending the bottom most node to the top.
    vec![(TNode::new(0), vec![top])].into_iter().collect(),
  );

  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Err(TError::Cyclic)
  );
}

#[tokio::test]
async fn cyclic_dirtying() {
  // Confirms that a dirtied path between two nodes is able to reverse direction while being
  // cleaned.
  let graph = Arc::new(Graph::new());
  let initial_top = TNode::new(2);
  let initial_bot = TNode::new(0);

  // Request with a context that creates a path downward.
  let context_down = TContext::new(graph.clone());
  assert_eq!(
    graph.create(initial_top.clone(), &context_down).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );

  // Clear the bottom node, and then clean it with a context that causes the path to reverse.
  graph.invalidate_from_roots(|n| n == &initial_bot);
  let context_up = context_down.with_salt(1).with_dependencies(
    // Reverse the path from bottom to top.
    vec![
      (TNode::new(1), vec![]),
      (TNode::new(0), vec![TNode::new(1)]),
    ]
    .into_iter()
    .collect(),
  );

  let res = graph.create(initial_bot, &context_up).await;

  assert_eq!(res, Ok(vec![T(1, 1), T(0, 1)]));

  let res = graph.create(initial_top, &context_up).await;

  assert_eq!(res, Ok(vec![T(1, 1), T(2, 1)]));
}

#[tokio::test]
async fn critical_path() {
  use super::entry::Entry;
  // First, let's describe the scenario with plain data.
  //
  // We label the nodes with static strings to help visualise the situation.
  // The first element of each tuple is a readable label. The second element represents the
  // duration for this action.
  let nodes = [
    ("download jvm", 10),
    ("download a", 1),
    ("download b", 2),
    ("download c", 3),
    ("compile a", 3),
    ("compile b", 20),
    ("compile c", 5),
  ];
  let deps = [
    ("download jvm", "compile a"),
    ("download jvm", "compile b"),
    ("download jvm", "compile c"),
    ("download a", "compile a"),
    ("download b", "compile b"),
    ("download c", "compile c"),
    ("compile a", "compile c"),
    ("compile b", "compile c"),
  ];

  // Describe a few transformations to navigate between our readable data and the actual types
  // needed for the graph.
  let tnode = |node: &str| {
    TNode::new(
      nodes
        .iter()
        .map(|(k, _)| k)
        .position(|label| &node == label)
        .unwrap(),
    )
  };
  let node_key = |node: &str| tnode(node);
  let node_entry = |node: &str| Entry::new(node_key(node));
  let node_and_duration_from_entry = |entry: &super::entry::Entry<TNode>| nodes[entry.node().0];
  let node_duration =
    |entry: &super::entry::Entry<TNode>| Duration::from_secs(node_and_duration_from_entry(entry).1);

  // Construct a graph and populate it with the nodes and edges prettily defined above.
  let graph = Graph::new();
  {
    let inner = &mut graph.inner.lock();
    for (node, _) in &nodes {
      let node_index = inner.pg.add_node(node_entry(node));
      inner.nodes.insert(node_key(node), node_index);
    }
    for (src, dst) in &deps {
      let src = inner.nodes[&node_key(src)];
      let dst = inner.nodes[&node_key(dst)];
      inner.pg.add_edge(src, dst, 1.0);
    }
  }

  // Calculate the critical path and validate it.
  {
    // The roots are all the sources, so we're covering the entire graph
    let roots = ["download jvm", "download a", "download b", "download c"]
      .iter()
      .map(|n| tnode(n))
      .collect::<Vec<_>>();
    let (expected_total_duration, expected_critical_path) = (
      Duration::from_secs(35),
      vec!["download jvm", "compile b", "compile c"],
    );
    let (total_duration, critical_path) = graph.critical_path(&roots, &node_duration);
    assert_eq!(expected_total_duration, total_duration);
    let critical_path = critical_path
      .iter()
      .map(|entry| node_and_duration_from_entry(entry).0)
      .collect::<Vec<_>>();
    assert_eq!(expected_critical_path, critical_path);
  }
  {
    // The roots exclude some nodes ("download jvm", "download a") from the graph.
    let roots = ["download b", "download c"]
      .iter()
      .map(|n| tnode(n))
      .collect::<Vec<_>>();
    let (expected_total_duration, expected_critical_path) = (
      Duration::from_secs(27),
      vec!["download b", "compile b", "compile c"],
    );
    let (total_duration, critical_path) = graph.critical_path(&roots, &node_duration);
    assert_eq!(expected_total_duration, total_duration);
    let critical_path = critical_path
      .iter()
      .map(|entry| node_and_duration_from_entry(entry).0)
      .collect::<Vec<_>>();
    assert_eq!(expected_critical_path, critical_path);
  }
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
struct TNode(usize, bool /*cacheability*/);
impl TNode {
  fn new(id: usize) -> Self {
    TNode(id, true)
  }
}
impl PartialEq for TNode {
  fn eq(&self, other: &Self) -> bool {
    self.0 == other.0
  }
}
impl Eq for TNode {}
impl Hash for TNode {
  fn hash<H: Hasher>(&self, state: &mut H) {
    self.0.hash(state);
  }
}
#[async_trait]
impl Node for TNode {
  type Context = TContext;
  type Item = Vec<T>;
  type Error = TError;

  async fn run(self, context: TContext) -> Result<Vec<T>, TError> {
    let mut abort_guard = context.abort_guard(self.clone());
    context.ran(self.clone());
    let token = T(self.0, context.salt());
    context.maybe_delay(&self).await;
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
    abort_guard.did_not_abort();
    res
  }

  fn cacheable(&self) -> bool {
    self.1
  }
}

impl std::fmt::Display for TNode {
  fn fmt(&self, f: &mut std::fmt::Formatter) -> Result<(), std::fmt::Error> {
    write!(f, "{:?}", self)
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
          "Node ids in {:?} were not monotonically ordered.",
          output
        ));
      }
      previous = node_id;
    }
    // Confirm ordered (non-monotonically).
    let mut previous: usize = 0;
    for &context_id in &context_ids {
      if previous > context_id {
        return Err(format!("Context ids in {:?} were not ordered.", output));
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
  run_id: usize,
  // A value that is included in every value computed by this context. Stands in for "the state of the
  // outside world". A test that wants to "change the outside world" and observe its effect on the
  // graph should change the salt to do so.
  salt: usize,
  // A mapping from source to destinations that drives what values each TNode depends on.
  // If there is no entry in this map for a node, then TNode::run will default to requesting
  // the next smallest node.
  edges: Arc<HashMap<TNode, Vec<TNode>>>,
  delays: Arc<HashMap<TNode, Duration>>,
  uncacheable: Arc<HashSet<TNode>>,
  graph: Arc<Graph<TNode>>,
  aborts: Arc<Mutex<Vec<TNode>>>,
  runs: Arc<Mutex<Vec<TNode>>>,
  entry_id: Option<EntryId>,
  stats: Arc<Mutex<Stats>>,
}
impl NodeContext for TContext {
  type Node = TNode;
  type RunId = usize;

  fn stats<'a>(&'a self) -> Box<dyn DerefMut<Target = Stats> + 'a> {
    Box::new(self.stats.lock())
  }

  fn clone_for(&self, entry_id: EntryId) -> TContext {
    TContext {
      run_id: self.run_id,
      salt: self.salt,
      edges: self.edges.clone(),
      delays: self.delays.clone(),
      uncacheable: self.uncacheable.clone(),
      graph: self.graph.clone(),
      aborts: self.aborts.clone(),
      runs: self.runs.clone(),
      entry_id: Some(entry_id),
      stats: self.stats.clone(),
    }
  }

  fn run_id(&self) -> &usize {
    &self.run_id
  }

  fn graph(&self) -> &Graph<TNode> {
    &self.graph
  }

  fn spawn<F>(&self, future: F)
  where
    F: Future<Output = ()> + Send + 'static,
  {
    // Avoids introducing a dependency on a threadpool.
    tokio::spawn(future);
  }
}

impl TContext {
  fn new(graph: Arc<Graph<TNode>>) -> TContext {
    TContext {
      run_id: 0,
      salt: 0,
      edges: Arc::default(),
      delays: Arc::default(),
      uncacheable: Arc::default(),
      graph,
      aborts: Arc::default(),
      runs: Arc::default(),
      entry_id: None,
      stats: Arc::default(),
    }
  }

  fn with_dependencies(mut self, edges: HashMap<TNode, Vec<TNode>>) -> TContext {
    self.edges = Arc::new(edges);
    self
  }

  fn with_delays(mut self, delays: HashMap<TNode, Duration>) -> TContext {
    self.delays = Arc::new(delays);
    self
  }

  fn with_uncacheable(mut self, uncacheable: HashSet<TNode>) -> TContext {
    self.uncacheable = Arc::new(uncacheable);
    self
  }

  fn with_salt(mut self, salt: usize) -> TContext {
    self.salt = salt;
    self
  }

  fn new_run(mut self, new_run_id: usize) -> TContext {
    self.run_id = new_run_id;
    self.runs.lock().clear();
    *self.stats.lock() = Stats::default();
    self
  }

  fn salt(&self) -> usize {
    self.salt
  }

  async fn get(&self, dst: TNode) -> Result<Vec<T>, TError> {
    self.graph.get(self.entry_id, self, dst).await
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

  async fn maybe_delay(&self, node: &TNode) {
    if let Some(delay) = self.delays.get(node) {
      delay_for(*delay).await;
    }
  }

  ///
  /// If the given TNode should declare a dependency on another TNode, returns that dependency.
  ///
  fn dependencies_of(&self, node: &TNode) -> Vec<TNode> {
    match self.edges.get(node) {
      Some(deps) => deps.clone(),
      None if node.0 > 0 => {
        let new_node_id = node.0 - 1;
        vec![TNode(
          new_node_id,
          !self.uncacheable.contains(&TNode::new(new_node_id)),
        )]
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
  Cyclic,
  Invalidated,
}
impl NodeError for TError {
  fn invalidated() -> Self {
    TError::Invalidated
  }

  fn cyclic(_path: Vec<String>) -> Self {
    TError::Cyclic
  }
}
