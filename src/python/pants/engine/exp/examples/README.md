# The Engine Experiment

This directory tree and its test sibling in `tests/python/pants_test/engine/exp/examples` serve as the base for
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
here in light of the actual code to land in the `pants/engine/exp/examples` package.

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
