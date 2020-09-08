// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::single_match_else,
  clippy::unseparated_literal_suffix,
// TODO: Falsely triggers for async/await:
//   see https://github.com/rust-lang/rust-clippy/issues/5360
// clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use crate::rules::{DependencyKey, ParamTypes, Query, Rule};
use crate::{params_str, Entry, EntryWithDeps, InnerEntry, RootEntry, RuleEdges, RuleGraph};

use std::collections::{hash_map, BTreeMap, HashMap, HashSet, VecDeque};

use indexmap::IndexSet;
use petgraph::graph::{DiGraph, EdgeReference, NodeIndex};
use petgraph::visit::{DfsPostOrder, EdgeRef, IntoNodeReferences, NodeRef, VisitMap, Visitable};
use petgraph::Direction;

#[derive(Debug, Eq, PartialEq, Hash, Clone)]
enum Node<R: Rule> {
  Query(Query<R>),
  Rule(R),
  Param(R::TypeId),
}

impl<R: Rule> std::fmt::Display for Node<R> {
  fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
    match self {
      Node::Query(q) => write!(f, "{}", q),
      Node::Rule(r) => write!(f, "{}", r),
      Node::Param(p) => write!(f, "Param({})", p),
    }
  }
}

impl<R: Rule> Node<R> {
  fn dependency_keys(&self) -> Vec<R::DependencyKey> {
    match self {
      Node::Rule(r) => r.dependency_keys(),
      Node::Query(q) => vec![R::DependencyKey::new_root(q.product)],
      Node::Param(_) => vec![],
    }
  }
}

///
/// A Node labeled with Param types that are declared (by its transitive dependees) for consumption,
/// and Param types that are actually (by its transitive dependencies) consumed.
///
#[derive(Debug, Eq, PartialEq, Hash, Clone)]
struct ParamsLabeled<R: Rule> {
  node: Node<R>,
  // Params that are actually consumed by transitive dependencies.
  in_set: ParamTypes<R::TypeId>,
  // Params that the Node's transitive dependees have available for consumption.
  out_set: ParamTypes<R::TypeId>,
}

impl<R: Rule> ParamsLabeled<R> {
  fn new(node: Node<R>, out_set: ParamTypes<R::TypeId>) -> ParamsLabeled<R> {
    ParamsLabeled {
      node,
      in_set: ParamTypes::new(),
      out_set,
    }
  }
}

impl<R: Rule> std::fmt::Display for ParamsLabeled<R> {
  fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
    write!(
      f,
      "ParamsLabeled(node: {}, in: ({}), out: ({}))",
      self.node,
      params_str(&self.in_set),
      params_str(&self.out_set)
    )
  }
}

///
/// A type that may have been deleted with the given reason.
///
/// Wraps both nodes and edges in graphs that need to record why options were eliminated: in
/// particular, the monomorphize phase records how and why choices were eliminated to allow later
/// phases to render useful error messages.
///
#[derive(Debug, Eq, PartialEq, Hash, Clone)]
struct MaybeDeleted<T, Reason>(T, Option<Reason>);

impl<T, Reason> MaybeDeleted<T, Reason> {
  fn new(t: T) -> MaybeDeleted<T, Reason> {
    MaybeDeleted(t, None)
  }

  fn inner(&self) -> Option<&T> {
    if self.is_deleted() {
      None
    } else {
      Some(&self.0)
    }
  }

  fn deleted_reason(&self) -> Option<&Reason> {
    self.1.as_ref()
  }

  fn is_deleted(&self) -> bool {
    self.1.is_some()
  }

  fn mark_deleted(&mut self, reason: Reason) {
    self.1 = Some(reason);
  }
}

impl<T: std::fmt::Display, Reason: std::fmt::Debug> std::fmt::Display for MaybeDeleted<T, Reason> {
  fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
    if let Some(ref reason) = self.1 {
      write!(f, "Deleted({}, reason: {:?})", self.0, reason,)
    } else {
      write!(f, "{}", self.0)
    }
  }
}

#[derive(Debug, Eq, PartialEq, Hash, Clone, Copy)]
enum NodePrunedReason {
  Monomorphized,
  NoDependees,
  NoValidCombinationsOfDependencies,
}

#[derive(Debug, Eq, PartialEq, Hash, Clone, Copy)]
enum EdgePrunedReason {
  DoesNotConsumeProvidedParam,
  SmallerParamSetAvailable,
}

// A node labeled with an out_set.
type Graph<R> =
  DiGraph<(Node<R>, ParamTypes<<R as Rule>::TypeId>), <R as Rule>::DependencyKey, u32>;
// A node labeled with both an out_set and in_set.
type ParamsLabeledGraph<R> = DiGraph<ParamsLabeled<R>, <R as Rule>::DependencyKey, u32>;
// A node labeled with both an out_set and in_set, and possibly marked deleted.
type MonomorphizedGraph<R> = DiGraph<
  MaybeDeleted<ParamsLabeled<R>, NodePrunedReason>,
  MaybeDeleted<<R as Rule>::DependencyKey, EdgePrunedReason>,
  u32,
>;

///
/// Given the set of Rules and Queries, produce a RuleGraph that allows dependency nodes
/// to be found statically.
///
pub struct Builder<R: Rule> {
  rules: BTreeMap<R::TypeId, Vec<R>>,
  queries: Vec<Query<R>>,
  params: ParamTypes<R::TypeId>,
}

impl<R: Rule> Builder<R> {
  pub fn new(rules: Vec<R>, queries: Vec<Query<R>>) -> Builder<R> {
    // Group rules by product/return type.
    let mut rules_by_type = BTreeMap::new();
    for rule in rules {
      rules_by_type
        .entry(rule.product())
        .or_insert_with(Vec::new)
        .push(rule);
    }
    // The set of all input Params in the graph: ie, those provided either via Queries, or via
    // a Rule with a DependencyKey that provides a Param.
    let params = queries
      .iter()
      .flat_map(|query| query.params.iter().cloned())
      .chain(
        rules_by_type
          .values()
          .flatten()
          .flat_map(|rule| rule.dependency_keys())
          .filter_map(|dk| dk.provided_param()),
      )
      .collect::<ParamTypes<_>>();
    Builder {
      rules: rules_by_type,
      queries,
      params,
    }
  }

