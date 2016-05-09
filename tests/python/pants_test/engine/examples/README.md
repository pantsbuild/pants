# The Engine Experiment

This directory tree and its test sibling in `tests/python/pants_test/engine/examples`
hosts examples that consume "the new engine" in fundamentally different ways. Some of
the ideas explored here may not be fully realizable until a decision is reached to break BUILD
file backwards compatibility.

Portions of the remainder of this document are historical: refer to
`src/python/pants/engine/README.md` for more information on the engine that was incubated
with the work described here.

## Design Goals

The design doc is [linked][tuple-design] above, but some goals and direction are further explained
here in light of the actual code to land in the `pants_test/engine/examples` package.

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

### Scheduling and Execution

For more information on Scheduling and Execution, see the `Engine` document at src/python/pants/engine/exp/README.md

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
