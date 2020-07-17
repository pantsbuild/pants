use std::cmp;
use std::collections::{HashMap, HashSet};
use std::future::Future;
use std::hash::{Hash, Hasher};
use std::sync::{mpsc, Arc};
use std::thread;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use parking_lot::Mutex;
use rand::{self, Rng};
use tokio::time::{delay_for, timeout, Elapsed};

use crate::{EdgeType, EntryId, Graph, InvalidationResult, Node, NodeContext, NodeError, RunToken};

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
  let context = context.new_session(1).with_salt(1);
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
    .with_dependencies(vec![(TNode::new(1), None)].into_iter().collect());
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

#[tokio::test]
async fn invalidate_randomly() {
  let graph = Arc::new(Graph::new());

  let invalidations = 10;
  let sleep_per_invalidation = Duration::from_millis(500);
  let range = 1000;

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
async fn dirty_dependents_of_uncacheable_node() {
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
  let context = context.new_session(1);
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(context.runs(), vec![TNode::new(0)]);

  // Re-request with a new session and different salt, and confirm that everything re-runs bottom
  // up (the order of node cleaning).
  let context = context.new_session(2).with_salt(1);
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
async fn uncachable_node_only_runs_once() {
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
    recv.recv_timeout(Duration::from_millis(100)).unwrap();
    thread::sleep(Duration::from_millis(50));
    graph2.invalidate_from_roots(|&TNode(n, _)| n == 0);
  });

  send.send(()).unwrap();
  assert_eq!(
    graph.create(TNode::new(2), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(2, 0)])
  );
  assert_eq!(
    context
      .runs()
      .into_iter()
      .filter(|n| *n == TNode::new(1))
      .count(),
    1,
  );
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
async fn canceled_immediately() {
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
    vec![(TNode::new(1), None), (TNode::new(0), Some(TNode::new(1)))]
      .into_iter()
      .collect(),
  );

  let res = graph.create(initial_bot, &context_up).await;

  assert_eq!(res, Ok(vec![T(1, 1), T(0, 1)]));

  let res = graph.create(initial_top, &context_up).await;

  assert_eq!(res, Ok(vec![T(1, 1), T(2, 1)]));
}

#[tokio::test]
async fn cyclic_strong_strong() {
  // A cycle between two nodes with strong edges.
  let (graph, context) = cyclic_references(vec![]);
  assert_eq!(
    graph.create(TNode::new(1), &context).await,
    Err(TError::Cyclic)
  );
  assert_eq!(
    graph.create(TNode::new(0), &context).await,
    Err(TError::Cyclic)
  );
}

#[tokio::test]
async fn cyclic_strong_weak_with_strong_first() {
  // A cycle between two nodes with a strong dep from top to bottom and a weak dep from bottom
  // to top, where we enter from the top first.
  let _logger = env_logger::try_init();

  let (graph, context) = cyclic_references(vec![TNode::new(1)]);
  assert_eq!(
    graph.create(TNode::new(1), &context).await,
    Ok(vec![T(0, 0), T(1, 0)])
  );
  assert_eq!(
    graph.create(TNode::new(0), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(0, 0)])
  );
}

///
/// TODO: Ignored due to https://github.com/pantsbuild/pants/issues/10229.
///
#[tokio::test]
#[ignore]
async fn cyclic_strong_weak_with_weak_first() {
  // A cycle between two nodes with a strong dep from top to bottom and a weak dep from bottom
  // to top, where we enter from the bottom first.
  let (graph, context) = cyclic_references(vec![TNode::new(1)]);
  assert_eq!(
    graph.create(TNode::new(0), &context).await,
    Ok(vec![T(0, 0), T(1, 0), T(0, 0)])
  );
  assert_eq!(
    graph.create(TNode::new(1), &context).await,
    Ok(vec![T(0, 0), T(1, 0)])
  );
}

#[tokio::test]
async fn cyclic_weak_weak() {
  // A cycle between two nodes, both with weak edges.
  let (graph, context) = cyclic_references(vec![TNode::new(0), TNode::new(1)]);
  assert_eq!(
    graph.create(TNode::new(1), &context).await,
    Ok(vec![T(0, 0), T(1, 0)])
  );
  assert_eq!(
    graph.create(TNode::new(0), &context).await,
    Ok(vec![T(1, 0), T(0, 0)])
  );
}