  pub fn graph(self) -> Result<RuleGraph<R>, String> {
    // 1. build a polymorphic graph
    //    * only consideration: whether something is a valid input Param _anywhere_ in the graph, and
    //      that we can't satisfy a Get with a Param
    let initial_polymorphic_graph = self.initial_polymorphic()?;
    // 2. run live variable analysis on the polymorphic graph to gather a conservative (ie, overly
    //    large) set of used Params.
    let polymorphic_live_params_graph = self.live_param_labeled_graph(initial_polymorphic_graph);
    // 3. monomorphize by partitioning a node (and its dependees) for each valid combination of its
    //    dependencies while mantaining liveness sets.
    let monomorphic_live_params_graph = Self::monomorphize(polymorphic_live_params_graph);
    // 4. choose the best dependencies via in/out sets. fail if:
    //    * invalid required param at a Query
    //    * take smallest option, fail for equal-sized sets
    let pruned_edges_graph = self.prune_edges(monomorphic_live_params_graph)?;
    // 5. generate the final graph for nodes reachable from queries
    self.finalize(pruned_edges_graph)
  }

  fn initial_polymorphic(&self) -> Result<Graph<R>, String> {
    let mut graph: Graph<R> = DiGraph::new();

    // Initialize the graph with nodes for Queries and Params
    let queries = self
      .queries
      .iter()
      .map(|query| {
        (
          query,
          graph.add_node((
            Node::Query(query.clone()),
            query.params.iter().cloned().collect(),
          )),
        )
      })
      .collect::<HashMap<_, _>>();
    let params = self
      .params
      .iter()
      .cloned()
      .map(|param| {
        (
          param,
          graph.add_node((Node::Param(param), ParamTypes::new())),
        )
      })
      .collect::<HashMap<_, _>>();

    // Rules are created on the fly based on the out_set of dependees.
    let mut rules: HashMap<(R, ParamTypes<R::TypeId>), NodeIndex<u32>> = HashMap::new();
    let mut satisfiable_nodes: HashSet<Node<R>> = HashSet::new();
    let mut unsatisfiable_nodes: HashMap<NodeIndex<u32>, Vec<R::DependencyKey>> = HashMap::new();

    // Starting from Queries, visit all reachable nodes in the graph.
    let mut visited = HashSet::new();
    let mut to_visit = queries.values().cloned().collect::<Vec<_>>();
    let mut iteration = 0;
    while let Some(node_id) = to_visit.pop() {
      if !visited.visit(node_id) {
        continue;
      }
      iteration += 1;
      if iteration % 1000 == 0 {
        log::debug!(
          "initial_polymorphic iteration {}: {} nodes",
          iteration,
          graph.node_count()
        );
      }

      // Collect the candidates that might satisfy the dependency keys of the node (if it has any).
      let candidates_by_key = graph[node_id]
        .0
        .dependency_keys()
        .into_iter()
        .map(|dependency_key| {
          let mut candidates = Vec::new();
          if dependency_key.provided_param().is_none()
            && graph[node_id].1.contains(&dependency_key.product())
          {
            candidates.push(Node::Param(dependency_key.product()));
          }

          if let Some(rules) = self.rules.get(&dependency_key.product()) {
            candidates.extend(rules.iter().map(|r| Node::Rule(r.clone())));
          };

          (dependency_key, candidates)
        })
        .collect::<HashMap<_, _>>();

      // If any dependency keys could not be satisfied, continue.
      let unsatisfiable_keys = candidates_by_key
        .iter()
        .filter_map(|(dependency_key, candidates)| {
          if candidates.is_empty() {
            Some(*dependency_key)
          } else {
            None
          }
        })
        .collect::<Vec<_>>();
      if !unsatisfiable_keys.is_empty() {
        unsatisfiable_nodes.insert(node_id, unsatisfiable_keys);
        continue;
      }

      // Determine which Params are unambiguously consumed by this node: we eagerly remove them
      // from the out_set of all other dependencies to shrink the total number of unique nodes
      // created during this phase. The rest will be chosen during monomorphize, where the out_set
      // shrinks further.
      let consumed_from_out_set = candidates_by_key
        .values()
        .filter_map(|candidates| {
          if candidates.len() != 1 {
            None
          } else if let Node::Param(p) = candidates[0] {
            Some(p)
          } else {
            None
          }
        })
        .collect::<HashSet<_>>();

      // Create nodes for each of the candidates using the computed out_set.
      let out_set = graph[node_id]
        .1
        .iter()
        .filter(|p| !consumed_from_out_set.contains(p))
        .cloned()
        .collect::<ParamTypes<_>>();
      for (dependency_key, candidates) in candidates_by_key {
        for candidate in candidates {
          match candidate {
            Node::Param(_) => {
              graph.add_edge(
                node_id,
                *params.get(&dependency_key.product()).unwrap(),
                dependency_key,
              );
            }
            Node::Rule(rule) => {
              // If the key provides a Param for the Rule to consume, include it in the out_set for
              // the dependency node.
              let out_set = if let Some(provided_param) = dependency_key.provided_param() {
                let mut out_set = out_set.clone();
                out_set.insert(provided_param);
                out_set
              } else {
                out_set.clone()
              };
              let rule_id = rules
                .entry((rule.clone(), out_set.clone()))
                .or_insert_with(|| graph.add_node((Node::Rule(rule.clone()), out_set)));
              graph.add_edge(node_id, *rule_id, dependency_key);
              to_visit.push(*rule_id);
            }
            Node::Query(_) => unreachable!("A Query may not be a dependency."),
          }
        }
      }

      satisfiable_nodes.insert(graph[node_id].0.clone());
    }

    // If any Rules had unsatisfiable copies but no satisfiable copies, error eagerly.
    // TODO: Render all of these in a flat list.
    for (node_id, dependency_keys) in &unsatisfiable_nodes {
      let (node, out_set) = &graph[*node_id];
      if satisfiable_nodes.contains(node) {
        continue;
      }

      for dependency_key in dependency_keys {
        log::debug!(
          "no source of {} for {} with {}",
          dependency_key,
          node,
          params_str(&out_set),
        );
        let root_hint = if dependency_key.provided_param().is_none() {
          "\nIf rather than being computed by a rule, that type should be provided \
            from outside the rule graph, consider adding it as an input for the relevant QueryRule."
        } else {
          ""
        };
        // TODO: This needs clarifying, because it's now context specific: it might also be because
        // the out_set of the dependee did not provide the type.
        return Err(format!(
            "No installed rules return the type {}: Is the rule that you're expecting to run registered?{}",
            dependency_key.product(),
            root_hint,
        ));
      }
    }

    // Remove all unsatisfiable nodes.
    // TODO: Should maybe preserve these as MaybeDeleted for the purposes of error messages, in
    // case a rule that should have been used was eliminated due to the lack of a Param.
    Ok(graph.filter_map(
      |node_id, node| {
        if !unsatisfiable_nodes.contains_key(&node_id) {
          Some(node.clone())
        } else {
          None
        }
      },
      |_, edge_weight| Some(*edge_weight),
    ))
  }

