// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::rules::{CallSignature, DependencyKey, ParamTypes, Query, Rule, RuleId};
use crate::{
    params_str, Entry, EntryWithDeps, Reentry, RootEntry, RuleEdges, RuleEntry, RuleGraph,
};

use std::borrow::Cow;
use std::collections::{BTreeMap, VecDeque};

use fnv::{FnvHashMap as HashMap, FnvHashSet as HashSet};
use indexmap::IndexSet;
use internment::Intern;
use itertools::Itertools;
use petgraph::graph::{DiGraph, EdgeReference, NodeIndex};
use petgraph::visit::{DfsPostOrder, EdgeRef, IntoNodeReferences, NodeRef, VisitMap, Visitable};
use petgraph::Direction;

#[derive(Debug, Eq, PartialEq, Hash, Clone)]
enum Node<R: Rule> {
    // A root node in the rule graph.
    Query(Query<R::TypeId>),
    // An inner node in the rule graph.
    Rule {
        rule: R,
        // The number of explicit positional args that were passed (and thus don't need to be
        // solved for in the rule graph).
        explicit_args_arity: u16,
    },
    // An inner node in the rule graph which must first locate its `in_scope_params`, and will then
    // execute the given Query.
    //
    // This is a leaf rather than an actual connection to the Query node to avoid introducing
    // unnecessary graph cycles.
    Reentry(Query<R::TypeId>, ParamTypes<R::TypeId>),
    // A leaf node in the rule graph which is satisfied by consuming a single parameter.
    Param(R::TypeId),
}

impl<R: Rule> std::fmt::Display for Node<R> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Node::Query(q) => write!(f, "{q}"),
            Node::Rule {
                rule,
                explicit_args_arity,
            } => {
                let explicit_args_arity: Cow<str> = if *explicit_args_arity > 0 {
                    format!(" <{}>", explicit_args_arity).into()
                } else {
                    "".into()
                };
                write!(f, "{rule}{explicit_args_arity}")
            }
            Node::Param(p) => write!(f, "Param({p})"),
            Node::Reentry(q, in_scope) => {
                write!(f, "Reentry({}, {})", q.product, params_str(in_scope))
            }
        }
    }
}

impl<R: Rule> Node<R> {
    fn dependency_keys(&self) -> Vec<DependencyKey<R::TypeId>> {
        // TODO: Give Query an internal DependencyKey to avoid cloning here.
        match self {
            Node::Rule {
                rule,
                explicit_args_arity,
            } => rule
                .dependency_keys(*explicit_args_arity)
                .into_iter()
                .cloned()
                .collect(),
            Node::Reentry(_, in_scope_params) => in_scope_params
                .iter()
                .cloned()
                .map(DependencyKey::new)
                .collect(),
            Node::Query(q) => vec![DependencyKey::new(q.product)],
            Node::Param(_) => vec![],
        }
    }

    ///
    /// Add the parameter types which are always required to satisfy this Node (regardless of what
    /// its dependencies require) to the given set.
    ///
    fn add_inherent_in_set(&self, in_set: &mut ParamTypes<R::TypeId>) {
        match self {
            Node::Reentry(query, in_scope_params) => {
                // Reentry nodes include in_sets computed from their Query and their dependencies.
                in_set.extend(
                    query
                        .params
                        .iter()
                        .filter(|p| !in_scope_params.contains(p))
                        .cloned(),
                );
            }
            Node::Param(p) => {
                // Params are always leaves with an in-set of their own value, and no out-set.
                in_set.insert(*p);
            }
            Node::Rule { .. } | Node::Query(_) => {
                // Rules and Queries only have in_sets computed from their dependencies.
            }
        }
    }
}

///
/// A Node labeled with Param types that are declared (by its transitive dependents) for consumption,
/// and Param types that are actually (by its transitive dependencies) consumed.
///
#[derive(Debug, Eq, PartialEq, Hash, Clone)]
struct ParamsLabeled<R: Rule> {
    node: Node<R>,
    // Params that are actually consumed by transitive dependencies.
    in_set: ParamTypes<R::TypeId>,
    // Params that the Node's transitive dependents have available for consumption.
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
            write!(f, "Deleted(reason: {:?}, {})", reason, self.0)
        } else {
            write!(f, "{}", self.0)
        }
    }
}

#[derive(Debug, Eq, PartialEq, Hash, Clone, Copy)]
enum NodePrunedReason {
    Ambiguous,
    Monomorphized,
    NoDependents,
    NoSourceOfParam,
    NoValidCombinationsOfDependencies,
}

#[derive(Debug, Eq, PartialEq, Hash, Clone, Copy)]
enum EdgePrunedReason {
    DoesNotConsumeProvidedParam,
    SmallerParamSetAvailable,
}

// Nodes labeled with out_sets.
type Graph<R> =
    DiGraph<(Node<R>, ParamTypes<<R as Rule>::TypeId>), DependencyKey<<R as Rule>::TypeId>, u32>;
// Nodes labeled with out_sets and possibly marked deleted.
type OutLabeledGraph<R> = DiGraph<
    MaybeDeleted<(Node<R>, ParamTypes<<R as Rule>::TypeId>), NodePrunedReason>,
    DependencyKey<<R as Rule>::TypeId>,
    u32,
>;
// Nodes labeled with both an out_set and in_set, and possibly marked deleted.
type LabeledGraph<R> = DiGraph<
    MaybeDeleted<ParamsLabeled<R>, NodePrunedReason>,
    DependencyKey<<R as Rule>::TypeId>,
    u32,
>;
// Nodes labeled with both out_sets and in_sets, and both edges and nodes possibly marked deleted.
type MonomorphizedGraph<R> = DiGraph<
    MaybeDeleted<ParamsLabeled<R>, NodePrunedReason>,
    MaybeDeleted<DependencyKey<<R as Rule>::TypeId>, EdgePrunedReason>,
    u32,
