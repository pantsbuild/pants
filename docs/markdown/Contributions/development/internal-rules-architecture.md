---
title: "Internal architecture"
slug: "internal-rules-architecture"
hidden: false
createdAt: "2020-08-26T19:22:24.769Z"
---
Rule Graph Construction
=======================

Overview
--------

Build logic in [Pants](https://www.pantsbuild.org/) is declared using collections of `@rules` with recursively memoized and invalidated results. This framework (known as Pants' "Engine") has similar goals to Bazel's [Skyframe](https://bazel.build/designs/skyframe.html) and the [Salsa](https://github.com/salsa-rs/salsa) framework: users define logic using a particular API, and the framework manages tracking the dependencies between nodes in a runtime graph.

In order to maximize the amount of work that can be reused at runtime, Pants statically computes the memoization keys for the nodes of the runtime graph from the user specified `@rules` during startup: this process is known as "rule graph construction". See the `Goals` section for more information on the strategy and reasoning for this.

Concepts used in compilers, including live variable analysis and monomorphization, can also be useful in rule graph construction to minimize rule identities and pre-decide which versions of their dependencies they will use.

Concepts
--------

A successfully constructed `RuleGraph` contains a graph where nodes have one of three types, `Rule`s, `Query`s, and `Param`s, which map fairly closely to what a Pants `@rule` author consumes. The edges between nodes represent dependencies: `Query`s are always roots of the graph, `Param`s are always leaves, and `Rule`s represent the end user logic making up all of the internal nodes of the graph.

### Rules

A `Rule` is a function or coroutine with all of its inputs declared as part of its type signature. The end user type signature is made up of:

1. the return type of the `Rule`
2. the positional arguments to the `Rule`
3. a set of `Get`s which declare the runtime requirements of a coroutine, of the form `Get(output_type, input_type)`

In the `RuleGraph`, these are encoded in a [Rule](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/rules.rs#L76-L95) trait, with a [DependencyKey](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/rules.rs#L21-L41) trait representing both the positional arguments (which have no provided `Param`) and the `Get`s (which provide their input type as a `Param`).

`Rule`s never refer to one another by name (i.e., they do not call one another by name): instead, their signature declares their requirements in terms of input/output types, and rule graph construction decides which potential dependencies will provide those requirements.

### Queries

The roots/entrypoints of a `RuleGraph` are `Query`s, which should correspond one-to-one to external callsites that use the engine to request that values are computed. A `Query` has an output type, and a series of input types: `Query(output_type, (*input_types))`.

If a user makes a request to the engine that does not have a corresponding `Query` declared, the engine fails rather than attempting to dynamically determine which `Rules` to use to answer the `Query`: how a `RuleGraph` is constructed should show why that is the case.

### Params

`Params` are typed, comparable (`eq`/`hash`) values that represent both the inputs to `Rules`, and the building block of the runtime memoization key for a `Rule`. The set of `Params` (unique by type) that are consumed to create a `Rule`'s inputs (plus the `Rule`'s own identity) make up the memoization key for a runtime instance of the `Rule`.

`Param`s are eventually used as positional args to `Rule`s, but it's important to note that the `Param`s in a `Rule` instance's identity/memoization-key will not always become the positional arguments to _that_ `Rule`: in many cases, a `Param` will be used by a `Rule`'s transitive dependencies in order to produce an output value that becomes either a positional argument to the `Rule` as it starts, or the result of a `Get` while a coroutine `Rule` runs.

The `Param`s that are available to a `Rule` are made available by the `Rule`'s dependents (its "callers"), but similar to how `Rule`s are not called by name, neither are all of their `Param`s passed explicitly at each use site. A `Rule` will be used to compute the output value for a `DependencyKey`: i.e., a positional argument, `Get` result, or `Query` result. Of these usage sites, only `Query` specifies the complete set of `Params` that will be available: the other two usages (positional arguments and `Get`s) are able to use any Param that will be "in scope" at the use site.

`Params` flow down the graph from `Query`s and the provided `Param`s of `Get`s: their presence does not need to be re-declared at each intermediate callsite. When a `Rule` consumes a `Param` as a positional argument, that `Param` will no longer be available to that `Rule`'s dependencies (but it might still be present in other subgraphs adjacent to that `Rule`).

Goals
-----

The goals of `RuleGraph` construction are:

1. decide which `Rule`s to use to answer `Query`s (transitively, since `Rule`s do not call one another by name); and
2. determine the minimum set of `Param` inputs needed to satisfy the `Rule`s below those `Query`s

If either of the goals were removed, `RuleGraph` construction might be more straightforward:

1. If rather than being type-driven, `Rule`s called one another by name, you could statically determine their input `Params` by walking the call graph of `Rule`s by name, and collecting their transitive input `Params`.
2. If rather than needing to compute a minimum set of `Param` inputs for the memoization key, we instead required that all usage sites explicitly declared all `Param`s that their dependencies might need, we could relatively easily eliminate candidates based on the combination of `Param` types at a use site. And if we were willing to have very large memoization keys, we could continue to have simple callsites, but skip pruning the `Params` that pass from a dependent to a dependency at runtime, and include any `Params` declared in any of a `Rule`s transitive dependents to be part of its identity.

But both of the goals are important because together they allow for an API that is easy to write `Rule`s for, with minimal boilerplate required to get the inputs needed for a `Rule` to compute a value, and minimal invalidation. Because the identity of a `Rule` is computed from its transitive input `Param`s rather than from its positional arguments, `Rule`s can accept arbitrarily-many large input values (which don't need to implement hash) with no impact on its memoization hit rate.

Constraints
-----------

There are a few constraints that decide which `Rule`s are able to provide dependencies for one another:

- `param_consumption` - When a `Rule` directly uses a `Param` as a positional argument, that `Param` is removed from scope for any of that `Rule`'s dependencies.
  - For example, for a `Rule` `y` with a positional argument `A` and a `Get(B, C)`: if there is a `Param` `A` in scope at `y` and it is used to satisfy the positional argument, it cannot also be used to (transitively) to satisfy the `Get(B, C)` (i.e., a hyptothetical rule that consumes both `A` and `C` would not be eligible in that position).
  - On the other hand, for a `Rule` `w` with `Get(B, C)` and `Get(D, E)`, if there is a `Param` `A` in scope at `w`, two dependency `Rule`s that consume `A` (transitively) _can_ be used to satisfy those `Get`s. Only consuming a `Param` as a positional argument removes it from scope.
- `provided_params` - When deciding whether one `Rule` can use another `Rule` to provide the output type of a `Get`, a constraint is applied that the candidate depedency must (transitively) consume the `Param` that is provided by the `Get`.
  - For example: if a `Rule` `z` has a `Get(A, B)`, only `Rule`s that compute an `A` and (transitively) consume a `B` are eligible to be used. This also means that a `Param` `A` which is already in scope for `Rule` `z` is not eligible to be used, because it would trivially not consume `B`.

Implementation
--------------

As of [3a188a1e06](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/builder.rs#L202-L219), we construct a `RuleGraph` using a combination of data flow analysis and some homegrown (and likely problematic: see the "Issue Overview") node splitting on the call graph of `Rule`s.

The construction algorithm is broken up into phases:

1. [initial_polymorphic](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/builder.rs#L221) - Builds a polymorphic graph while computing an "out-set" for each node in the graph by accounting for which `Param`s are available at each use site. During this phase, nodes may have multiple dependency edges per `DependencyKey`, which is what makes them "polymorphic". Each of the possible ways to compute a dependency will likely have different input `Param` requirements, and each node in this phase represents all of those possibilities.
2. [live_param_labeled](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/builder.rs#L749-L754) - Run [live variable analysis](https://en.wikipedia.org/wiki/Live_variable_analysis) on the polymorphic graph to compute the initial "in-set" of `Params` used by each node in the graph. Because nodes in the polymorphic graph have references to all possible sources of a particular dependency type, the computed set is conservative (i.e., overly large).
   - For example: if a `Rule` `x` has exactly one `DependencyKey`, but there are two potential dependencies to provide that `DependencyKey` with input `Param`s `{A,B}` and `{B,C}` (respectively), then at this phase the input `Param`s for `x` must be the union of all possibilities: `{A,B,C}`.
   - If we were to stop `RuleGraph` construction at this phase, it would be necessary to do a form of [dynamic dispatch](https://en.wikipedia.org/wiki/Dynamic_dispatch) at runtime to decide which source of a dependency to use based on the `Param`s that were currently in scope. And the sets of `Param`s used in the memoization key for each `Rule` would still be overly large, causing excess invalidation.
3. [monomorphize](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/builder.rs#L325-L353) - "Monomorphize" the polymorphic graph by using the out-set of available `Param`s (initialized during `initial_polymorphic`) and the in-set of consumed `Param`s (computed during `live_param_labeled`) to partition nodes (and their dependents) for each valid combination of their dependencies. Combinations of dependencies that would be invalid (see the Constraints section) are not generated, which causes some pruning of the graph to happen during this phase.
   - Continuing the example from above: the goal of monomorphize is to create one copy of `Rule` `x` per legal combination of its `DependencyKey`. Assuming that both of `x`'s dependencies remain legal (i.e. that all of `{A,B,C}` are still in scope in the dependents of `x`, etc), then two copies of `x` will be created: one that uses the first dependency and has an in-set of `{A,B}`, and another that uses the second dependency and has an in-set of `{B,C}`.
4. [prune_edges](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/builder.rs#L836-L845) - Once the monomorphic graph has [converged](https://en.wikipedia.org/wiki/Data-flow_analysis#Convergence), each node in the graph will ideally have exactly one source of each `DependencyKey` (with the exception of `Query`s, which are not monomorphized). This phase validates that, and chooses the smallest input `Param` set to use for each `Query`. In cases where a node has more that one dependency per `DependencyKey`, it is because given a particular set of input `Params` there was more than one valid way to compute a dependency. This can happen either because there were too many `Param`s in scope, or because there were multiple `Rule`s with the same `Param` requirements.
   - This phase is the only phase that renders errors: all of the other phases mark nodes and edges "deleted" for particular reasons, and this phase consumes that record. A node that has been deleted indicates that that node is unsatisfiable for some reason, while an edge that has been deleted indicates that the source node was not able to consume the target node for some reason.
   - If a node has too many sources of a `DependencyKey`, this phase will recurse to attempt to locate the node in the `Rule` graph where the ambiguity was introduced. Likewise, if a node has no source of a `DependencyKey`, this phase will recurse on deleted nodes (which are preserved by the other phases) to attempt to locate the bottom-most `Rule` that was missing a `DependencyKey`.
5. [finalize](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/builder.rs#L1064-L1068) - After `prune_edges` the graph is known to be valid, and this phase generates the final static `RuleGraph` for all `Rule`s reachable from `Query`s.