  ///
  /// Splits Rules in the graph that have multiple valid sources of a dependency, and recalculates
  /// their in/out sets to attempt to re-join with other copies of the Rule with identical sets.
  /// Similar to `live_param_labeled_graph`, this is an analysis that propagates both up and down
  /// the graph (and maintains the in/out sets initialized by `live_param_labeled_graph` while doing
  /// so). Visiting a node might cause us to split it and re-calculate the in/out sets for each
  /// split; we then visit the nodes affected by the split to ensure that they are updated as well,
  /// and so on.
  ///
  /// During this phase, the out_set of a node is used to determine which Params are legal to
  /// consume in each subgraph: as this information propagates down the graph, Param dependencies
  /// might be eliminated, which results in corresponding changes to the in_set which flow back
  /// up the graph. As the in_sets shrink, we shrink the out_sets as well to avoid creating
  /// redundant nodes: although the params might still technically be declared by the dependees, we
  /// can be sure that any not contained in the in_set are not used.
  ///
  /// Any node that has only invalid sources of a dependency (such as those that do not consume a
  /// provided param, or those that consume a Param that is not present in their scope) will be
  /// removed (which may also cause its dependees to be removed, for the same reason). This is safe
  /// to do at any time during the monomorphize run, because the in/out sets are adjusted in tandem
  /// based on the current dependencies/dependees.
  ///
  /// The exit condition for this phase is that all valid combinations of dependencies have the
  /// same minimal in_set. This occurs when all splits that would result in smaller sets of
  /// dependencies for a node have been executed. Note though that it might still be the case that
  /// a node has multiple sources of a particular dependency with the _same_ param requirements.
  /// This represents ambiguity that must be handled (likely by erroring) in later phases.
  ///
  fn monomorphize(graph: ParamsLabeledGraph<R>) -> MonomorphizedGraph<R> {
    // The monomorphized graph contains nodes and edges that have been marked deleted, because:
    //   1. we expose which nodes and edges were deleted to allow for improved error messages
    //   2. it is slow to delete nodes/edges with petgraph: marking them is much cheaper.
    // Initialize with no deleted nodes/edges.
    let mut graph: MonomorphizedGraph<R> = graph.map(
      |_node_id, node| MaybeDeleted::new(node.clone()),
      |_edge_id, edge_weight| MaybeDeleted::new(*edge_weight),
    );

    // In order to reduce the number of permutations rapidly, we make a best effort attempt to
    // visit a node before any of its dependencies using DFS-post-order. We need to visit all
    // nodes in the graph, but because monomorphizing a node enqueues its dependees we may
    // visit some of them multiple times.
    //
    // DFS converges much more quickly than BFS. We use an IndexSet to preserve the initial walk
    // order while still removing duplicates. The nodes that should be visited last will remain at
    // the bottom of the set/stack, and will stay there until things above them have been removed.
    let mut to_visit = {
      let mut dfs = DfsPostOrder {
        stack: graph.externals(Direction::Incoming).collect(),
        discovered: graph.visit_map(),
        finished: graph.visit_map(),
      };
      let mut to_visit = Vec::new();
      while let Some(node_id) = dfs.next(&graph) {
        to_visit.push(node_id);
      }
      // The IndexSet acts like a stack (ie, we can only remove from the end) so we reverse the DFS
      // order to ensure that the last nodes in the DFS end up at the bottom of the stack.
      to_visit.into_iter().rev().collect::<IndexSet<_>>()
    };

    // Both the in_set and out_set shrink as this phase continues and nodes are monomorphized.
    // Because the sets only shrink, we are able to eliminate direct dependencies based on their
    // absence from the sets.
    //
    // If a node has been monomorphized and all of its dependencies have minimal in_sets, then we
    // can assume that its in_set is minimal too: it has _stopped_ shrinking. That means that we can
    // additionally prune dependencies transitively in cases where in_sets contain things that are
    // not in a node's out_set (since the out_set will not grow, and the minimal in_set represents
    // the node's true requirements).
    let mut minimal_in_set = HashSet::new();

    // Should be called after a Node has been successfully reduced (regardless of whether it became
    // monomorphic) to maybe mark it minimal.
    let maybe_mark_minimal_in_set = |minimal_in_set: &mut HashSet<NodeIndex<u32>>,
                                     graph: &MonomorphizedGraph<R>,
                                     node_id: NodeIndex<u32>| {
      let dependencies_are_minimal = graph
        .edges_directed(node_id, Direction::Outgoing)
        .filter_map(|edge_ref| {
          if graph[edge_ref.target()].is_deleted() || edge_ref.weight().is_deleted() {
            None
          } else {
            Some(edge_ref.target())
          }
        })
        .all(|dependency_id| node_id == dependency_id || minimal_in_set.contains(&dependency_id));
      if dependencies_are_minimal {
        minimal_in_set.insert(node_id);
      }
    };

    // TODO: Unfortunately, monomorphize is not completely monotonic (for reasons I can't nail
    // down), and so it is possible for nodes to split fruitlessly in loops, where each iteration
    // of the loop results in identical splits of each intermediate node. We could hypothetically
    // break these loops by shrinking the in_set/out_sets synthetically (ie: removing Params until
    // the loop converged), but it's likely that that would result in strange error cases.
    //
    // Instead, we force the phase to be monotonic by recording splits that we have executed, and
    // considering the re-execution of the same split to be a noop. If this results in a loop of
    // nodes that cannot be further reduced, it's likely that that loop will not be the only way to
    // satisfy a dependency: if it is, then at least we have preserved the loop for error
    // reporting.
    let mut splits: HashMap<ParamsLabeled<R>, Vec<HashSet<ParamsLabeled<R>>>> = HashMap::new();

    // Rules are not always split in disjoint ways, so as they are further split, they might become
    // identical to other splits. We attempt to re-join with existing identical Rule nodes to keep
    // the node count more reasonable.
    let mut rules: HashMap<ParamsLabeled<R>, _> = graph
      .node_references()
      .filter_map(|node_ref| match node_ref.weight().0.node {
        Node::Rule(_) => Some((node_ref.weight().0.clone(), node_ref.id())),
        _ => None,
      })
      .collect();

    let mut iteration = 0;
    let mut maybe_in_loop = HashSet::new();
    let mut looping = false;
    while let Some(node_id) = to_visit.pop() {
      let node = if let Some(node) = graph[node_id].inner() {
        node
      } else {
        continue;
      };
      match node.node {
        Node::Rule(_) => {
          // Fall through to visit the rule.
        }
        Node::Param(_) => {
          // Ensure that the Param is marked minimal, but don't bother to visit.
          minimal_in_set.insert(node_id);
          continue;
        }
        Node::Query(_) => {
          // Don't bother to visit.
          continue;
        }
      }

      iteration += 1;
      if iteration > 100000 {
        looping = true;
      }
      if iteration % 1000 == 0 {
        let live_count = graph
          .node_references()
          .filter(|node_ref| !node_ref.weight().is_deleted())
          .count();
        let minimal_count = graph
          .node_references()
          .filter(|node_ref| {
            !node_ref.weight().is_deleted() && minimal_in_set.contains(&node_ref.id())
          })
          .count();
        log::debug!(
          "rule_graph monomorphize: iteration {}: live: {}, minimal: {}, to_visit: {}, total: {}",
          iteration,
          live_count,
          minimal_count,
          to_visit.len(),
          graph.node_count(),
        );
      }

      // Group dependencies by DependencyKey.
      let dependencies_by_key: Vec<Vec<(R::DependencyKey, NodeIndex<u32>)>> =
        Self::edges_by_dependency_key(&graph, node_id, false)
          .into_iter()
          .map(|(_, edge_refs)| {
            edge_refs
              .iter()
              .map(|edge_ref| (edge_ref.weight().0, edge_ref.target()))
              .collect()
          })
          .collect();

      // A node with no declared dependencies is always already minimal.
      if dependencies_by_key.is_empty() {
        minimal_in_set.insert(node_id);

        // But we ensure that its out_set is accurate before continuing.
        if node.out_set != node.in_set {
          rules.remove(&node);
          graph.node_weight_mut(node_id).unwrap().0.out_set = graph[node_id].0.in_set.clone();
          rules.insert(graph[node_id].0.clone(), node_id);
        }
        continue;
      }

      // Group dependees by out_set.
      let dependees_by_out_set: HashMap<ParamTypes<R::TypeId>, Vec<(R::DependencyKey, _)>> = {
        let mut dbos = HashMap::new();
        for edge_ref in graph.edges_directed(node_id, Direction::Incoming) {
          if edge_ref.weight().is_deleted() || graph[edge_ref.source()].is_deleted() {
            continue;
          }

          // Compute the out_set of this dependee, plus the provided param, if any.
          let mut out_set = graph[edge_ref.source()].0.out_set.clone();
          if let Some(p) = edge_ref.weight().0.provided_param() {
            out_set.insert(p);
          }

          dbos
            .entry(out_set)
            .or_insert_with(Vec::new)
            .push((edge_ref.weight().0, edge_ref.source()));
        }
        dbos
      };
      let had_dependees = !dependees_by_out_set.is_empty();

      if looping {
        log::debug!(
          "creating monomorphizations (from {} dependee sets and {:?} dependencies) for {:?}: {:#?} with {:#?} and {:#?}",
          dependees_by_out_set.len(),
          dependencies_by_key
        .iter()
        .map(|edges| edges.len())
        .collect::<Vec<_>>(),
          node_id,
          graph[node_id],
          dependencies_by_key
            .iter()
            .flat_map(|choices| {
              choices
                .iter()
                .map(|(dk, di)| (dk.to_string(), graph[*di].to_string()))
            })
            .collect::<Vec<_>>(),
          dependees_by_out_set
        .keys()
        .map(|out_set| params_str(&out_set))
        .collect::<Vec<_>>(),
        );
      }

      // Generate the monomorphizations of this Node, where each key is a potential node to
      // create, and the dependees and dependencies to give it (respectively).
      let mut monomorphizations = HashMap::new();
      for (out_set, dependees) in dependees_by_out_set {
        for (node, dependencies) in Self::monomorphizations(
          &graph,
          node_id,
          out_set.clone(),
          &minimal_in_set,
          &dependencies_by_key,
        ) {
          let entry = monomorphizations
            .entry(node)
            .or_insert_with(|| (HashSet::new(), HashSet::new()));
          entry.0.extend(dependees.iter().cloned());
          entry.1.extend(dependencies);
        }
      }

      // The goal of this phase is to shrink the in_sets as much as possible via dependency changes.
      //
      // The base case for a node then is that its dependencies cannot be partitioned to produce
      // disjoint in_sets, and that the in/out sets are accurate based on any transitive changes
      // above or below this node. If both of these conditions are satisified, the node is valid.
      //
      // See the TODO on `splits`.
      if let Some((_, dependencies)) = monomorphizations.get(&graph[node_id].0) {
        // We generated an identical node: if there was only one output node and its dependencies were
        // also identical, then we have nooped.
        let original_dependencies = || {
          graph
            .edges_directed(node_id, Direction::Outgoing)
            .filter_map(|edge_ref| {
              if graph[edge_ref.target()].is_deleted() {
                None
              } else {
                edge_ref.weight().inner().map(|dk| (*dk, edge_ref.target()))
              }
            })
            .collect::<HashSet<_>>()
        };
        if monomorphizations.len() == 1 && dependencies == &original_dependencies() {
          // This node cannot be reduced. If its dependencies had minimal in_sets, then it now also
          // has a minimal in_set.
          maybe_mark_minimal_in_set(&mut minimal_in_set, &graph, node_id);
          if looping {
            log::debug!(
              "not able to reduce {:?}: {} (had {} monomorphizations)",
              node_id,
              graph[node_id],
              monomorphizations.len()
            );
          }
          continue;
        }

        // Otherwise, see if this exact split has occurred before: if so, noop.
        let split_output = monomorphizations.keys().cloned().collect::<HashSet<_>>();
        if splits
          .get(&graph[node_id].0)
          .map(|split_outputs| split_outputs.contains(&split_output))
          .unwrap_or(false)
        {
          // This exact split has been executed before: noop. See the TODO on `splits`.
          if looping {
            log::debug!(
              "re-observed split:\n  {}\n  to\n  {}",
              graph[node_id],
              split_output
                .iter()
                .map(|n| n.to_string())
                .collect::<Vec<_>>()
                .join("\n  ")
            );
          }
          continue;
        }
        // Else, record it for later.
        splits
          .entry(graph[node_id].0.clone())
          .or_insert_with(Vec::new)
          .push(split_output);
      }

      if looping {
        maybe_in_loop.insert(node_id);
        if maybe_in_loop.len() > 40 {
          let subgraph = graph.filter_map(
            |node_id, node| {
              if maybe_in_loop.contains(&node_id) {
                Some(format!("{:?}: {}", node_id, node))
              } else {
                None
              }
            },
            |_, edge_weight| Some(edge_weight.clone()),
          );

          panic!(
            "Loop subgraph: {}",
            petgraph::dot::Dot::with_config(&subgraph, &[])
          );
        }
      }

      // Needs changes. Mark this node deleted.
      graph
        .node_weight_mut(node_id)
        .unwrap()
        .mark_deleted(if !monomorphizations.is_empty() {
          NodePrunedReason::Monomorphized
        } else if had_dependees {
          NodePrunedReason::NoValidCombinationsOfDependencies
        } else {
          NodePrunedReason::NoDependees
        });
      rules.remove(&graph[node_id].0);
      // And schedule visits for all dependees and dependencies.
      to_visit.extend(graph.neighbors_undirected(node_id));

      // Generate a replacement node for each monomorphization of this rule.
      for (new_node, (dependees, dependencies)) in monomorphizations {
        if looping {
          log::debug!(
            "   generating {:#?}, with {} dependees and {} dependencies ({} minimal) which consumes: {:#?}",
            new_node,
            dependees.len(),
            dependencies.len(),
            dependencies.iter().filter(|(_, dependency_id)| minimal_in_set.contains(dependency_id)).count(),
            dependencies
              .iter()
              .map(|(dk, di)| (dk.to_string(), graph[*di].to_string(),))
              .collect::<Vec<_>>()
          );
        }

        let (replacement_id, is_new_node) = match rules.entry(new_node.clone()) {
          hash_map::Entry::Occupied(oe) => {
            // We're adding edges to an existing node. Ensure that we visit it later to square
            // that.
            // NB: Because these edges do not affect the size of the in_set of this node, if it
            // already had a minimal_in_set, it still does, despite not being monomorphic any
            // longer.
            let existing_id = *oe.get();
            to_visit.insert(existing_id);
            (existing_id, false)
          }
          hash_map::Entry::Vacant(ve) => {
            let new_node_id = graph.add_node(MaybeDeleted::new(new_node));
            (*ve.insert(new_node_id), true)
          }
        };

        if looping {
          let keyword = if is_new_node { "creating" } else { "using" };
          log::debug!("node: {}: {:?}", keyword, replacement_id);
        }

        // Give all dependees edges to the new node.
        for (dependency_key, dependee_id) in &dependees {
          // Add a new edge (and confirm that we're not creating a duplicate if this is not a new
          // node).
          let is_new_edge = || {
            graph
              .edges_directed(*dependee_id, Direction::Outgoing)
              .all(|edge_ref| {
                edge_ref.target() != replacement_id
                  || edge_ref.weight().inner() != Some(dependency_key)
              })
          };
          if is_new_node || is_new_edge() {
            let mut edge = MaybeDeleted::new(*dependency_key);
            if let Some(p) = dependency_key.provided_param() {
              // NB: If the edge is invalid because it does not consume the provide param, we
              // create it as deleted with that reason.
              if !graph[replacement_id].0.in_set.contains(&p) {
                edge.mark_deleted(EdgePrunedReason::DoesNotConsumeProvidedParam);
              }
            }
            if looping {
              log::debug!("dependee edge: adding: ({:?}, {})", dependee_id, edge);
            }
            graph.add_edge(*dependee_id, replacement_id, edge);
          } else if looping {
            log::debug!(
              "dependee edge: skipping existing: {:?}",
              (dependee_id, dependency_key)
            );
          }
        }

        // And give the replacement node edges to this combination of dependencies (while confirming that we
        // don't create dupes).
        let existing_edges = graph
          .edges_directed(replacement_id, Direction::Outgoing)
          .filter_map(|edge_ref| edge_ref.weight().inner().map(|dk| (*dk, edge_ref.target())))
          .collect::<HashSet<_>>();
        for (dependency_key, dependency_id) in dependencies {
          // NB: When a node depends on itself, we adjust the destination of that self-edge to point to
          // the new node.
          let dependency_id = if dependency_id == node_id {
            replacement_id
          } else {
            dependency_id
          };
          if existing_edges.contains(&(dependency_key, dependency_id)) {
            if looping {
              log::debug!(
                "dependency edge: skipping existing: {:?}",
                (dependency_key, dependency_id)
              );
            }
          } else {
            if looping {
              log::debug!(
                "dependency edge: adding: {:?}",
                (dependency_key, dependency_id)
              );
            }
            graph.add_edge(
              replacement_id,
              dependency_id,
              MaybeDeleted::new(dependency_key),
            );
          }
        }

        // Now that all edges have been created, maybe mark it minimal.
        if is_new_node {
          maybe_mark_minimal_in_set(&mut minimal_in_set, &graph, replacement_id);
        }
      }
    }

    graph
  }

