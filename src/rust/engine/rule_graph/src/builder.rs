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

use std::collections::{hash_map, HashMap, HashSet, VecDeque};
use std::convert::TryInto;

use indexmap::IndexSet;
use itertools::Itertools;
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::visit::{Bfs, EdgeRef, IntoNodeReferences, NodeRef, VisitMap, Visitable};
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

enum DependencyNode<R: Rule> {
  Rule(R),
  Param(R::TypeId),
}

type Graph<R> = DiGraph<Node<R>, <R as Rule>::DependencyKey, u32>;
type ParamsLabeledGraph<R> =
  DiGraph<(Node<R>, ParamTypes<<R as Rule>::TypeId>), <R as Rule>::DependencyKey, u32>;

///
/// Given the set of Rules and Queries, produce a RuleGraph that allows dependency nodes
/// to be found statically.
///
pub struct Builder<'t, R: Rule> {
  rules: &'t HashMap<R::TypeId, Vec<R>>,
  queries: Vec<Query<R>>,
  params: ParamTypes<R::TypeId>,
}

impl<'t, R: Rule> Builder<'t, R> {
  pub fn new(rules: &'t HashMap<R::TypeId, Vec<R>>, queries: Vec<Query<R>>) -> Builder<'t, R> {
    // The set of all input Params in the graph: ie, those provided either via Queries, or via
    // a Rule with a DependencyKey that provides a Param.
    let params = queries
      .iter()
      .flat_map(|query| query.params.iter().cloned())
      .chain(
        rules
          .values()
          .flatten()
          .flat_map(|rule| rule.dependency_keys())
          .filter_map(|dk| dk.provided_param()),
      )
      .collect::<ParamTypes<_>>();
    Builder {
      rules,
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
    // 3. monomorphize by copying a node (and its dependees) for each valid combination of its
    //    dependencies
    let monomorphic_live_params_graph = Self::monomorphize(polymorphic_live_params_graph);
    // 4. delete nodes that are illegal based on their final in/out sets.
    //    * if a DependencyKey does not consume a provided param, the node and all rule
    //      dependees are deleted
    let pruned_nodes_graph = self.prune_nodes(monomorphic_live_params_graph);
    // 5. choose the best dependencies via in/out sets. fail if:
    //    * invalid required param at a Query
    //    * take smallest option, fail for equal-sized sets
    let pruned_edges_graph = self.prune_edges(pruned_nodes_graph)?;
    // 6. generate the final graph for nodes reachable from queries
    self.finalize(pruned_edges_graph)
  }

  fn initial_polymorphic(&self) -> Result<Graph<R>, String> {
    let mut graph: Graph<R> = DiGraph::new();

    // Initialize the graph with nodes for all Queries, Rules, and Params.
    let queries = self
      .queries
      .iter()
      .map(|query| (query, graph.add_node(Node::Query(query.clone()))))
      .collect::<HashMap<_, _>>();
    let rules = self
      .rules
      .values()
      .flatten()
      .cloned()
      .map(|rule| (rule.clone(), graph.add_node(Node::Rule(rule))))
      .collect::<HashMap<_, _>>();
    let params = self
      .params
      .iter()
      .cloned()
      .map(|param| (param, graph.add_node(Node::Param(param))))
      .collect::<HashMap<_, _>>();

    // Starting from Queries, visit all reachable nodes in the graph.
    let mut visited = graph.visit_map();
    let mut to_visit = queries.values().cloned().collect::<Vec<_>>();
    while let Some(node_id) = to_visit.pop() {
      if !visited.visit(node_id) {
        continue;
      }

      // Visit the dependency keys of the node (if it has any).
      for dependency_key in graph[node_id].dependency_keys() {
        let candidates: Vec<DependencyNode<R>> = self.rhs(dependency_key);
        if candidates.is_empty() {
          // "No rules or queries provide type X."
          return Err("TODO".to_owned());
        }
        for candidate in candidates {
          match candidate {
            DependencyNode::Rule(r) => {
              let rule_id = rules.get(&r).unwrap();
              graph.add_edge(node_id, *rule_id, dependency_key);
              to_visit.push(*rule_id);
            }
            DependencyNode::Param(p) => {
              graph.add_edge(node_id, *params.get(&p).unwrap(), dependency_key);
            }
          }
        }
      }
    }

    Ok(graph)
  }

  ///
  /// Splits Rules in the graph that have multiple valid sources of a dependency, and recalculates
  /// their live variables to attempt to re-join with other copies of the Rule with identical sets.
  /// Similar to `live_param_labeled_graph`, this is an analysis that propagates "up" the graph
  /// from dependencies to dependees (and maintains the live param sets initialized by
  /// `live_param_labeled_graph` while doing so). Visiting a node might cause us to split it and
  /// re-calculate the live params sets for each split; we then visit the dependees of the split
  /// nodes to ensure that they are visited as well, and so on.
  ///
  /// Any node that has a dependency that does not consume a provided param will be removed (which
  /// may also cause its dependees to be removed, for the same reason). This is safe to do at any
  /// time during the monomorphize run, because the liveness sets only shrink over time: if a
  /// dependency does not consume a provided param with the overapproximated set, it won't with any
  /// smaller set either.
  ///
  /// The exit condition for this phase is that all nodes have their final, accurate param usage sets,
  /// because all splits that result in smaller param sets for a node will have been executed. BUT,
  /// it might still be the case that a node has multiple sources of a particular dependency with
  /// the _same_ param requirements. This represents ambiguity that must be handled (likely by
  /// erroring) in later phases.
  ///
  fn monomorphize(mut graph: ParamsLabeledGraph<R>) -> ParamsLabeledGraph<R> {
    // We need to visit all nodes in the graph, but because monomorphizing a node enqueues its
    // dependees we may visit some of them multiple times. We use a set as the to_visit collection
    // because each visit clears the need to re-visit unless another dependency enqueues it _after_
    // it has been visited.
    let mut to_visit = graph
      .node_references()
      .map(|node_ref| node_ref.id())
      .collect::<IndexSet<_>>();
    // As we go, we record which nodes to delete, but we wait until the end to delete them, as it
    // will cause NodeIds to shift in the graph (and is only cheap to do in bulk).
    let mut to_delete = HashSet::new();

    // As we split Rules, we attempt to re-join with existing identical Rule nodes to avoid an
    // explosion.
    let mut rules: HashMap<(Node<R>, ParamTypes<_>), _> = graph
      .node_references()
      .filter_map(|node_ref| match node_ref.weight().0 {
        Node::Rule(_) => Some((node_ref.weight().clone(), node_ref.id())),
        _ => None,
      })
      .collect();

    println!(
      "Monomorphizing with: {:?}",
      petgraph::dot::Dot::with_config(&graph, &[])
    );

    while let Some(node_id) = to_visit.pop() {
      if to_delete.contains(&node_id) {
        continue;
      }
      if !matches!(&graph[node_id].0, Node::Rule(_)) {
        continue;
      }

      // If any DependencyKey has multiple (live/not-deleted) sources, the Rule needs to be
      // monomorphized/duplicated.
      let edges_by_dependency_key: Vec<(R::DependencyKey, Vec<_>)> = {
        let mut sorted_edges = graph
          .edges_directed(node_id, Direction::Outgoing)
          .collect::<Vec<_>>();
        sorted_edges.sort_by_key(|edge_ref| edge_ref.weight());
        sorted_edges
          .into_iter()
          .group_by(|edge_ref| edge_ref.weight())
          .into_iter()
          .map(|(dependency_key, edge_refs)| {
            let dependency_ids = edge_refs
              .filter(|edge_ref| {
                // Filter out the dependency if the in_set of the dependency node does not consume a
                // provided param. Since the "used parameter" sets of nodes only shrink as
                // monomorphize runs, it's always safe to eliminate a potential dependency this way.
                let consumes_provided =
                  if let Some(provided_param) = dependency_key.provided_param() {
                    graph[edge_ref.target()].1.contains(&provided_param)
                  } else {
                    true
                  };
                consumes_provided && !to_delete.contains(&edge_ref.target())
              })
              .map(|edge_ref| edge_ref.target())
              .collect();
            (*dependency_key, dependency_ids)
          })
          .collect()
      };

      if edges_by_dependency_key
        .iter()
        .all(|(_, dependency_ids)| dependency_ids.len() == 1)
      {
        // This node is already monomorphic: dependencies may have changed though, so confirm
        // that its liveness set is up to date. If it isn't, we'll fall through to monomorphize it,
        // which will handle the update and potential merge with an existing node.
        let new_in_set = Self::live_params(
          &graph,
          node_id,
          graph
            .edges_directed(node_id, Direction::Outgoing)
            .map(|edge_ref| (*edge_ref.weight(), edge_ref.target())),
        );
        if graph[node_id].1 == new_in_set {
          /*
          println!(
            ">>> already monomorphic {:?} with accurate liveness.",
            graph[node_id]
          );
          */
          continue;
        } else {
          /*
          println!(
            ">>> already monomorphic {:?}, but needs liveness updates.",
            graph[node_id]
          );
          */
        }
      }

      /*
      println!(
        ">>> visiting {:?} for {:?}",
        edges_by_dependency_key
          .iter()
          .map(|edges| edges.len())
          .collect::<Vec<_>>(),
        graph[node_id]
      );
      */

      // Needs changes. Add dependees to the list of nodes to visit, and this node to the
      // list of nodes to be deleted.
      let dependee_edges = graph
        .edges_directed(node_id, Direction::Incoming)
        .map(|edge_ref| (edge_ref.source(), *edge_ref.weight()))
        .collect::<Vec<_>>();
      to_visit.extend(dependee_edges.iter().map(|(dependee_id, _)| dependee_id));
      to_delete.insert(node_id);
      rules.remove(&graph[node_id]);

      // Generate a replacement node per valid monomorphization of this rule.
      let mut modified_existing_nodes = HashSet::new();
      for combination in
        Self::monomorphizations(&graph, &graph[node_id].1, &edges_by_dependency_key)
      {
        // Compute a live variable set for this combination of deps, and see whether there is
        // an existing copy of this Rule with those live_params.
        let live_params = Self::live_params(
          &graph,
          node_id,
          combination.iter().map(|(dk, di)| (dk.clone(), di.clone())),
        );
        /*
        println!(
          ">>>   {} generating permutation for {} that consumes: {:#?}",
          graph[node_id].0,
          crate::params_str(&live_params),
          combination
            .iter()
            .map(|(dk, di)| format!(
              "{} from ({} with {})",
              dk,
              graph[*di].0,
              crate::params_str(&graph[*di].1)
            ))
            .collect::<Vec<_>>()
        );
        */
        let (replacement_id, is_new_node) =
          match rules.entry((graph[node_id].0.clone(), live_params.clone())) {
            hash_map::Entry::Occupied(oe) => (*oe.get(), false),
            hash_map::Entry::Vacant(ve) => (
              *ve.insert(graph.add_node((graph[node_id].0.clone(), live_params.clone()))),
              true,
            ),
          };

        // Give all dependees edges to the chosen node for this combo.
        for (dependee_id, dependency_key) in &dependee_edges {
          // NB: For existing nodes, confirm that we are not creating a duplicate edge.
          if is_new_node
            || graph
              .edges_directed(*dependee_id, Direction::Outgoing)
              .all(|edge_ref| {
                edge_ref.target() != replacement_id || edge_ref.weight() != dependency_key
              })
          {
            graph.add_edge(*dependee_id, replacement_id, *dependency_key);
          }
        }

        // And give it edges to this combination of dependencies (while confirming that we don't
        // create dupes).
        let existing_edges = graph
          .edges_directed(replacement_id, Direction::Outgoing)
          .map(|edge_ref| (*edge_ref.weight(), edge_ref.target()))
          .collect::<HashSet<_>>();
        for (dependency_key, dependency_id) in combination {
          // NB: When a node depends on itself, we adjust the destination of that self-edge to point to
          // the new node.
          let dependency_id = if dependency_id == node_id {
            replacement_id
          } else {
            dependency_id
          };
          if !existing_edges.contains(&(dependency_key, dependency_id)) {
            if !is_new_node {
              modified_existing_nodes.insert(replacement_id);
            }
            graph.add_edge(replacement_id, dependency_id, dependency_key);
          }
        }
      }

      // If we modified any existing nodes, we revisit them unless they had the same live params
      // set as our input. Because we "deleted" our input node before running, any combinations that
      // resulted in collisions back to that same set represent ambiguities, either:
      //   1. temporarily, because some of our dependencies did not have their final liveness sets
      //      because they had not been visited yet. they are guaranteed to be visited eventually
      //      though, and our replacement node will be too because it depends on them
      //   2. permanently, because there is ambiguity that cannot be resolved by this phase, in
      //      which case we leave it the graph to be resolved by the pruning phases
      // In either case, it is fruitless to revisit those nodes, so we ignore them here. See the
      // method docstring.
      to_visit.extend(
        modified_existing_nodes
          .into_iter()
          .filter(|existing_node_id| {
            let visit = graph[*existing_node_id].1 != graph[node_id].1;
            if visit {
              println!(
                ">>> enqueueing existing node to be visited {:?}",
                existing_node_id
              );
            }
            visit
          }),
      );
    }

    // Finally, delete all nodes that were replaced (which will also delete their edges).
    graph.filter_map(
      |node_id, node| {
        if to_delete.is_visited(&node_id) {
          None
        } else {
          Some(node.clone())
        }
      },
      |_, edge_weight| Some(*edge_weight),
    )
  }

  ///
  /// Execute live variable analysis to determine which Params are used by which nodes.
  ///
  /// See https://en.wikipedia.org/wiki/Live_variable_analysis
  ///
  fn live_param_labeled_graph(&self, graph: Graph<R>) -> ParamsLabeledGraph<R> {
    // Add in and out sets for each node, with the only non-empty sets initially being the in-set
    // for Params which represent the "usage" of a Param, and the params provided by a Query as its
    // in-set.
    let mut graph: ParamsLabeledGraph<R> = graph.map(
      |_node_id, node| match node {
        Node::Rule(r) => (Node::Rule(r.clone()), ParamTypes::new()),
        Node::Query(q) => (Node::Query(q.clone()), q.params.clone()),
        Node::Param(p) => {
          let mut in_set = ParamTypes::new();
          in_set.insert(*p);
          (Node::Param(*p), in_set)
        }
      },
      |_edge_id, edge_weight| *edge_weight,
    );

    // Starting from leaves of the graph, propagate used Params through nodes. To minimize
    // the total number of visits, we walk breadth first with a queue.
    let mut to_visit = graph
      .externals(Direction::Outgoing)
      .collect::<VecDeque<_>>();
    while let Some(node_id) = to_visit.pop_front() {
      let new_in_set = match &graph[node_id] {
        (Node::Rule(_), in_set) => {
          // If our new in_set is different from our old in_set, update it and schedule our
          // dependees.
          let new_in_set = Self::live_params(
            &graph,
            node_id,
            graph
              .edges_directed(node_id, Direction::Outgoing)
              .map(|edge_ref| (*edge_ref.weight(), edge_ref.target())),
          );
          if in_set != &new_in_set {
            to_visit.extend(graph.neighbors_directed(node_id, Direction::Incoming));
            Some(new_in_set)
          } else {
            None
          }
        }
        (Node::Param(_), _) => {
          // Params are always leaves with an in-set of their own value, and no out-set. Visiting a
          // Param means just kicking off visits to all of its predecessors.
          to_visit.extend(graph.neighbors_directed(node_id, Direction::Incoming));
          continue;
        }
        (Node::Query(_), _) => {
          // Queries are always roots with an out-set of the Params that can be computed based on
          // the Rule(s) that they depend on. We do not validate Queries during this phase of graph
          // construction: potential ambiguity is resolved later during pruning.
          continue;
        }
      };

      if let Some(in_set) = new_in_set {
        graph[node_id].1 = in_set;
      }
    }

    graph
  }

  ///
  /// After nodes are all labeled with their in/out Param sets, we eliminate any monomorphized
  /// Rules that did not satisfy the requirement that the provided param of a DependencyKey needs
  /// to be used.
  ///
  fn prune_nodes(&self, graph: ParamsLabeledGraph<R>) -> ParamsLabeledGraph<R> {
    let mut to_visit = graph
      .node_references()
      .map(|node_ref| node_ref.id())
      .collect::<Vec<_>>();
    // We keep a reversed copy of the graph to use for deleting dependees transitively.
    let reversed_graph = {
      let mut rg = graph.clone();
      rg.reverse();
      rg
    };

    // Uses the same lazy deletion strategy as monomorphize.
    let mut to_delete = graph.visit_map();

    println!(
      "Pruning nodes with: {:?}",
      petgraph::dot::Dot::with_config(&graph, &[])
    );

    while let Some(node_id) = to_visit.pop() {
      if to_delete.is_visited(&node_id) {
        continue;
      }

      // Validate that for each dependency, the in_set of the dependency node consumes the provided
      // param.
      let valid_dependencies = graph
        .edges_directed(node_id, Direction::Outgoing)
        .all(|edge_ref| {
          if let Some(provided_param) = edge_ref.weight().provided_param() {
            graph[edge_ref.target()].1.contains(&provided_param)
          } else {
            true
          }
        });
      if valid_dependencies {
        continue;
      }

      // Otherwise, this node (and all rules that depend on it) should be deleted.
      let mut dependees = Bfs::new(&reversed_graph, node_id);
      while let Some(dependee_id) = dependees.next(&graph) {
        if !to_delete.is_visited(&dependee_id) && matches!(&graph[dependee_id].0, Node::Rule(_)) {
          to_delete.visit(dependee_id);
        }
      }
    }

    // Finally, delete all nodes that were invalidated.
    graph.filter_map(
      |node_id, node| {
        if to_delete.is_visited(&node_id) {
          None
        } else {
          Some(node.clone())
        }
      },
      |_, edge_weight| Some(*edge_weight),
    )
  }

  ///
  /// After nodes have been pruned, all remaining nodes are valid, and we can statically decide
  /// which source of each DependencyKey a Node should use, and prune edges to the rest.
  ///
  fn prune_edges(&self, graph: ParamsLabeledGraph<R>) -> Result<ParamsLabeledGraph<R>, String> {
    // Edge removal is expensive, so we wait until the end of iteration to do it, and filter
    // dead edges while running.
    let mut edges_to_delete = HashSet::new();

    println!(
      "Pruning edges with: {:?}",
      petgraph::dot::Dot::with_config(&graph, &[])
    );

    // Walk from roots, choosing one source for each DependencyKey of each node.
    let mut visited = graph.visit_map();
    let mut to_visit = graph.externals(Direction::Incoming).collect::<Vec<_>>();
    while let Some(node_id) = to_visit.pop() {
      if !visited.visit(node_id) {
        continue;
      }
      let node = &graph[node_id].0;

      // * "no choice of rule that consumes param X" here (ie it's both GEN'd and KILL'd within the node)
      // * invalid required param at a Query
      // * take smallest option, fail for equal-sized sets

      let edges_by_dependency_key = {
        let mut sorted_edges = graph
          .edges_directed(node_id, Direction::Outgoing)
          .collect::<Vec<_>>();
        sorted_edges.sort_by_key(|edge_ref| edge_ref.weight());
        sorted_edges
          .into_iter()
          .group_by(|edge_ref| edge_ref.weight())
      };
      for (dependency_key, edge_refs) in &edges_by_dependency_key {
        // Collect live edges.
        let live_edge_refs = edge_refs
          .filter(|edge_ref| !edges_to_delete.contains(&edge_ref.id()))
          .collect::<Vec<_>>();

        // Filter out any that are not satisfiable for this node based on its type and in/out sets.
        let relevant_edge_refs: Vec<_> = match node {
          Node::Query(q) => {
            // Only dependencies with in_sets that are a subset of our params can be used.
            live_edge_refs
              .iter()
              .filter(|edge_ref| {
                let dependency_in_set = &graph[edge_ref.target()].1;
                dependency_in_set.is_subset(&q.params)
              })
              .collect()
          }
          Node::Rule(_) => {
            // If there is a provided param, only dependencies that consume it can be used.
            live_edge_refs
              .iter()
              .filter(|edge_ref| {
                if let Some(provided_param) = dependency_key.provided_param() {
                  graph[edge_ref.target()].1.contains(&provided_param)
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
              live_edge_refs
                .iter()
                .map(|edge_ref| format!("{}", graph[edge_ref.target()].0))
                .collect::<Vec<_>>()
            );
          }
        };

        // We prefer the dependency with the smallest set of input Params, as that minimizes Rule
        // identities in the graph and biases toward receiving values from dependencies (which do not
        // affect our identity) rather than dependents.
        /*
        println!(
          ">>> for {} at {}, choosing from {:#?}",
          node,
          dependency_key,
          relevant_edge_refs
            .iter()
            .map(|edge_ref| format!("{}", graph[edge_ref.target()].0))
            .collect::<Vec<_>>()
        );
        */
        let chosen_edges = {
          let mut minimum_param_set_size = ::std::usize::MAX;
          let mut chosen_edges = Vec::new();
          for edge_ref in relevant_edge_refs {
            let param_set_size = graph[edge_ref.target()].1.len();
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
            // Schedule this dependency to be visited, and Mark all other choices deleted.
            let chosen_edge = chosen_edges[0];
            to_visit.push(chosen_edge.target());
            edges_to_delete.extend(
              live_edge_refs
                .iter()
                .map(|edge_ref| edge_ref.id())
                .filter(|edge_ref_id| *edge_ref_id != chosen_edge.id()),
            );
          }
          0 => {
            return Err(format!(
              "TODO: No source of dependency {} for {}. All potential sources were \
                    eliminated: {:#?}",
              dependency_key,
              node,
              live_edge_refs
                .iter()
                .map(|edge_ref| {
                  format!(
                    "{} (needed {})",
                    graph[edge_ref.target()].0,
                    crate::params_str(&graph[edge_ref.target()].1)
                  )
                })
                .collect::<Vec<_>>()
            ));
          }
          _ => {
            return Err(format!(
              "TODO: Too many sources of dependency {} for {}: {:#?}",
              dependency_key,
              node,
              chosen_edges
                .iter()
                .map(|edge_ref| format!("{}", graph[edge_ref.target()].0))
                .collect::<Vec<_>>()
            ));
          }
        }
      }
    }

    // Finally, return a new graph with pruned edges.
    Ok(graph.filter_map(
      |_node_id, node| Some(node.clone()),
      |edge_id, edge_weight| {
        if edges_to_delete.contains(&edge_id) {
          None
        } else {
          Some(*edge_weight)
        }
      },
    ))
  }

  ///
  /// Takes a Graph that has been pruned to eliminate unambiguous choices: any duplicate edges at
  /// this point are errors.
  ///
  fn finalize(self, pruned_graph: ParamsLabeledGraph<R>) -> Result<RuleGraph<R>, String> {
    let graph = pruned_graph;

    let entry_for = |node_id| -> Entry<R> {
      let (node, in_set): &(Node<R>, ParamTypes<R::TypeId>) = &graph[node_id];
      match node {
        Node::Rule(rule) => Entry::WithDeps(EntryWithDeps::Inner(InnerEntry {
          params: in_set.clone(),
          rule: rule.clone(),
        })),
        Node::Query(q) => Entry::WithDeps(EntryWithDeps::Root(RootEntry(q.clone()))),
        Node::Param(p) => Entry::Param(*p),
      }
    };

    println!(
      "Finalizing with: {:?}",
      petgraph::dot::Dot::with_config(&graph, &[])
    );

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
      unfulfillable_rules: HashMap::default(),
      // TODO
      unreachable_rules: Vec::default(),
    })
  }

  ///
  /// Calculates the "live params" (live variables) that are required to satisfy the given set of
  /// dependency edges.
  ///
  fn live_params(
    graph: &ParamsLabeledGraph<R>,
    node_id: NodeIndex<u32>,
    dependency_edges: impl Iterator<Item = (R::DependencyKey, NodeIndex<u32>)>,
  ) -> ParamTypes<R::TypeId> {
    // Union the live sets of our dependencies, less any Params "provided" (ie "declared variables"
    // in the context of live variable analysis) by the relevant DependencyKeys.
    dependency_edges
      .flat_map(|(dependency_key, dependency_id)| {
        if dependency_id == node_id {
          // A self-edge to this node does not contribute Params to its own liveness set, for two
          // reasons:
          //   1. it should always be a noop.
          //   2. any time it is _not_ a noop, it is probably because we're busying updating the
          //      liveness set, and the node contributing to its own set ends up using a stale
          //      result.
          Box::new(std::iter::empty())
        } else if let Some(provided_param) = dependency_key.provided_param() {
          // If the DependencyKey "provides" the Param, it does not count toward our in-set.
          Box::new(
            graph[dependency_id]
              .1
              .iter()
              .filter(move |p| *p != &provided_param)
              .cloned(),
          )
        } else {
          let iter: Box<dyn Iterator<Item = R::TypeId>> =
            Box::new(graph[dependency_id].1.iter().cloned());
          iter
        }
      })
      .collect()
  }

  ///
  /// Given an Entry and a mapping of all legal sources of each of its dependencies, generates a
  /// simplified Entry for each legal combination of parameters.
  ///
  /// Computes the union of all parameters used by the dependencies, and then uses the powerset of
  /// used parameters to filter the possible combinations of dependencies.
  ///
  fn monomorphizations(
    graph: &ParamsLabeledGraph<R>,
    all_available_params: &ParamTypes<R::TypeId>,
    deps: &[(R::DependencyKey, Vec<NodeIndex<u32>>)],
  ) -> Vec<Vec<(R::DependencyKey, NodeIndex<u32>)>> {
    // For the powerset of used parameters (in ascending order by set size), determine which
    // dependency combinations are satisfiable.
    let used_params_size: u8 = all_available_params.len().try_into().unwrap_or_else(|_| {
      panic!(
        "Cannot operate on more than 256 consumed parameters: {}",
        params_str(
          &all_available_params
            .iter()
            .cloned()
            .collect::<ParamTypes<_>>()
        )
      );
    });
    let mut combinations: Vec<(i64, Vec<Vec<(R::DependencyKey, NodeIndex<u32>)>>)> = Vec::new();
    for available_params_bits in Powerset::new(used_params_size) {
      // If a subset of these parameters is already satisfied, skip. This has the effect of
      // selecting the smallest sets of parameters that will satisfy a rule.
      // NB: This scan over satisfied sets is linear, but should have a small N.
      let already_satisfied = combinations.iter().any(|&(satisfied_params_bits, _)| {
        // Is a subset if "subtracting" the bits of the superset results in the empty set.
        satisfied_params_bits & !available_params_bits == 0
      });
      if already_satisfied {
        continue;
      }

      // We haven't seen this combination before: compute the actual parameter values, and then
      // choose valid combinations of dependencies.
      let available_params = all_available_params
        .iter()
        .enumerate()
        .filter_map(|(idx, typeid)| {
          if available_params_bits & (1 << idx) == 0 {
            None
          } else {
            Some(*typeid)
          }
        })
        .collect();
      // TODO: We don't currently allow for ambiguity here (ambiguous entries are logged and
      // dropped), but we should (using the `combinations_of_one` code), and generate the
      // node for later inspection.
      let chosen_dependencies = Self::choose_dependencies(graph, &available_params, deps);
      if !chosen_dependencies.is_empty() {
        combinations.push((available_params_bits, chosen_dependencies));
      }
    }

    combinations
      .into_iter()
      .flat_map(|(_, combinations)| combinations)
      .collect()
  }

  ///
  /// Given a set of available Params, choose one combination of satisfiable dependencies if it
  /// exists (it may not, because we're searching for sets of legal parameters in the powerset
  /// of all used params).
  ///
  /// NB: There is no need to confirm that a provided param is consumed, because all dependencies
  /// have already been filtered for that case.
  ///
  fn choose_dependencies<'a>(
    graph: &ParamsLabeledGraph<R>,
    available_params: &ParamTypes<R::TypeId>,
    deps: &[(R::DependencyKey, Vec<NodeIndex<u32>>)],
  ) -> Vec<Vec<(R::DependencyKey, NodeIndex<u32>)>> {
    let mut combination = Vec::new();
    for (key, dependency_ids) in deps {
      let satisfiable_dependency_ids = dependency_ids
        .iter()
        .filter(|&dependency_id| graph[*dependency_id].1.is_subset(available_params))
        .collect::<Vec<_>>();

      if satisfiable_dependency_ids.is_empty() {
        // No source of a dependency was satisfiable with these Params.
        return vec![];
      } else if satisfiable_dependency_ids.len() == 1 {
        combination.push((*key, *satisfiable_dependency_ids[0]));
        continue;
      }

      // Choose the non-ambiguous entry with the smallest set of Params, as that minimizes Node
      // identities in the graph and biases toward receiving values from dependencies (which do not
      // affect our identity) rather than dependents.
      let mut minimum_param_set_size = ::std::usize::MAX;
      let mut smallest_satisfiable_ids = Vec::new();
      for satisfiable_id in satisfiable_dependency_ids {
        let param_set_size = graph[*satisfiable_id].1.len();
        if param_set_size < minimum_param_set_size {
          smallest_satisfiable_ids.clear();
          smallest_satisfiable_ids.push(satisfiable_id);
          minimum_param_set_size = param_set_size;
        } else if param_set_size == minimum_param_set_size {
          smallest_satisfiable_ids.push(satisfiable_id);
        }
      }

      match smallest_satisfiable_ids.len() {
        1 => {
          combination.push((*key, *smallest_satisfiable_ids[0]));
        }
        0 => {
          return vec![];
        }
        _ => {
          println!(">>> TODO: ambiguity.");
          return vec![];
        }
      }
    }

    vec![combination]
  }

  ///
  /// Create Nodes that might be able to provide the given product type.
  ///
  fn rhs(&self, dependency_key: R::DependencyKey) -> Vec<DependencyNode<R>> {
    let mut entries = Vec::new();
    // If the params can provide the type directly, add that.
    if dependency_key.provided_param().is_none() && self.params.contains(&dependency_key.product())
    {
      entries.push(DependencyNode::Param(dependency_key.product()));
    }
    // If there are any rules which can produce the desired type, add them.
    if let Some(matching_rules) = self.rules.get(&dependency_key.product()) {
      entries.extend(
        matching_rules
          .iter()
          .map(|rule| DependencyNode::Rule(rule.clone())),
      );
    }
    entries
  }
}

///
/// Iterates over all combinations of the given set size in ascending order.
///
pub struct Powerset {
  pop_count: u8,
  block_size: u8,
  permutations_for_pop_count: Permutations,
}

impl Powerset {
  pub fn new(block_size: u8) -> Powerset {
    Powerset {
      pop_count: 0,
      block_size,
      // NB: Initialized for popcount 1, since a popcount of 0 isn't legal, and is handled in
      // the loop body.
      permutations_for_pop_count: Permutations::new(1, block_size),
    }
  }
}

impl Iterator for Powerset {
  type Item = i64;

