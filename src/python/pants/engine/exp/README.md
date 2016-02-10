# The Engine Experiment

This directory tree and its test sibling in `tests/python/pants_test/engine/exp` serve as the base for
code implementing the new tuple-based engine envisioned some time as far back as 2013.

The code is limited in scope to proving out capabilities of the new engine concept:

+ Can the engine schedule such and such a build request?
+ Can task writer accomplish their goals with the engine APIs reasonably?
+ Can a BUILD writer express BUILD rules reasonably.

The code leaves out much that would be needed in a full execution model; notably option plumbing
and product caching.  The presumption is that the bits left out are straight-forward to plumb and do
not provide insight into the questions above.

## History

The need for an engine that could schedule all work as a result of linking required products to
their producers in multiple rounds was identified sometime in the middle of 2013 as a result of
new requirements on the `IdeaGen` task forced by the use of pants in the Twitter birdcage repo.  The
design document for this "RoundEngine" is
[here](https://docs.google.com/document/d/1MwOFcr4W6KbzPdbaj_ntJ36a0NRoiKyWLed0ziobsr4/edit#heading=h.rsohbvtm7zng).
Some work was completed along these lines and an initial version of the `RoundEngine` was
integrated into the pants mainline and is used today.

Work stalled on the later phases of the `RoundEngine` and talks re-booted about the future of the
`RoundEngine`.  Foursquare folks had been thinking about general problems with the `RoundEngine` as
it stood and proposed the idea of a "tuple-engine".  With some license taken in representation, this
idea took the `RoundEngine` to the extreme of generating a round for each target-task pair.  The
pair formed the tuple of schedulable work and this concept combined with others to form the design
[here][tuple-design].

Meanwhile, need for fine-grained parallelism was acute to help speed up jvm compilation, especially
in the context of scala and mixed scala & java builds.  Twitter spiked on a project to implement
a target-level scheduling system scoped to just the jvm compilation tasks.  This bore fruit and
served as further impetus to get a "tuple-engine" designed and constructed to bring the benefits
seen in the jvm compilers to the wider pants world of tasks.

## Design Goals

The design doc is [linked][tuple-design] above, but some goals and direction are further explained
here in light of the actual code to land in the `pants/engine/exp` package.

4 primary concerns can be seen as driving much of the design, in no particular order:

* It should be easy to write a maximally fine-grained task and have the engine handle scheduling.
* It should be possible for tasks to introduce new dependencies during execution, which may
   cause further work to be scheduled.
* It should be possible to distribute execution of independent units of work to exploit more cores
   and more disk IO bandwidth.
* It should be easy for plugin authors to extend the operations available on a target without a
   brittle web of target subclassing across the core and plugins.

There were other concerns, like bootstrapping in-repo tools from their sources, but the 4 above
serve to explain almost all the features of the experiment.

Notably _not_ in the list of goals listed above is any requirement to be able to schedule
coarse-grained/"global" executions.  While originally present in the designs, it was removed in
favor of the ability to introduce new dependencies during execution. Since it is impossible
to know when "all" dependencies of a particular type have been introduced to the graph, no
execution can be truly global.

Instead, tasks like `IvyResolve` will be able to use the 'variants' feature to propagate global
information down from dependents.

## Components

The design goals led to 4 key components in the experiment:

1. The struct object model.
2. The product graph.
3. The execution scheduler.
4. The execution engines.

### Object Model

The core of the object model are
[`Serializable`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/objects.py#L48)
objects.  These namedtuple-like objects that are amenable to serialization, including to and from
json and via pickling.  This is a key requirement for both eventual RPC distribution of execution
data as well as supporting a target graph daemon with out-of-process clients.  The engine experiment
uses
[`Struct`](https://github.com/pantsbuild/pants/blob/0f8eb2c1a965dd55893a6220ca137a7d79cf50aa/src/python/pants/engine/exp/struct.py)
as a convenient baseclass for most of its `Serializable` objects.

### Product Graph

The
[`ProductGraph`](https://github.com/pantsbuild/pants/blob/ef3f8d221a5afefb01d655448ce7e3f537399810/src/python/pants/engine/exp/scheduler.py#L321)
is built around named `Struct` objects as opposed to targets per-se.  Dependency edges are
modelled flexibly via an [`AddressableDescriptor`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/addressable.py#L113)
that has associated decorators for one to one edges
([`@addressable`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/addressable.py#L299)),
and one to many edges
([`@addressable_list`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/addressable.py#L341)
and [`@addressable_dict`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/addressable.py#L370)).
There are two important outgrowths from the flexible edge-schema model:

1. Dependencies now need only point at a named `Serializable` object, they need not be targets.
   This allows for both expressing dependencies inline as well as referring to dependencies that
   themselves don't naturally admit (local) dependencies.  Both jars and python requirements are
   good examples of these.  For those that remember the old inline `jar(...)`s and un-wrapped
   (but still addressable) `python_requirement`s, this supports those in a disciplined way.
2. A templating scheme becomes viable.  Since dependency edges are easy to define, `Struct`
   defines an optional `extends` one-to-one property and an optional `merges` one-to-many list
   property.  These combine with graph support for `Serializable` object factories to allow for
   "target templating".  More accurately, a set of default properties for a `Struct` (or
   Target) can be written down in a BUILD file as an addressable object that is conceptually
   abstract.  Other targets can then inherit properties and configurations from these templates. 
   This allows normalization of BUILD configuration in general.

In addition to the new edge schema system, the `Serializable` basis of the object model allows for
straight-forward introduction of BUILD file formats.  The experiment ships with three: the legacy
python style with name parameters, a modified python style that takes names from variable
assignments, and a JSON format.

### Scheduling

In the current engine, work is scheduled and then later performed via the `Task` interface.  In the
experimental engine execution occurs via simple functions, with inputs selected via an input
selection clause made up of `Selector` objects (described later).

The `Scheduler` builds a graph of `Node`s.  A Node represents a unique computation and the data for a
Node implicitly acts as its own key/identity.

To compute a value for a Node, the Scheduler uses the `Node.step` method on any Nodes that have
not yet been computed.  The `step` method returns a State value which indicates whether the
computation for a Node has completed with a value, failed, or needs additional inputs.  If a Node
needs more inputs, they are provided to that Node during a future call to its `step` method.
When a Node has all required inputs, it should execute and then `Return` its final value.

The initial Nodes are created by the
[scheduler](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/scheduler.py#L521),
but the rest of the scheduling is driven by Nodes returning the `Waiting` State to request
dependencies.  It's this lazy scheduling that naturally allows for recursion and fine-grained
planning.

#### Products and Subjects

A `Product` is a value of a particular type for a particular `Subject`.  The most common
Subject type is `Target`: a named collection (usually parsed from a BUILD file) which holds
concrete/native `Product` values in its `configurations` field.  Tasks can also request a Product
for a non-Target subject, and the examples demonstrate this for named `Jar` objects. Products
that are fetched directly from the build graph (rather than being computed) are referred to as
'native' Products.

#### Variants

Certain tasks will also need parameters provided by the dependents of their Node in order to
tailor their output Products to their consumers.  For example, a javac planner might need to know
the version of the java platform for a given dependent binary target (say Java 6), or an ivy task
might need to identify a globally consistent ivy resolve for a test target.  To allow for this the
engine introduces the concept of `variants`, which are passed recursively from dependents to
dependencies.

If a task indicates that a variant is required, consumers can use a `@[type]=[name]` address
syntax extension to pass a variant that matches a particular configuration for a task. A dependency
declared as `src/java/com/example/lib:lib` specifies no particular variant, but
`src/java/com/example/lib:lib@java=java8` asks for the configured variant of the lib named "java8".

Additionally, it is possible to specify the "default" variants for a Target by adding a
`Variants(default=..)` configuration. Again, since the purpose of variants is to collect
information from dependents, only default variant values which have not been set by a dependent
will be used.

#### Selectors

The `Selector` classes selects function inputs in the context of a particular `Subject` (and its
variants).  For example, it might select a Product for the given Subject (`Select` or
`SelectVariant`), the dependencies of a Product for the Subject (`SelectDependencies`), or a
Product for some other literal Subject (`SelectLiteral`: usually because you need access to a
tool that lives at a named address).

There is also a very useful but potentially confusing selector to 'project' fields of a Subject.
SelectProjection allows for selecting only one field of a Subject, which normalizes the dependency
graph and avoids unnecessary work. For example, if many unique Subjects have the same value in a
'directory' field, projecting the directory will allow a task to execute only once per directory.

### Execution

The scheduling process emits opaque work units to be executed by the engine.  Two local engine
implementations are provided, a simple
[serial engine](https://github.com/pantsbuild/pants/blob/06e62bd1f00e130d76ada31b932062c5531cd717/src/python/pants/engine/exp/engine.py#L304)
and a more sophisticated
[multiprocess engine](https://github.com/pantsbuild/pants/blob/06e62bd1f00e130d76ada31b932062c5531cd717/src/python/pants/engine/exp/engine.py#L331)
that can use all cores.

To help visualize executions, a visualization tool is provided that, after building/executing a
`ProductGraph`, draws it using graphviz.  If you have graphviz installed on your machine and its
binaries in your path, you can produce visualizations like so:

```console
$ ./pants run src/python/pants/engine/exp/examples:viz -- \
  tests/python/pants_test/engine/exp/examples/scheduler_inputs \
  compile \
  src/java/codegen/selector:selected
```

This particular example shows off target and configuration templating, variants, and tool
bootstrapping.

## Questions & Problems and TODO

1. Allow for subjectless plans; ie `clean-all`:
   https://github.com/pantsbuild/pants/issues/2413
2. Handle user-IO tasks appropriately with distributed executors in mind:
   https://github.com/pantsbuild/pants/issues/2417
3. Allow for more than one fulfillment of a promise.  An example here is a java library target
   subject that a javac planner can promise a classpath product for (via compilation of java
   sources) and a service-info planner can offer a `META-INF/services/...` resource classpath
   product for. See: https://github.com/pantsbuild/pants/issues/2484

[tuple-design]: https://docs.google.com/a/twitter.com/document/d/1MQLmVGHLnA2xlVgnFjwQQeFZRonTbxM1FyBS5sYwyr8/edit?usp=sharing "Tuple Engine Design Doc"