  ///
  /// Execute live variable analysis to determine which Params are used by each node.
  ///
  /// See https://en.wikipedia.org/wiki/Live_variable_analysis
  ///
  fn live_param_labeled_graph(&self, graph: Graph<R>) -> ParamsLabeledGraph<R> {
    // Add in_sets for each node, with all sets empty initially.
    let mut graph: ParamsLabeledGraph<R> = graph.map(
      |_node_id, node| ParamsLabeled::new(node.0.clone(), node.1.clone()),
      |_edge_id, edge_weight| *edge_weight,
    );

    // Because the leaves of the graph (generally Param nodes) are the most significant source of
    // information, we start there. But we will eventually visit all reachable nodes, possibly
    // multiple times. Information flows up (the in_sets) this graph.
    let mut to_visit = graph
      .externals(Direction::Outgoing)
      .collect::<VecDeque<_>>();
    while let Some(node_id) = to_visit.pop_front() {
      let new_in_set = match &graph[node_id].node {
        Node::Rule(_) => {
          // Rules have in_sets computed from their dependencies.
          Some(Self::dependencies_in_set(
            node_id,
            graph
              .edges_directed(node_id, Direction::Outgoing)
              .map(|edge_ref| {
                (
                  *edge_ref.weight(),
                  edge_ref.target(),
                  &graph[edge_ref.target()].in_set,
                )
              }),
          ))
        }
        Node::Param(p) => {
          // Params are always leaves with an in-set of their own value, and no out-set.
          let mut in_set = ParamTypes::new();
          in_set.insert(*p);
          Some(in_set)
        }
        Node::Query(_) => {
          // Queries are always roots which declare some parameters.
          let in_set = Self::dependencies_in_set(
            node_id,
            graph
              .edges_directed(node_id, Direction::Outgoing)
              .map(|edge_ref| {
                (
                  *edge_ref.weight(),
                  edge_ref.target(),
                  &graph[edge_ref.target()].in_set,
                )
              }),
          );
          Some(in_set)
        }
      };

      if let Some(in_set) = new_in_set {
        if in_set != graph[node_id].in_set {
          to_visit.extend(graph.neighbors_directed(node_id, Direction::Incoming));
          graph[node_id].in_set = in_set;
        }
      }
    }

    graph
  }