>;
// Node labeled with in_sets.
type InLabeledGraph<R> =
    DiGraph<(Node<R>, ParamTypes<<R as Rule>::TypeId>), DependencyKey<<R as Rule>::TypeId>, u32>;

///
/// Given the set of Rules and Queries, produce a RuleGraph that allows dependency nodes
/// to be found statically.
///
pub struct Builder<R: Rule> {
    rules: BTreeMap<R::TypeId, Vec<R>>,
    queries: IndexSet<Query<R::TypeId>>,
    params: ParamTypes<R::TypeId>,
}

impl<R: Rule> Builder<R> {
    pub fn new(rules: IndexSet<R>, mut queries: IndexSet<Query<R::TypeId>>) -> Builder<R> {
        // Extend the Queries with those assumed by Reentry nodes.
        queries.extend(rules.iter().flat_map(|rule| {
            rule.dependency_keys(0)
                .into_iter()
                .filter_map(|dk| dk.as_reentry_query())
        }));

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
                    .flat_map(|rule| rule.dependency_keys(0))
                    .flat_map(|dk| dk.provided_params.iter().cloned()),
            )
            .collect::<ParamTypes<_>>();

        Builder {
            rules: rules_by_type,
            queries,
            params,
        }
    }

    pub fn graph(self) -> Result<RuleGraph<R>, String> {
        // 0. validate that the rules all have unique rule ids.
        self.validate_rule_ids()?;
        // 1. build a polymorphic graph, where nodes might have multiple legal sources of dependencies
        let initial_polymorphic_graph = self.initial_polymorphic();
        // 2. run live variable analysis on the polymorphic graph to gather a conservative (ie, overly
        //    large) set of used Params.
        let polymorphic_live_params_graph =
            self.live_param_labeled_graph(initial_polymorphic_graph);
        // 3. monomorphize by partitioning a node (and its dependents) for each valid combination of its
        //    dependencies while mantaining liveness sets.
        let monomorphic_live_params_graph = Self::monomorphize(polymorphic_live_params_graph);
        // 4. choose the best dependencies via in/out sets. fail if:
        //    * invalid required param at a Query
        //    * take smallest option, fail for equal-sized sets
        let pruned_edges_graph = self.prune_edges(monomorphic_live_params_graph)?;
        // 5. generate the final graph for nodes reachable from queries
        self.finalize(pruned_edges_graph)
    }

    ///
    /// Validate that all rules have unique RuleIds.
    ///
    fn validate_rule_ids(&self) -> Result<(), String> {
        let mut invalid_rule_ids: Vec<&RuleId> = self
            .rules
            .values()
            .flatten()
            .map(|rule| rule.id())
            .duplicates()
            .collect();
        match invalid_rule_ids.len() {
            0 => Ok(()),
            _ => {
                invalid_rule_ids.sort();
                Err(format!(
                    "The following rule ids were each used by more than one rule: {}",
                    invalid_rule_ids.iter().join(", ")
                ))
            }
        }
    }

    ///
    /// Builds a polymorphic graph while computing an out_set for each node in the graph by accounting
    /// for which `Param`s are available at each use site. During this phase, nodes may have multiple
    /// dependency edges per `DependencyKey`, which is what makes them "polymorphic". Each of the
    /// possible ways to compute a dependency will likely have different input `Param` requirements,
    /// and each node in this phase represents all of those possibilities.
    ///
    fn initial_polymorphic(&self) -> OutLabeledGraph<R> {
        let mut graph: Graph<R> = DiGraph::new();

        // Initialize the graph with nodes for Queries, Params, and Reentries.
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

        let rules_by_id: HashMap<&RuleId, &R> =
            self.rules.values().flatten().map(|r| (r.id(), r)).collect();

        // Rules and Reentries are created on the fly based on the out_set of dependents.
        let mut rules: HashMap<(CallSignature, ParamTypes<R::TypeId>), NodeIndex<u32>> =
            HashMap::default();
        #[allow(clippy::type_complexity)]
        let mut reentries: HashMap<
            (
                Query<R::TypeId>,
                ParamTypes<R::TypeId>,
                ParamTypes<R::TypeId>,
            ),
            NodeIndex<u32>,
        > = HashMap::default();
        let mut satisfiable_nodes: HashSet<Node<R>> = HashSet::default();
        let mut unsatisfiable_nodes: HashMap<NodeIndex<u32>, Vec<DependencyKey<R::TypeId>>> =
            HashMap::default();

        // Starting from Queries, visit all reachable nodes in the graph.
        let mut visited = HashSet::default();
        let mut to_visit = queries.values().cloned().collect::<Vec<_>>();
        let mut iteration = 0;
        while let Some(node_id) = to_visit.pop() {
            if !visited.visit(node_id) {
                continue;
            }
            iteration += 1;
            if iteration % 1000 == 0 {
                log::trace!(
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
                    if let Some(in_scope_params) = dependency_key.in_scope_params.as_ref() {
                        // If a DependencyKey has `in_scope_params`, it is solved by re-entering the graph with
                        // a Query.
                        let query = Query::new(
                            dependency_key.product,
                            dependency_key
                                .provided_params
                                .iter()
                                .chain(in_scope_params.iter())
                                .cloned(),
                        );
                        let in_scope_params = in_scope_params.into_iter().cloned().collect();
                        return (dependency_key, vec![Node::Reentry(query, in_scope_params)]);
                    }

                    let mut candidates = Vec::new();
                    if let Some(call_signature) = &dependency_key.call_signature {
                        // New call-by-name semantics.
                        candidates.extend(rules_by_id.get(&call_signature.rule_id).map(|&r| {
                            Node::Rule {
                                rule: r.clone(),
                                explicit_args_arity: call_signature.explicit_args_arity,
                            }
                        }));
                        // TODO: Once we are entirely call-by-name, we can get rid of the entire edifice
                        // of multiple candidates and the unsatisfiable_nodes mechanism, and modify this
                        // function to return a Result, which will be Err if there is no rule with a
                        // matching RuleId for some node.
                        assert!(
                            candidates.len() < 2,
                            "Had multiple candidates for rule id {}: {:?}",
                            call_signature.rule_id,
                            candidates
                        );
                    } else {
                        // Old call-by-type semantics.
                        if dependency_key.provided_params.is_empty()
                            && graph[node_id].1.contains(&dependency_key.product())
                            && params.contains_key(&dependency_key.product())
                        {
                            candidates.push(Node::Param(dependency_key.product()));
                        }

                        if let Some(rules) = self.rules.get(&dependency_key.product()) {
                            candidates.extend(rules.iter().map(|r| Node::Rule {
                                rule: r.clone(),
                                explicit_args_arity: 0,
                            }));
                        };
                    }

                    (dependency_key, candidates)
                })
                .collect::<HashMap<_, _>>();

            // If any dependency keys could not be satisfied, continue.
            let unsatisfiable_keys = candidates_by_key
                .iter()
                .filter_map(|(dependency_key, candidates)| {
                    if candidates.is_empty() {
                        Some(dependency_key.clone())
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
                        Node::Param(p) => {
                            graph.add_edge(
                                node_id,
                                *params.get(&p).unwrap(),
                                dependency_key.clone(),
                            );
                        }
                        Node::Reentry(query, in_scope_params) => {
                            let out_set = {
                                let mut out_set = out_set.clone();
                                out_set.extend(dependency_key.provided_params.iter().cloned());
                                out_set
                            };
                            let reentry_id = reentries
                                .entry((query.clone(), in_scope_params.clone(), out_set.clone()))
                                .or_insert_with(|| {
                                    graph.add_node((
                                        Node::Reentry(query.clone(), in_scope_params),
                                        out_set,
                                    ))
                                });
                            graph.add_edge(node_id, *reentry_id, dependency_key.clone());
                            to_visit.push(*reentry_id);
                        }
                        Node::Rule {
                            rule,
                            explicit_args_arity,
                        } => {
                            // If the key provides a Param for the Rule to consume, include it in the out_set for
                            // the dependency node.
                            let out_set = {
                                let mut out_set = out_set.clone();
                                out_set.extend(dependency_key.provided_params.iter().cloned());
                                out_set
                            };
                            let rule_id = rules
                                .entry((
                                    CallSignature {
                                        rule_id: rule.id().clone(),
                                        explicit_args_arity,
                                    },
                                    out_set.clone(),
                                ))
                                .or_insert_with(|| {
                                    graph.add_node((
                                        Node::Rule {
                                            rule: rule.clone(),
                                            explicit_args_arity,
                                        },
                                        out_set,
                                    ))
                                });
                            graph.add_edge(node_id, *rule_id, dependency_key.clone());
                            to_visit.push(*rule_id);
                        }
                        Node::Query(_) => unreachable!("A Query may not be a dependency."),
                    }
                }
            }

            satisfiable_nodes.insert(graph[node_id].0.clone());
        }

        // Mark all unsatisfiable nodes deleted.
        graph.map(
            |node_id, node| {
                let mut result = MaybeDeleted::new(node.clone());
                if unsatisfiable_nodes.contains_key(&node_id) {
                    result.mark_deleted(NodePrunedReason::NoSourceOfParam);
                }
                result
            },
            |_, edge_weight| edge_weight.clone(),
        )
    }

    ///
    /// Splits Rules in the graph that have multiple valid sources of a dependency, and recalculates
    /// their in/out sets to attempt to re-join with other copies of the Rule with identical sets.
    /// Similar to `live_param_labeled_graph`, this is an analysis that propagates both up and down
    /// the graph (and maintains the in/out sets while doing so). Visiting a node might cause us to
    /// split it and re-calculate the in/out sets for each split; we then visit the nodes affected
    /// by the split to ensure that they are updated as well, and so on.
    ///
    /// During this phase, the out_set of a node is used to determine which Params are legal to
    /// consume in each subgraph: as this information propagates down the graph, Param dependencies
    /// might be eliminated, which results in corresponding changes to the in_set which flow back
    /// up the graph. As the in_sets shrink, we shrink the out_sets as well to avoid creating
    /// redundant nodes: although the params might still technically be declared by the dependents, we
    /// can be sure that any not contained in the in_set are not used.
    ///
    /// Any node that has only invalid sources of a dependency (such as those that do not consume a
    /// provided param, or those that consume a Param that is not present in their scope) will be
    /// removed (which may also cause its dependents to be removed, for the same reason). This is safe
    /// to do at any time during the monomorphize run, because the in/out sets are adjusted in tandem
    /// based on the current dependencies/dependents.
    ///
    /// The exit condition for this phase is that all valid combinations of dependencies have the
    /// same minimal in_set. This occurs when all splits that would result in smaller sets of
    /// dependencies for a node have been executed. Note though that it might still be the case that
    /// a node has multiple sources of a particular dependency with the _same_ param requirements.
    /// This represents ambiguity that must be handled (likely by erroring) in later phases.
    ///
    fn monomorphize(graph: LabeledGraph<R>) -> MonomorphizedGraph<R> {
        // The monomorphized graph contains nodes and edges that have been marked deleted, because:
        //   1. we expose which nodes and edges were deleted to allow for improved error messages
        //   2. it is slow to delete nodes/edges with petgraph: marking them is much cheaper.
        // Initialize with no deleted nodes/edges.
        let mut graph: MonomorphizedGraph<R> = graph.map(
            |_node_id, node| node.clone(),
            |_edge_id, edge_weight| MaybeDeleted::new(edge_weight.clone()),
        );

        // In order to reduce the number of permutations rapidly, we make a best effort attempt to
        // visit a node before any of its dependencies using DFS-post-order. We need to visit all
        // nodes in the graph, but because monomorphizing a node enqueues its dependents we may
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
        let mut minimal_in_set = HashSet::default();

        // Should be called after a Node has been successfully reduced (regardless of whether it became
        // monomorphic) to maybe mark it minimal.
        let maybe_mark_minimal_in_set =
            |minimal_in_set: &mut HashSet<NodeIndex<u32>>,
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
                    .all(|dependency_id| {
                        node_id == dependency_id || minimal_in_set.contains(&dependency_id)
                    });
                if dependencies_are_minimal {
                    minimal_in_set.insert(node_id);
                }
            };

        // If a node splits the same way multiple times without becoming minimal, we mark it ambiguous
        // the second time.
        let mut suspected_ambiguous = HashSet::default();

        let mut iteration = 0;
        let mut maybe_in_loop = HashSet::default();
        let mut looping = false;
        while let Some(node_id) = to_visit.pop() {
            let node = if let Some(node) = graph[node_id].inner() {
                node
            } else {
                continue;
            };
            match node.node {
                Node::Rule { .. } | Node::Reentry { .. } => {
                    // Fall through to visit the Rule or Reentry node.
                }
                Node::Param(_) => {
                    // Ensure that the leaf is marked minimal, but don't bother to visit.
                    minimal_in_set.insert(node_id);
                    continue;
                }
                Node::Query(_) => {
                    // Don't bother to visit.
                    continue;
                }
            }

            // TODO: This value is mostly arbitrary, but should be increased to allow for solving the
            // largest known rulesets that we've encountered. It should really only be triggered in
            // case of implementation bugs (as we would prefer for a solution to fail via the usual
            // pathways if it can).
            //
            // See https://github.com/pantsbuild/pants/issues/11269 for plans to improve this
            // implementation.
            iteration += 1;
            if iteration > 10000000 {
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
                log::trace!(
          "rule_graph monomorphize: iteration {}: live: {}, minimal: {}, to_visit: {}, total: {}",
          iteration,
          live_count,
          minimal_count,
          to_visit.len(),
          graph.node_count(),
        );
            }

            // Group dependencies by DependencyKey.
            #[allow(clippy::type_complexity)]
            let dependencies_by_key: Vec<
                Vec<(DependencyKey<R::TypeId>, NodeIndex<u32>)>,
            > = Self::edges_by_dependency_key(&graph, node_id, false)
                .into_values()
                .map(|edge_refs| {
                    edge_refs
                        .iter()
                        .map(|edge_ref| (edge_ref.weight().0.clone(), edge_ref.target()))
                        .collect()
                })
                .collect();

            // A node with no declared dependencies is always already minimal.
            if dependencies_by_key.is_empty() {
                minimal_in_set.insert(node_id);

                // But we ensure that its out_set is accurate before continuing.
                if node.out_set != node.in_set {
                    graph.node_weight_mut(node_id).unwrap().0.out_set =
                        graph[node_id].0.in_set.clone();
                }
                continue;
            }

            // Group dependents by out_set.
            #[allow(clippy::type_complexity)]
            let dependents_by_out_set: HashMap<
                ParamTypes<R::TypeId>,
                Vec<(DependencyKey<R::TypeId>, _)>,
            > = {
                let mut dbos = HashMap::default();
                for edge_ref in graph.edges_directed(node_id, Direction::Incoming) {
                    if edge_ref.weight().is_deleted() || graph[edge_ref.source()].is_deleted() {
                        continue;
                    }

                    // Compute the out_set of this dependent, plus the provided param, if any.
                    let mut out_set = graph[edge_ref.source()].0.out_set.clone();
                    out_set.extend(edge_ref.weight().0.provided_params.iter().cloned());
                    dbos.entry(out_set)
                        .or_insert_with(Vec::new)
                        .push((edge_ref.weight().0.clone(), edge_ref.source()));
                }
                dbos
            };
            let had_dependents = !dependents_by_out_set.is_empty();

            let trace_str = if looping {
                format!(
          "creating monomorphizations (from {} dependent sets and {:?} dependencies) for {:?}: {} with {:#?} and {:#?}",
          dependents_by_out_set.len(),
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
          dependents_by_out_set
        .keys()
        .map(params_str)
        .collect::<Vec<_>>(),
        )
            } else {
                "".to_owned()
            };

            // Generate the monomorphizations of this Node, where each key is a potential node to
            // create, and the dependents and dependencies to give it (respectively).
            let mut monomorphizations = HashMap::default();
            for (out_set, dependents) in dependents_by_out_set {
                for (node, dependencies) in Self::monomorphizations(
                    &graph,
                    node_id,
                    out_set.clone(),
                    &minimal_in_set,
                    &dependencies_by_key,
                ) {
                    let entry = monomorphizations
                        .entry(node)
                        .or_insert_with(|| (HashSet::default(), HashSet::default()));
                    entry.0.extend(dependents.iter().cloned());
                    entry.1.extend(dependencies);
                }
            }

            // The goal of this phase is to shrink the in_sets as much as possible via dependency changes.
            //
            // The base case for a node then is that its dependencies cannot be partitioned to produce
            // disjoint in_sets, and that the in/out sets are accurate based on any transitive changes
            // above or below this node. If both of these conditions are satisified, the node is valid.
            //
            // If a node splits in a way that results in an identical node once, we mark it suspected
            // ambiguous: if it does so again, we mark it deleted as ambiguous.
            let is_suspected_ambiguous =
                if let Some((_, dependencies)) = monomorphizations.get(&graph[node_id].0) {
                    // We generated an identical node: if there was only one output node and its dependencies were
                    // also identical, then we have nooped.
                    let had_original_dependencies = dependencies
                        == &graph
                            .edges_directed(node_id, Direction::Outgoing)
                            .filter_map(|edge_ref| {
                                if graph[edge_ref.target()].is_deleted() {
                                    None
                                } else {
                                    edge_ref
                                        .weight()
                                        .inner()
                                        .map(|dk| (dk.clone(), edge_ref.target()))
                                }
                            })
                            .collect::<HashSet<_>>();
                    if had_original_dependencies && monomorphizations.len() == 1 {
                        // This node cannot be reduced. If its dependencies had minimal in_sets, then it now also
                        // has a minimal in_set.
                        maybe_mark_minimal_in_set(&mut minimal_in_set, &graph, node_id);
                        if looping {
                            log::trace!(
                                "not able to reduce {:?}: {} (had {} monomorphizations)",
                                node_id,
                                graph[node_id],
                                monomorphizations.len()
                            );
                        }
                        continue;
                    }

                    // If more than one node was generated, but one of them had the original dependencies, then
                    // the node is potentially ambiguous.
                    had_original_dependencies
                } else {
                    false
                };

            if looping {
                log::trace!("{}", trace_str);

                maybe_in_loop.insert(node_id);
                if maybe_in_loop.len() > 5 {
                    let subgraph = graph.filter_map(
                        |node_id, node| {
                            if maybe_in_loop.contains(&node_id) {
                                Some(format!("{node_id:?}: {node}"))
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
            let ambiguous = is_suspected_ambiguous && suspected_ambiguous.contains(&node_id);
            graph
                .node_weight_mut(node_id)
                .unwrap()
                .mark_deleted(if ambiguous {
                    NodePrunedReason::Ambiguous
                } else if !monomorphizations.is_empty() {
                    NodePrunedReason::Monomorphized
                } else if had_dependents {
                    NodePrunedReason::NoValidCombinationsOfDependencies
                } else {
                    NodePrunedReason::NoDependents
                });
            // And schedule visits for all dependents and dependencies.
            to_visit.extend(graph.neighbors_undirected(node_id));

            // Generate a replacement node for each monomorphization of this rule.
            for (new_node, (dependents, dependencies)) in monomorphizations {
                let is_suspected_ambiguous_node = if is_suspected_ambiguous {
                    let is_identical = new_node == graph[node_id].0;
                    if ambiguous && is_identical {
                        // This is the identical copy of an ambiguous node: the original node has been deleted
                        // as ambiguous, and we skip creating the new copy.
                        continue;
                    }
                    is_identical
                } else {
                    false
                };

                if looping {
                    log::trace!(
            "   generating {:#?}, with {} dependents and {} dependencies ({} minimal) which consumes: {:#?}",
            new_node,
            dependents.len(),
            dependencies.len(),
            dependencies.iter().filter(|(_, dependency_id)| minimal_in_set.contains(dependency_id)).count(),
            dependencies
              .iter()
              .map(|(dk, di)| (dk.to_string(), graph[*di].to_string(),))
              .collect::<Vec<_>>()
          );
                }

                let replacement_id = graph.add_node(MaybeDeleted::new(new_node));
                if is_suspected_ambiguous_node {
                    // We suspect that this node is ambiguous, but aren't sure yet: if it splits again the
                    // same way in the future, it will be deleted as ambiguous.
                    suspected_ambiguous.insert(replacement_id);
                }

                if looping {
                    log::trace!("node: creating: {:?}", replacement_id);
                }

                // Give all dependents edges to the new node.
                for (dependency_key, dependent_id) in &dependents {
                    // Add a new edge.
                    let mut edge = MaybeDeleted::new(dependency_key.clone());
                    for p in &dependency_key.provided_params {
                        // NB: If the edge is invalid because it does not consume the provide param, we
                        // create it as deleted with that reason.
                        if !graph[replacement_id].0.in_set.contains(p) {
                            edge.mark_deleted(EdgePrunedReason::DoesNotConsumeProvidedParam);
                        }
                    }
                    if looping {
                        log::trace!("dependent edge: adding: ({:?}, {})", dependent_id, edge);
                    }
                    graph.add_edge(*dependent_id, replacement_id, edge);
                }

                // And give the replacement node edges to this combination of dependencies.
                for (dependency_key, dependency_id) in dependencies {
                    // NB: When a node depends on itself, we adjust the destination of that self-edge to point to
                    // the new node.
                    let dependency_id = if dependency_id == node_id {
                        replacement_id
                    } else {
                        dependency_id
                    };
                    if looping {
                        log::trace!(
                            "dependency edge: adding: ({dependency_key:?}, {dependency_id:?})"
                        );
                    }
                    graph.add_edge(
                        replacement_id,
                        dependency_id,
                        MaybeDeleted::new(dependency_key),
                    );
                }

                // Now that all edges have been created, maybe mark it minimal and potentially ambiguous.
                maybe_mark_minimal_in_set(&mut minimal_in_set, &graph, replacement_id);
            }
        }

        graph
    }

    ///
    /// Execute live variable analysis to determine which Params are used by each node.
    ///
    /// See https://en.wikipedia.org/wiki/Live_variable_analysis
    ///
    fn live_param_labeled_graph(&self, graph: OutLabeledGraph<R>) -> LabeledGraph<R> {
        // Add in_sets for each node, with all sets empty initially.
        let mut graph: LabeledGraph<R> = graph.map(
            |_node_id, node| {
                MaybeDeleted(
                    ParamsLabeled::new((node.0).0.clone(), (node.0).1.clone()),
                    node.1,
                )
            },
            |_edge_id, edge_weight| edge_weight.clone(),
        );

        // Information flows up (the in_sets) this graph.
        let mut to_visit = graph
            .node_references()
            .map(|nr| nr.id())
            .collect::<VecDeque<_>>();
        while let Some(node_id) = to_visit.pop_front() {
            if graph[node_id].is_deleted() {
                continue;
            }

            // Compute an initial in_set from the Node's dependencies.
            let mut in_set = Self::dependencies_in_set(
                node_id,
                graph
                    .edges_directed(node_id, Direction::Outgoing)
                    .filter(|edge_ref| !graph[edge_ref.target()].is_deleted())
                    .map(|edge_ref| {
                        (
                            edge_ref.weight().clone(),
                            edge_ref.target(),
                            &graph[edge_ref.target()].0.in_set,
                        )
                    }),
            );

            // Then extend it with Node-specific params.
            graph[node_id].0.node.add_inherent_in_set(&mut in_set);

            if in_set != graph[node_id].0.in_set {
                to_visit.extend(graph.neighbors_directed(node_id, Direction::Incoming));
                graph[node_id].0.in_set = in_set;
            }
        }

        graph
    }

    ///
    /// After nodes have been monomorphized, they have the smallest dependency sets possible.
    /// In cases where a node still has more than one source of a dependency, this phase statically
    /// decides which source of each DependencyKey to use, and prunes edges to the rest.
    ///
    /// If a node has too many dependencies (in an ambiguous way) or too few, this phase will fail
    /// slowly to collect all errored nodes (including those that have been deleted), and render the
    /// most specific error possible.
    ///
    fn prune_edges(&self, mut graph: MonomorphizedGraph<R>) -> Result<InLabeledGraph<R>, String> {
        // Walk from roots, choosing one source for each DependencyKey of each node.
        let mut visited = graph.visit_map();
        let mut errored = HashMap::default();
        // NB: We visit any node that is enqueued, even if it is deleted.
        let mut to_visit = graph
            .node_references()
            .filter_map(|node_ref| match node_ref.weight().0 {
                ParamsLabeled {
                    node: Node::Query(_),
                    ..
                } => Some(node_ref.id()),
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
                // Filter out any dependencies that are not satisfiable for this node based on its type and
                // in/out sets and any that were deleted/invalid.
                let relevant_edge_refs: Vec<_> = match node {
                    Node::Query(q) => {
                        // Only dependencies with in_sets that are a subset of our params can be used.
                        edge_refs
                            .iter()
                            .filter(|edge_ref| {
                                !edge_ref.weight().is_deleted()
                                    && !graph[edge_ref.target()].is_deleted()
                            })
                            .filter(|edge_ref| {
                                let dependency_in_set = &graph[edge_ref.target()].0.in_set;
                                dependency_in_set.is_subset(&q.params)
                            })
                            .collect()
                    }
                    Node::Rule { .. } | Node::Reentry { .. } => {
                        // If there is a provided param, only dependencies that consume it can be used.
                        edge_refs
                            .iter()
                            .filter(|edge_ref| {
                                !edge_ref.weight().is_deleted()
                                    && !graph[edge_ref.target()].is_deleted()
                            })
                            .filter(|edge_ref| {
                                dependency_key
                                    .provided_params
                                    .iter()
                                    .all(|p| graph[edge_ref.target()].0.in_set.contains(p))
                            })
                            .collect()
                    }
                    p @ Node::Param(_) => {
                        panic!(
                            "A Param should not have dependencies: {:?} had {:#?}",
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
                        // Schedule this dependency to be visited, and mark edges to all other choices deleted.
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
                        // If there were no live nodes for this DependencyKey, traverse into any nodes
                        // that were deleted. We do not traverse deleted edges, as they represent this node
                        // having eliminated the dependency for a specific reason that we should render here.
                        if edge_refs
                            .iter()
                            .all(|edge_ref| graph[edge_ref.target()].deleted_reason().is_some())
                        {
                            to_visit.extend(
                                edge_refs
                                    .iter()
                                    .filter(|edge_ref| {
                                        matches!(
                      graph[edge_ref.target()].deleted_reason(),
                      Some(NodePrunedReason::Ambiguous)
                        | Some(NodePrunedReason::NoSourceOfParam)
                        | Some(NodePrunedReason::NoValidCombinationsOfDependencies)
                    )
                                    })
                                    .map(|edge_ref| edge_ref.target()),
                            );
                        }
                        errored.entry(node_id).or_insert_with(Vec::new).push(
                            self.render_no_source_of_dependency_error(
                                &graph,
                                node,
                                dependency_key,
                                edge_refs,
                            ),
                        );
                    }
                    _ => {
                        // Render and visit only the chosen candidates to see why they were ambiguous.
                        to_visit.extend(chosen_edges.iter().map(|edge_ref| edge_ref.target()));
                        errored
                            .entry(node_id)
                            .or_insert_with(Vec::new)
                            .push(format!(
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
                            ));
                    }
                }
            }
            for edge_to_delete in edges_to_delete {
                graph[edge_to_delete].mark_deleted(EdgePrunedReason::SmallerParamSetAvailable);
            }

            // Validate masked params.
            if let Node::Rule { rule, .. } = &graph[node_id].0.node {
                for masked_param in rule.masked_params() {
                    if graph[node_id].0.in_set.contains(&masked_param) {
                        let in_set = params_str(&graph[node_id].0.in_set);
                        let dependencies = graph
                            .edges_directed(node_id, Direction::Outgoing)
                            .filter(|edge_ref| {
                                !edge_ref.weight().is_deleted()
                                    && !edge_ref.weight().0.provides(&masked_param)
                                    && graph[edge_ref.target()].0.in_set.contains(&masked_param)
                            })
                            .map(|edge_ref| {
                                let dep_id = edge_ref.target();
                                format!(
                                    "{} for {}",
                                    graph[dep_id].0.node,
                                    params_str(&graph[dep_id].0.in_set)
                                )
                            })
                            .collect::<Vec<_>>()
                            .join("\n  ");
                        errored
                            .entry(node_id)
                            .or_insert_with(Vec::new)
                            .push(format!(
                "Rule `{rule} (for {in_set})` masked the parameter type `{masked_param}`, but \
                  it was required by some dependencies:\n  {dependencies}"
              ));
                    }
                }
            }
        }

        if errored.is_empty() {
            // Finally, return a new graph with all deleted data discarded.
            Ok(graph.filter_map(
                |_node_id, node| {
                    node.inner()
                        .map(|node| (node.node.clone(), node.in_set.clone()))
                },
                |_edge_id, edge| edge.inner().cloned(),
            ))
        } else {
            // Render the most specific errors.
            Err(Self::render_prune_errors(&graph, errored))
        }
    }

    #[allow(clippy::type_complexity)]
    fn render_no_source_of_dependency_error(
        &self,
        graph: &MonomorphizedGraph<R>,
        node: &Node<R>,
        dependency_key: DependencyKey<R::TypeId>,
        edge_refs: Vec<
            EdgeReference<MaybeDeleted<DependencyKey<R::TypeId>, EdgePrunedReason>, u32>,
        >,
    ) -> String {
        if self.rules.contains_key(&dependency_key.product()) {
            format!(
                "No source of dependency {} for {}. All potential sources were eliminated: {:#?}",
                dependency_key,
                node,
                edge_refs
                    .iter()
                    .map(|edge_ref| {
                        // An edge being deleted carries more information than a node being deleted, because a
                        // deleted edge from X to Y describes specifically why X cannot use Y.
                        let node = &graph[edge_ref.target()];
                        let reason = edge_ref
                            .weight()
                            .deleted_reason()
                            .map(|r| format!("{r:?}"))
                            .or_else(|| node.deleted_reason().map(|r| format!("{r:?}")));
                        let reason_suffix = if let Some(reason) = reason {
                            format!("{reason}: ")
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
            )
        } else if dependency_key.provided_params.is_empty() {
            format!(
                "No installed rules return the type {}, and it was not provided by potential \
        callers of {}.\nIf that type should be computed by a rule, ensure that that \
        rule is installed.\nIf it should be provided by a caller, ensure that it is included \
        in any relevant Query or Get.",
                dependency_key.product(),
                node,
            )
        } else {
            format!(
        "No installed rules return the type {} to satisfy {} for {}.\nEnsure that the rule you are \
        expecting to use is installed.",
        dependency_key.product(),
        dependency_key,
        node,
      )
        }
    }

    fn render_prune_errors(
        graph: &MonomorphizedGraph<R>,
        errored: HashMap<NodeIndex<u32>, Vec<String>>,
    ) -> String {
        // Leaf errors have no dependencies in the errored map.
        let mut leaf_errors = errored
            .iter()
            .filter(|(&node_id, _)| {
                !graph
                    .neighbors_directed(node_id, Direction::Outgoing)
                    .any(|dependency_id| {
                        errored.contains_key(&dependency_id) && node_id != dependency_id
                    })
            })
            .flat_map(|(_, errors)| {
                let mut errors = errors.clone();
                errors.sort();
                errors.into_iter().map(|e| e.trim().replace('\n', "\n    "))
            })
            .collect::<Vec<_>>();

        leaf_errors.sort();
        leaf_errors.dedup();

        let subgraph = graph.filter_map(
            |node_id, node| {
                errored
                    .get(&node_id)
                    .map(|errors| format!("{}:\n{}", node, errors.join("\n")))
            },
            |_, edge_weight| Some(edge_weight.clone()),
        );

        log::trace!(
            "// errored subgraph:\n{}",
            petgraph::dot::Dot::with_config(&subgraph, &[])
        );

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
    fn finalize(self, graph: InLabeledGraph<R>) -> Result<RuleGraph<R>, String> {
        let entry_for = |node_id| -> Entry<R> {
            let (node, in_set): &(Node<R>, ParamTypes<_>) = &graph[node_id];
            match node {
                Node::Rule {
                    rule,
                    explicit_args_arity,
                } => Entry::WithDeps(Intern::new(EntryWithDeps::Rule(RuleEntry {
                    params: in_set.clone(),
                    rule: rule.clone(),
                    explicit_args_arity: *explicit_args_arity,
                }))),
                Node::Query(q) => {
                    Entry::WithDeps(Intern::new(EntryWithDeps::Root(RootEntry(q.clone()))))
                }
                Node::Param(p) => Entry::Param(*p),
                Node::Reentry(q, _) => {
                    Entry::WithDeps(Intern::new(EntryWithDeps::Reentry(Reentry {
                        params: in_set.clone(),
                        query: q.clone(),
                    })))
                }
            }
        };

        // Visit the reachable portion of the graph to create Edges, starting from roots.
        let mut rule_dependency_edges = HashMap::default();
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
                .map(|edge_ref| {
                    (
                        edge_ref.weight().clone(),
                        Intern::new(entry_for(edge_ref.target())),
                    )
                })
                .collect::<HashMap<_, Intern<Entry<R>>>>();

            match entry {
                Entry::WithDeps(wd) => {
                    rule_dependency_edges.insert(wd, RuleEdges { dependencies });
                }
                Entry::Param(p) => {
                    if !dependencies.is_empty() {
                        return Err(format!(
              "Param {p} should not have had dependencies, but had: {dependencies:#?}",
            ));
                    }
                }
            }
        }

        Ok(RuleGraph {
            queries: self.queries.into_iter().collect(),
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
        DependencyKey<R::TypeId>,
        Vec<EdgeReference<MaybeDeleted<DependencyKey<R::TypeId>, EdgePrunedReason>, u32>>,
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
        .get_mut(dependency_key)
        .unwrap_or_else(|| {
          panic!("{node} did not declare a dependency {dependency_key}, but had an edge for it.");
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
        dependency_key: &'a DependencyKey<R::TypeId>,
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

        if dependency_key.provided_params.is_empty() {
            Box::new(dependency_in_set.iter().cloned())
        } else {
            // If the DependencyKey "provides" the Param, it does not count toward our in-set.
            Box::new(
                dependency_in_set
                    .iter()
                    .filter(move |p| !dependency_key.provides(*p))
                    .cloned(),
            )
        }
    }

    ///
    /// Calculates the in_set required to satisfy the given set of dependency edges with their
    /// in_sets.
    ///
    fn dependencies_in_set<'a>(
        node_id: NodeIndex<u32>,
        dependency_edges: impl Iterator<
            Item = (
                DependencyKey<R::TypeId>,
                NodeIndex<u32>,
                &'a ParamTypes<R::TypeId>,
            ),
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
        deps: &[Vec<(DependencyKey<R::TypeId>, NodeIndex<u32>)>],
    ) -> HashMap<ParamsLabeled<R>, HashSet<(DependencyKey<R::TypeId>, NodeIndex<u32>)>> {
        let mut combinations = HashMap::default();

        // We start by computing per-dependency in_sets, and filtering out dependencies that will be
        // illegal in any possible combination.
        let filtered_deps: Vec<
            Vec<(
                DependencyKey<R::TypeId>,
                NodeIndex<u32>,
                ParamTypes<R::TypeId>,
            )>,
        > = deps
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
                            dependency_key,
                            *dependency_id,
                            &graph[*dependency_id].0.in_set,
                        )
                        .collect::<ParamTypes<_>>();
                        (dependency_key.clone(), *dependency_id, dependency_in_set)
                    })
                    .collect()
            })
            .collect();

        // Then generate the combinations of possibly valid deps.
        for combination in combinations_of_one(&filtered_deps) {
            // Union the pre-filtered per-dependency in_sets.
            let in_set = {
                let mut in_set =
                    combination
                        .iter()
                        .fold(ParamTypes::new(), |mut in_set, (_, _, dep_in_set)| {
                            in_set.extend(dep_in_set.iter().cloned());
                            in_set
                        });
                graph[node_id].0.node.add_inherent_in_set(&mut in_set);
                in_set
            };

            // Confirm that this combination of deps is satisfiable in terms of the in_set.
            let in_set_satisfiable =
                combination
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
                            .provided_params
                            .iter()
                            .all(|p| dependency_in_set.contains(p))
                    });
            if !in_set_satisfiable {
                continue;
            }

            // Compute the out_set for this combination. Any Params that are consumed here are removed
            // from the out_set that Rule dependencies will be allowed to consume. Params that weren't
            // present in the out_set were already filtered near the top of this method.
            let out_set = {
                let mut out_set = out_set.clone();
                for (_, dependency_id, _) in &combination {
                    if let Node::Param(p) = graph[*dependency_id].0.node {
                        out_set.remove(&p);
                    }
                }
                out_set
            };

            // We can eliminate this candidate if any dependencies have minimal in_sets which contain
            // values not present in the computed out_set (meaning that they consume a Param that isn't
            // in scope). If their in_sets are not minimal, then they might shrink further in the future,
            // and so we cannot eliminate them quite yet.
            let out_set_satisfiable =
                combination
                    .iter()
                    .all(|(_, dependency_id, dependency_in_set)| {
                        matches!(graph[*dependency_id].0.node, Node::Param(_))
                            || !minimal_in_set.contains(dependency_id)
                            || dependency_in_set.difference(&out_set).next().is_none()
                    });
            if !out_set_satisfiable {
                continue;
            }

            // If we've made it this far, we're worth recording. Huzzah!
            let entry = ParamsLabeled {
                node: graph[node_id].0.node.clone(),
                in_set: in_set.clone(),
                // NB: See the method doc. Although our dependents could technically still provide a
                // larger set of params, anything not in the in_set is not consumed in this subgraph,
                // and the out_set shrinks correspondingly to avoid creating redundant nodes.
                out_set: out_set.intersection(&in_set).cloned().collect(),
            };
            combinations
                .entry(entry)
                .or_insert_with(HashSet::default)
                .extend(combination.into_iter().map(|(dk, di, _)| (dk.clone(), *di)));
        }

        combinations
    }
}

///
/// Generate all combinations of one element from each input vector.
///
pub(crate) fn combinations_of_one<T>(input: &[Vec<T>]) -> Box<dyn Iterator<Item = Vec<&T>> + '_> {
    combinations_of_one_helper(input, input.len())
}

fn combinations_of_one_helper<T>(
    input: &[Vec<T>],
    combination_len: usize,
) -> Box<dyn Iterator<Item = Vec<&T>> + '_> {
    match input.len() {
        0 => Box::new(std::iter::empty()),
        1 => Box::new(input[0].iter().map(move |item| {
            let mut output = Vec::with_capacity(combination_len);
            output.push(item);
            output
        })),
        len => {
            let last_idx = len - 1;
            Box::new(input[last_idx].iter().flat_map(move |item| {
                combinations_of_one_helper(&input[..last_idx], combination_len).map(
                    move |mut prefix| {
                        prefix.push(item);
                        prefix
                    },
                )
            }))
        }
    }
}