fn cyclic_references(weak: Vec<TNode>) -> (Arc<Graph<TNode>>, TContext) {
  let graph = Arc::new(Graph::new());
  let top = TNode::new(1);
  let context = TContext::new(graph.clone())
    .with_dependencies(
      // Request creation of a cycle by sending the bottom most node to the top.
      vec![(TNode::new(0), Some(top))].into_iter().collect(),
    )
    .with_weak(weak.into_iter().collect());
  (graph, context)
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
      inner
        .pg
        .add_edge(src, dst, (EdgeType::Strong, RunToken::initial()));
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
    let res = if let Some(dep) = context.dependency_of(&self) {
      let mut v = context.get(dep).await?;
      v.push(token);
      Ok(v)
    } else {
      Ok(vec![token])
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
  session_id: usize,
  // A value that is included in every value computed by this context. Stands in for "the state of the
  // outside world". A test that wants to "change the outside world" and observe its effect on the
  // graph should change the salt to do so.
  salt: usize,
  // When dependencies on these nodes are requested, those dependencies will be weak.
  weak: Arc<HashSet<TNode>>,
  // A mapping from source to optional destination that drives what values each TNode depends on.
  // If there is no entry in this map for a node, then TNode::run will default to requesting
  // the next smallest node. Finally, if a None entry is present, a node will have no
  // dependencies.
  edges: Arc<HashMap<TNode, Option<TNode>>>,
  delays: Arc<HashMap<TNode, Duration>>,
  uncacheable: Arc<HashSet<TNode>>,
  graph: Arc<Graph<TNode>>,
  aborts: Arc<Mutex<Vec<TNode>>>,
  runs: Arc<Mutex<Vec<TNode>>>,
  entry_id_and_run_token: Option<(EntryId, RunToken)>,
}
impl NodeContext for TContext {
  type Node = TNode;
  type SessionId = usize;

  fn clone_for(&self, entry_id: EntryId, run_token: RunToken) -> TContext {
    TContext {
      session_id: self.session_id,
      salt: self.salt,
      weak: self.weak.clone(),
      edges: self.edges.clone(),
      delays: self.delays.clone(),
      uncacheable: self.uncacheable.clone(),
      graph: self.graph.clone(),
      aborts: self.aborts.clone(),
      runs: self.runs.clone(),
      entry_id_and_run_token: Some((entry_id, run_token)),
    }
  }

  fn session_id(&self) -> &usize {
    &self.session_id
  }

  fn graph(&self) -> &Graph<TNode> {
    &self.graph
  }

  fn entry_id_and_run_token(&self) -> Option<(EntryId, RunToken)> {
    self.entry_id_and_run_token
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
      session_id: 0,
      salt: 0,
      weak: Arc::default(),
      edges: Arc::default(),
      delays: Arc::default(),
      uncacheable: Arc::default(),
      graph,
      aborts: Arc::default(),
      runs: Arc::default(),
      entry_id_and_run_token: None,
    }
  }

  fn with_weak(mut self, weak: HashSet<TNode>) -> TContext {
    self.weak = Arc::new(weak);
    self
  }

  fn with_dependencies(mut self, edges: HashMap<TNode, Option<TNode>>) -> TContext {
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

  fn new_session(mut self, new_session_id: usize) -> TContext {
    self.session_id = new_session_id;
    {
      let mut runs = self.runs.lock();
      runs.clear();
    }
    self
  }

  fn salt(&self) -> usize {
    self.salt
  }

  async fn get(&self, dst: TNode) -> Result<Vec<T>, TError> {
    if self.weak.contains(&dst) {
      Ok(
        self
          .graph
          .get_weak(self, dst)
          .await?
          .unwrap_or_else(Vec::new),
      )
    } else {
      self.graph.get(self, dst).await
    }
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
  fn dependency_of(&self, node: &TNode) -> Option<TNode> {
    match self.edges.get(node) {
      Some(Some(ref dep)) => Some(dep.clone()),
      Some(None) => None,
      None if node.0 > 0 => {
        let new_node_id = node.0 - 1;
        Some(TNode(
          new_node_id,
          !self.uncacheable.contains(&TNode::new(new_node_id)),
        ))
      }
      None => None,
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