  ///
  /// After nodes have been monomorphizedthey have the smallest dependency sets possible.
  /// In cases where a node still has more than one source of a dependency, this phase statically
  /// decides which source of each DependencyKey to use, and prunes edges to the rest.
  ///
  /// If a node has too many dependencies (in an ambiguous way) or too few, this phase will fail
  /// slowly to collect all errored nodes (including those that have been deleted), and render the
  /// most specific error possible.
  ///
  fn prune_edges(&self, mut graph: MonomorphizedGraph<R>) -> Result<ParamsLabeledGraph<R>, String> {
    // Walk from roots, choosing one source for each DependencyKey of each node.
    let mut visited = graph.visit_map();
    let mut errored = HashMap::new();
    // NB: We visit any node that is enqueued, even if it is deleted. But because we filter to
    // Queries at the root (which are never deleted by monomorphize), a deleted node will only be
    // enqueued in where we have already encountered an error and are continuing on to find a
    // root cause.
    let mut to_visit = graph
      .node_references()
      .filter_map(|node_ref| match node_ref.weight().inner() {
        Some(ParamsLabeled {
          node: Node::Query(_),
          ..
        }) => Some(node_ref.id()),
        _ => None,
      })
      .collect::<Vec<_>>();

    while let Some(node_id) = to_visit.pop() {
      if !visited.visit(node_id) {
        continue;
      }
      // See the note above about deleted nodes.
      let node = &graph[node_id].0.node;

      let edges_by_dependency_key = Self::edges_by_dependency_key(&graph, node_id, true);
      let mut edges_to_delete = Vec::new();
      for (dependency_key, edge_refs) in edges_by_dependency_key {
        // Filter out any that are not satisfiable for this node based on its type and in/out sets,
        // and any that were deleted/invalid.
        let relevant_edge_refs: Vec<_> = match node {
          Node::Query(q) => {
            // Only dependencies with in_sets that are a subset of our params can be used.
            edge_refs
              .iter()
              .filter(|edge_ref| {
                if edge_ref.weight().is_deleted() || graph[edge_ref.target()].is_deleted() {
                  false
                } else {
                  let dependency_in_set = &graph[edge_ref.target()].0.in_set;
                  dependency_in_set.is_subset(&q.params)
                }
              })
              .collect()
          }
          Node::Rule(_) => {
            // If there is a provided param, only dependencies that consume it can be used.
            edge_refs
              .iter()
              .filter(|edge_ref| {
                if edge_ref.weight().is_deleted() || graph[edge_ref.target()].is_deleted() {
                  false
                } else if let Some(provided_param) = dependency_key.provided_param() {
                  graph[edge_ref.target()].0.in_set.contains(&provided_param)
                } else {
                  true
                }
              })
              .collect()
          }
          Node::Param(p) => {
            panic!(
              "A Param node should not have dependencies: {} had {:#?}",
              p,
              edge_refs
                .iter()
                .map(|edge_ref| format!("{}", graph[edge_ref.target()].0.node))
                .collect::<Vec<_>>()
            );
          }
        };

        // We prefer the dependency with the smallest set of input Params, as that minimizes Rule
        // identities in the graph and biases toward receiving values from dependencies (which do not
        // affect our identity) rather than dependents.
        #[allow(clippy::comparison_chain)]
        let chosen_edges = {
          let mut minimum_param_set_size = ::std::usize::MAX;
          let mut chosen_edges = Vec::new();
          for edge_ref in relevant_edge_refs {
            let param_set_size = graph[edge_ref.target()].0.in_set.len();
            if param_set_size < minimum_param_set_size {
              chosen_edges.clear();
              chosen_edges.push(edge_ref);
              minimum_param_set_size = param_set_size;
            } else if param_set_size == minimum_param_set_size {
              chosen_edges.push(edge_ref);
            }
          }
          chosen_edges
        };
        match chosen_edges.len() {
          1 => {
            // Schedule this dependency to be visited, and mark all other choices deleted.
            let chosen_edge = chosen_edges[0];
            to_visit.push(chosen_edge.target());
            edges_to_delete.extend(
              edge_refs
                .iter()
                .map(|edge_ref| edge_ref.id())
                .filter(|edge_ref_id| *edge_ref_id != chosen_edge.id()),
            );
          }
          0 => {
            // Render all candidates, and traverse any edges that were deleted for interesting reasons.
            to_visit.extend(
              edge_refs
                .iter()
                .filter(|edge_ref| match graph[edge_ref.target()].deleted_reason() {
                  None | Some(NodePrunedReason::NoValidCombinationsOfDependencies) => true,
                  _ => false,
                })
                .map(|edge_ref| edge_ref.target()),
            );
            errored.insert(
              node_id,
              format!(
                "No source of dependency {} for {}. All potential sources were eliminated: {:#?}",
                dependency_key,
                node,
                edge_refs
                  .iter()
                  .map(|edge_ref| {
                    let node = &graph[edge_ref.target()];
                    let reason_suffix = if let Some(reason) = node.deleted_reason() {
                      format!("{:?}: ", reason)
                    } else {
                      "".to_owned()
                    };
                    format!(
                      "{}{} (for {})",
                      reason_suffix,
                      node.0.node,
                      params_str(&node.0.in_set)
                    )
                  })
                  .collect::<Vec<_>>()
              ),
            );
          }
          _ => {
            // Render and visit only the chosen candidates to see why they were ambiguous.
            to_visit.extend(chosen_edges.iter().map(|edge_ref| edge_ref.target()));
            errored.insert(
              node_id,
              format!(
                "Too many sources of dependency {} for {}: {:#?}",
                dependency_key,
                node,
                chosen_edges
                  .iter()
                  .map(|edge_ref| {
                    format!(
                      "{} (for {})",
                      graph[edge_ref.target()].0.node,
                      params_str(&graph[edge_ref.target()].0.in_set)
                    )
                  })
                  .collect::<Vec<_>>()
              ),
            );
          }
        }
      }
      for edge_to_delete in edges_to_delete {
        graph[edge_to_delete].mark_deleted(EdgePrunedReason::SmallerParamSetAvailable);
      }
    }

    if errored.is_empty() {
      // Finally, return a new graph with all deleted data discarded.
      Ok(graph.filter_map(
        |_node_id, node| {
          if let Some(node) = node.inner() {
            Some(node.clone())
          } else {
            None
          }
        },
        |_edge_id, edge| {
          if let Some(edge) = edge.inner() {
            Some(*edge)
          } else {
            None
          }
        },
      ))
    } else {
      // Render the most specific errors.
      Err(Self::render_errored(&graph, errored))
    }
  }

