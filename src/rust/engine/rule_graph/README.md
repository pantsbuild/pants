# Rule Graph Construction

## Overview

Build logic in [Pants](https://www.pantsbuild.org/) is declared using collections of `@rules` with recursively memoized and invalidated results. This framework (known as Pants' "Engine") has similar goals to Bazel's [Skyframe](https://bazel.build/designs/skyframe.html) and the [Salsa](https://github.com/salsa-rs/salsa) framework: users define logic using a particular API, and the framework manages tracking the dependencies between nodes in a runtime graph.

In order to maximize the amount of work that can be reused at runtime, Pants statically computes the memoization keys for the nodes of the runtime graph from the user specified `@rules` during startup: this process is known as "rule graph construction". See the `Goals` section for more information on the strategy and reasoning for this.

Construction of a rule graph has a few problems relevant to compilers, including live variable analysis and monomorphization of usages of rules to minimize their identities and pre-decide which versions of their dependencies they will use. See the "Open Issues" section for a call for assistance with improving the implementation of rule graph construction!

## Concepts

A successfully constructed `RuleGraph` contains a graph where nodes have one of three types, which map fairly closely to what a Pants `@rule` author consumes.

### Rules

A `Rule` is a function or coroutine with all of its inputs declared as part of its type signature. The end user type signature is made up of:
1. the return type of the `Rule`
2. the positional arguments to the `Rule`
3. a set of `Get`s which declare the runtime requirements of a coroutine, of the form `Get(output_type, input_type)`

In the `RuleGraph`, these are encoded in a [Rule](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/rules.rs#L76-L95) trait, with a [DependencyKey](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/rules.rs#L21-L41) trait representing both the positional arguments (which have no provided `Param`) and the `Get`s (which provide their input type).

`Rule`s never refer to one another by name (ie, they do not call one another by name): instead, their signature declares their requirements in terms of input/output types.

### Queries

The roots/entrypoints of a `RuleGraph` are `Query`s, which should correspond one-to-one to external callsites that use the engine to request that values are computed. A `Query` has an output type, and a series of input types: `Query(output_type, (*input_types))`.

If a user makes a request to the engine that does not have a corresponding `Query` declared, the engine fails rather than attempting to dynamically determine which `Rules` to use to answer the `Query`: how a `RuleGraph` is constructed should show why that is the case.

### Params

`Params` are typed, comparable (`eq`/`hash`) values that represent both the inputs to `Rules`, and the building block of the runtime memoization key for a `Rule`. The set of `Params` (unique by type) that are consumed to create a `Rule`'s inputs (plus the `Rule`'s own identity) make up the memoization key for a runtime instance of the `Rule`.

It's important to note though that the `Params` in a `Rule` instance's identity will _not_ always become the positional arguments to that `Rule`: in many cases, a `Param` will be consumed by a `Rule`'s dependencies in order to produce an output value that becomes either a positional argument to the `Rule` as it starts, or the result of a `Get` while a coroutine `Rule` runs.

The `Param`s that are available to a `Rule` are caller dependent, but similar to how `Rule`s are not called by name, neither are all of their `Param`s passed explicitly at each usage. A `Rule` will be used to compute the output value for a `DependencyKey`: ie, a positional argument, `Get` result, or `Query` result. Of these usage sites, only `Query` specifies the complete set of `Params` that will be available: the other two usages (positional arguments and `Get`s) are able to use any Param that is "in scope" at the use site.

`Params` flow down the graph from `Query`s and the provided `Param`s of `Get`s: their presence does not need to be re-declared at each intermediate callsite, and so a `Param` injected into a subgraph by a `Query` or `Get` is available to a consumer arbitrarily deep in that subgraph.

## Goals

The goal of `RuleGraph` construction is both to:
1. decide which `Rule`s to use to answer `Query`s (transitively, since `Rule`s do not call one another by name) and
2. determine the minimum set of `Param` inputs needed to satisfy the `Rule`s below those `Query`s

If either of the Goals were removed, `RuleGraph` construction might be more straightforward:
1. If rather than being type-driven, `Rule`s called one-another by name, you could statically determine their input `Params` by walking the call graph of `Rule`s by name, and collecting their transitive input `Params`.
2. If rather than needing to compute a minimum set of `Param` inputs for the memoization key, we instead required that all usage sites explicitly declared all `Param`s that their dependencies might need, we could relatively easily eliminate candidates based on the combination of `Param` types at a use site. And if we were willing to have very large memoization keys, we could continue to have simple callsites, but skip pruning the `Params` that pass from a dependee to a dependency at runtime, and include any `Params` declared in any of a `Rule`s transitive dependees to be part of its identity.

But both of the goals are important, because together they allow for an API that is* (should be: see below!) very easy to write `Rule`s for, with minimal boilerplate required to get the inputs needed for a `Rule` to compute a value, and minimal invalidation. Because the identity of a `Rule` is computed from its transitive input `Param`s rather than from its positional arguments, `Rule`s can accept arbitrarily-many large input values (which don't need to implement hash) with no impact on its memoization hit rate.

On the other hand, we _are_ willing to add constraints in order to make the graph easier to compute. For example, one constraint (which aligns reasonably well with user's expectations) is that only `Rule` subgraphs that use the input `Param` of a `Get` are eligible to be used.

## Implementation

As of [3a188a1e06](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/builder.rs#L202-L219), we construct a `RuleGraph` using a combination of data flow analysis and some homegrown (and likely problematic: see below) node splitting on the call graph of `Rule`s.

The construction algorithm is broken up into phases:

1. Building a polymorphic graph, where all sources of a particular dependency are included, but without regard for which types are available at a callsite. This phase will fail fast if no `Query` or `Get` anywhere in the graph provides a particular `Param` type.
2. Run [live variable analysis](https://en.wikipedia.org/wiki/Live_variable_analysis) on the polymorphic graph to compute the initial set of `Params` used by each node in the graph. During this phase, each node in the graph has a reference to all possible sources of a particular type, and so the computed set is very conservative (ie, overly large). 
3. "Monomorphize" the polymorphic graph by using the liveness sets to partition nodes (and their dependees) for each valid combination of their dependencies. Unfortunately, this phase remains the most complicated component: while it is implemented using an algorithm similar to live variable analysis, the fit isn't perfect, and so there is a special case to break out of fruitless loops: see the "splits" TODO in `fn monomorphize`.
4. Choose the best dependencies via in/out sets, and prune unambiguous choices. Once the monomorphic graph has converged, each node in the graph will ideally have exactly one source of each dependency: in cases where a node has more, it is because given a particular set of input `Params`, there was more than one way to compute a dependency (ie, the `Params` were ambiguous). This phase is the second phase that renders errors: it does so by walking nodes that were marked deleted during `monomorphize` to attempt to find the root cause of a particular failure.
5. Once the graph is known to be valid, generate the final static `RuleGraph` for all rules reachable from queries.

## Issue Overview

As mentioned above, the "monomorphize" phase (which might be a misnomer: references to prior art/names appreciated!) of rule graph construction needs further work. While the live variable analysis phase is fully cycle tolerant, monomorphization does not always converge in the presence of cycles, meaning that without special casing, nodes can split fruitlessly in loops.

Cycles/loops are in general supported by the rule graph via recursion. Both simple and mutual recursion (written using the high level @rule syntax) converge without any special casing in monomorphize: 

```
@rule
async def fibonacci(n: int) -> Fibonacci:
    if n < 2:
        return Fibonacci(n)
    x, y = await Get(Fib, int(n - 2)), await Get(Fib, int(n - 1))
    return Fibonacci(x.val + y.val)
```
```
@rule
async def is_even(n: int) -> IsEven:
    ...

@rule
async def is_odd(n: int) -> IsEven:
    ...
```

But as the set of rules in Pants has grown, more cycles have made their way into graphs: the base set of rules (with no plugins loaded) contains some [irreducible](https://arcb.csc.ncsu.edu/~mueller/ftp/pub/mueller/papers/toplas2184.pdf) loops containing ten to twenty nodes with multiple loop headers. Examples (with external entrypoints filtered out): [one](https://gist.github.com/stuhood/568413333a9e4785a2f60928d3c02067), [two](https://gist.github.com/stuhood/5ee7d45d4f94674968e13b7fc34f9b6b)).

The special case mentioned above to break out of monomorphize if it is not converging allows us to successfully construct graphs for most of these dozen-node cases (relatively quickly: 4000 node visits to construct a 450 node output graph), but larger cases can take exponentially longer, and the special case causes us to break out with errors in cases that should be resolvable.

### Issues

#### Monotonicity vs Global Information

It is unclear precisely what factors the monomorphize phase should use on a node-by-node basis to decide whether a node should be split or whether to noop. The implementation started out similar to live variable analysis, which is expected to be monotonic and converge (ie the in/out sets get smaller/larger over time in a lattice). The [special casing we've introduced](https://github.com/pantsbuild/pants/blob/3a188a1e06d8c27ff86d8c311ff1b2bdea0d39ff/src/rust/engine/rule_graph/src/builder.rs#L386-L397) around "giving up" when a node would attempt a split that we had previously recorded attempts to use global information to decide that further splitting is fruitless, but it's possible that there is a cycle-safe way to inspect a set of nodes that have stabilized?

We've also explored converting our irreducible loops to reducible loops using [Janssen/Corporaal](http://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.46.3925&rep=rep1&type=pdf), but unfortunately the simpler

#### Pruning Choices Early

Because of how the in/out sets are adjusted during monomorphize, we're not able to prune the graph as we would be able to if we knew for certain that all of a node's transitive dependencies had already converged. As mentioned in the `Param`s section, we have a constraint that a "provided" `Param` (the input to a `Get`) must be consumed by a subgraph.

But we can only apply these constraint "directly": ie, when we're actually visiting a node with a `Get`, we _can_ eliminate dependencies whose in-sets (`Param`s transitively consumed by dependencies) show that the provided `Param` is not consumed in that subgraph. Likewise, we _can_ prune a direct dependency on a `Param` node if the out-set (`Param`s provided by transitive dependees) shows that it is not present.

But we _cannot_ use the out-set to prune choices based on their in-sets in the current implementation. Both the in-set and out-set shrink as nodes are split, and it's possible that the in-set of a dependency will shrink later and become satisfiable. We can only use transitive information if we know that all reachable dependencies have already converged... and that is non-trivial in the presence of cycles. It's possible that nodes need to be in one of multiple states depending on whether they depend transitively on themselves? Or perhaps some property of a [dominator tree](https://en.wikipedia.org/wiki/Dominator_(graph_theory)) would help here? 

#### Adjusting Phases

It's possible that rather than generating a polymorphic graph as a first step, that there is a viable strategy for directly generating a monomorphic graph without regard for requirements, and then running live variable analysis on that before pruning.