  fn next(&mut self) -> Option<Self::Item> {
    if self.pop_count == 0 {
      self.pop_count += 1;
      // The empty set.
      return Some(0);
    }

    loop {
      if self.pop_count > self.block_size {
        return None;
      }

      let next = self.permutations_for_pop_count.next();
      if next.is_some() {
        return next;
      } else {
        // Start iterating over the permutations of the next set size.
        self.pop_count += 1;
        self.permutations_for_pop_count = Permutations::new(self.pop_count, self.block_size);
      }
    }
  }
}

///
/// An iterator that generates all permutations with a particular size as a bitset in an i64.
///
/// Based on https://alexbowe.com/popcount-permutations/
///
struct Permutations {
  v: i64,
  initial: i64,
  block_mask: i64,
}

impl Permutations {
  fn new(pop_count: u8, block_size: u8) -> Permutations {
    assert!(pop_count > 0);
    let initial = Self::first_perm(pop_count);
    let block_mask = Self::first_perm(block_size);
    Permutations {
      v: initial,
      initial,
      block_mask,
    }
  }

  ///
  /// Generates the first permutation with a given count of set bits, which is used to generate
  /// the rest.
  ///
  fn first_perm(c: u8) -> i64 {
    (1_i64 << c) - 1_i64
  }

  ///
  /// Generate the next permutation with a given amount of set bits,
  /// given the previous lexicographical value.
  ///
  /// Taken from http://graphics.stanford.edu/~seander/bithacks.html
  ///
  fn next_perm(v: i64) -> i64 {
    let t = (v | (v - 1)) + 1;
    t | ((((t & -t) / (v & -v)) >> 1) - 1)
  }
}

impl Iterator for Permutations {
  type Item = i64;

  fn next(&mut self) -> Option<Self::Item> {
    if self.v >= self.initial {
      let result = self.v;
      self.v = Self::next_perm(self.v) & self.block_mask;
      Some(result)
    } else {
      None
    }
  }
}