  fn render_errored(
    graph: &MonomorphizedGraph<R>,
    errored: HashMap<NodeIndex<u32>, String>,
  ) -> String {
    // Leaf errors have no dependencies in the errored map.
    let mut leaf_errors = errored
      .iter()
      .filter(|(&node_id, _)| {
        !graph
          .neighbors_directed(node_id, Direction::Outgoing)
          .any(|dependency_id| errored.contains_key(&dependency_id) && node_id != dependency_id)
      })
      .map(|(_, error)| error.replace("\n", "\n    "))
      .collect::<Vec<_>>();

    leaf_errors.sort();

    format!(
      "Encountered {} rule graph error{}:\n  {}",
      leaf_errors.len(),
      if leaf_errors.len() == 1 { "" } else { "s" },
      leaf_errors.join("\n  "),
    )
  }

  ///
  /// Takes a Graph that has been pruned to eliminate unambiguous choices: any duplicate edges at
  /// this point are errors.
  ///
  fn finalize(self, graph: ParamsLabeledGraph<R>) -> Result<RuleGraph<R>, String> {
    log::debug!(
      "// finalizing with:\n{}",
      petgraph::dot::Dot::with_config(&graph, &[])
    );

    let entry_for = |node_id| -> Entry<R> {
      let ParamsLabeled { node, in_set, .. }: &ParamsLabeled<R> = &graph[node_id];
      match node {
        Node::Rule(rule) => Entry::WithDeps(EntryWithDeps::Inner(InnerEntry {
          params: in_set.clone(),
          rule: rule.clone(),
        })),
        Node::Query(q) => Entry::WithDeps(EntryWithDeps::Root(RootEntry(q.clone()))),
        Node::Param(p) => Entry::Param(*p),
      }
    };

    // Visit the reachable portion of the graph to create Edges, starting from roots.
    let mut rule_dependency_edges = HashMap::new();
    let mut visited = graph.visit_map();
    let mut to_visit = graph.externals(Direction::Incoming).collect::<Vec<_>>();
    while let Some(node_id) = to_visit.pop() {
      if !visited.visit(node_id) {
        continue;
      }

      // Create an entry for the node, and schedule its dependencies to be visited.
      let entry = entry_for(node_id);
      to_visit.extend(graph.neighbors_directed(node_id, Direction::Outgoing));

      // Convert the graph edges into RuleEdges: graph pruning should already have confirmed that
      // there was one dependency per DependencyKey.
      let dependencies = graph
        .edges_directed(node_id, Direction::Outgoing)
        .map(|edge_ref| (*edge_ref.weight(), vec![entry_for(edge_ref.target())]))
        .collect::<HashMap<_, _>>();

      match entry {
        Entry::WithDeps(wd) => {
          rule_dependency_edges.insert(wd, RuleEdges { dependencies });
        }
        Entry::Param(p) => {
          if !dependencies.is_empty() {
            return Err(format!(
              "Param entry for {} should not have had dependencies, but had: {:#?}",
              p, dependencies
            ));
          }
        }
      }
    }

    Ok(RuleGraph {
      queries: self.queries,
      rule_dependency_edges,
      // TODO
      unreachable_rules: Vec::default(),
    })
  }

  ///
  /// Groups the DependencyKeys of the given node (regardless of whether it is deleted) including
  /// any empty groups for any keys that were declared by the node but didn't have edges.
  ///
  #[allow(clippy::type_complexity)]
  fn edges_by_dependency_key(
    graph: &MonomorphizedGraph<R>,
    node_id: NodeIndex<u32>,
    include_deleted_dependencies: bool,
  ) -> BTreeMap<
    R::DependencyKey,
    Vec<EdgeReference<MaybeDeleted<R::DependencyKey, EdgePrunedReason>, u32>>,
  > {
    let node = &graph[node_id].0.node;
    let mut edges_by_dependency_key = node
      .dependency_keys()
      .into_iter()
      .map(|dk| (dk, vec![]))
      .collect::<BTreeMap<_, _>>();
    for edge_ref in graph.edges_directed(node_id, Direction::Outgoing) {
      if !include_deleted_dependencies
        && (edge_ref.weight().is_deleted() || graph[edge_ref.target()].is_deleted())
      {
        continue;
      }

      let dependency_key = &edge_ref.weight().0;
      edges_by_dependency_key
        .get_mut(&dependency_key)
        .unwrap_or_else(|| {
          panic!(
            "{} did not declare a dependency {}, but had an edge for it.",
            node, dependency_key
          );
        })
        .push(edge_ref);
    }
    edges_by_dependency_key
  }

  ///
  /// Calculates the in_set required to satisfy the given dependency via the given DependencyKey.
  ///
  fn dependency_in_set<'a>(
    node_id: NodeIndex<u32>,
    dependency_key: &R::DependencyKey,
    dependency_id: NodeIndex<u32>,
    dependency_in_set: &'a ParamTypes<R::TypeId>,
  ) -> Box<dyn Iterator<Item = R::TypeId> + 'a> {
    // The in_sets of the dependency, less any Params "provided" (ie "declared variables"
    // in the context of live variable analysis) by the relevant DependencyKey.
    if dependency_id == node_id {
      // A self-edge to this node does not contribute Params to its own liveness set, for two
      // reasons:
      //   1. it should always be a noop.
      //   2. any time it is _not_ a noop, it is probably because we're busying updating the
      //      liveness set, and the node contributing to its own set ends up using a stale
      //      result.
      return Box::new(std::iter::empty());
    }

    if let Some(provided_param) = dependency_key.provided_param() {
      // If the DependencyKey "provides" the Param, it does not count toward our in-set.
      Box::new(
        dependency_in_set
          .iter()
          .filter(move |p| *p != &provided_param)
          .cloned(),
      )
    } else {
      Box::new(dependency_in_set.iter().cloned())
    }
  }

  ///
  /// Calculates the in_set required to satisfy the given set of dependency edges with their
  /// in_sets.
  ///
  fn dependencies_in_set<'a>(
    node_id: NodeIndex<u32>,
    dependency_edges: impl Iterator<
      Item = (R::DependencyKey, NodeIndex<u32>, &'a ParamTypes<R::TypeId>),
    >,
  ) -> ParamTypes<R::TypeId> {
    // Union the in_sets of our dependencies, less any Params "provided" (ie "declared variables"
    // in the context of live variable analysis) by the relevant DependencyKeys.
    let mut in_set = ParamTypes::new();
    for (dependency_key, dependency_id, dependency_in_set) in dependency_edges {
      in_set.extend(Self::dependency_in_set(
        node_id,
        &dependency_key,
        dependency_id,
        dependency_in_set,
      ));
    }
    in_set
  }

  ///
  /// Given a node and a mapping of all legal sources of each of its dependencies, generates a
  /// simplified node for each legal set.
  ///
  /// Note that because ambiguities are preserved (to allow for useful errors
  /// post-monomorphization), the output is a set of dependencies which might contain multiple
  /// entries per DependencyKey.
  ///
  /// Unfortunately, we cannot eliminate dependencies based on their in_sets not being a subset of
  /// the out_set, because it's possible that the in_sets have not shrunk (transitively) to their
  /// true requirements yet. See the doc string of `monomorphize`. We _are_ able to reject
  /// dependencies that _directly_ depend on something that is not present though: either via a
  /// direct dependency on a Param node that is not present in the out_set, or a DependencyKey's
  /// provided_param that is not in the in_set of a combination.
  ///
  #[allow(clippy::type_complexity)]
  fn monomorphizations(
    graph: &MonomorphizedGraph<R>,
    node_id: NodeIndex<u32>,
    out_set: ParamTypes<R::TypeId>,
    minimal_in_set: &HashSet<NodeIndex<u32>>,
    deps: &[Vec<(R::DependencyKey, NodeIndex<u32>)>],
  ) -> HashMap<ParamsLabeled<R>, HashSet<(R::DependencyKey, NodeIndex<u32>)>> {
    let mut combinations = HashMap::new();

    // We start by computing per-dependency in_sets, and filtering out dependencies that will be
    // illegal in any possible combination.
    let filtered_deps: Vec<Vec<(R::DependencyKey, NodeIndex<u32>, ParamTypes<R::TypeId>)>> = deps
      .iter()
      .map(|choices| {
        choices
          .iter()
          .filter(|(_, dependency_id)| {
            // If the candidate is a Param, it must be present in the out_set.
            if let Node::Param(ref p) = graph[*dependency_id].0.node {
              out_set.contains(p)
            } else {
              true
            }
          })
          .map(|(dependency_key, dependency_id)| {
            let dependency_in_set = Self::dependency_in_set(
              node_id,
              &dependency_key,
              *dependency_id,
              &graph[*dependency_id].0.in_set,
            )
            .collect::<ParamTypes<_>>();
            (*dependency_key, *dependency_id, dependency_in_set)
          })
          .collect()
      })
      .collect();

    // Then generate the combinations of possibly valid deps.
    for combination in combinations_of_one(&filtered_deps) {
      // Union the pre-filtered per-dependency in_sets.
      let in_set = combination
        .iter()
        .fold(ParamTypes::new(), |mut in_set, (_, _, dep_in_set)| {
          in_set.extend(dep_in_set.iter().cloned());
          in_set
        });

      // Confirm that this combination of deps is satisfiable in terms of the in_set.
      let in_set_satisfiable = combination
        .iter()
        .all(|(dependency_key, dependency_id, _)| {
          let dependency_in_set = if *dependency_id == node_id {
            // Is a self edge: use the in_set that we're considering creating.
            &in_set
          } else {
            &graph[*dependency_id].0.in_set
          };

          // Any param provided by this key must be consumed.
          dependency_key
            .provided_param()
            .map(|p| dependency_in_set.contains(&p))
            .unwrap_or(true)
        });
      if !in_set_satisfiable {
        continue;
      }

      // Compute the out_set for this combination: any Params that are consumed here are removed
      // from the out_set that Rule dependencies will be allowed to consume. Params that weren't
      // present in the out_set were already filtered near the top of this method.
      let out_set = {
        let consumed_by_params = combination
          .iter()
          .filter_map(|(_, dependency_id, _)| match graph[*dependency_id].0.node {
            Node::Param(p) => Some(p),
            _ => None,
          })
          .collect::<ParamTypes<_>>();

        out_set
          .difference(&consumed_by_params)
          .cloned()
          .collect::<ParamTypes<R::TypeId>>()
      };

      // We can eliminate this candidate if any dependencies have minimal in_sets which contain
      // values not present in the computed out_set (meaning that they consume a Param that isn't
      // in scope). If their in_sets are not minimal, then they might shrink further in the future,
      // and so we cannot eliminate them quite yet.
      let out_set_satisfiable = combination
        .iter()
        .all(|(dk, dependency_id, dependency_in_set)| {
          matches!(graph[*dependency_id].0.node, Node::Param(_))
            || !minimal_in_set.contains(&dependency_id)
            || dependency_in_set.difference(&out_set).next().is_none()
        });
      if !out_set_satisfiable {
        continue;
      }

      // If we've made it this far, we're worth recording. Huzzah!
      let entry = ParamsLabeled {
        node: graph[node_id].0.node.clone(),
        in_set: in_set.clone(),
        // NB: See the method doc. Although our dependees could technically still provide a
        // larger set of params, anything not in the in_set is not consumed in this subgraph,
        // and the out_set shrinks correspondingly to avoid creating redundant nodes.
        out_set: out_set.intersection(&in_set).cloned().collect(),
      };
      combinations
        .entry(entry)
        .or_insert_with(HashSet::new)
        .extend(combination.into_iter().map(|(dk, di, _)| (*dk, *di)));
    }

    combinations
  }
}

///
/// Generate all combinations of one element from each input vector.
///
pub(crate) fn combinations_of_one<T: std::fmt::Debug>(
  input: &[Vec<T>],
) -> Box<dyn Iterator<Item = Vec<&T>> + '_> {
  match input.len() {
    0 => Box::new(std::iter::empty()),
    1 => Box::new(input[0].iter().map(|item| vec![item])),
    len => {
      let last_idx = len - 1;
      Box::new(input[last_idx].iter().flat_map(move |item| {
        combinations_of_one(&input[..last_idx]).map(move |mut prefix| {
          prefix.push(item);
          prefix
        })
      }))
    }
  }
}
