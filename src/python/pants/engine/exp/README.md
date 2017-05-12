# The Engine Experiment

This directory tree and its test sibling in tests/python/pants_test/engine/exp serve as the base for
code implementing the new tuple-based engine envisioned some time as far back as 2013.

The code is limited in scope to proving out capabilities of the new engine concept:

+ Can the engine schedule such and such a build request?
+ Can task writer accomplish their goals with the engine APIs reasonably?
+ Can a BUILD writer express BUILD rules reasonably.

The code leaves out much that would be needed in a full execution model; notably option plumbing and
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

* It should be easy to write a maximally fine-grained task and have the engine handle scheduling;
   it should still be possible to write a coarse-grained task.
* It should be possible to determine the full execution plan while doing a minimum amount of work.
  The plan should be fully determined from the list of goals, targets and options specified and
  it should require minimal work to execute.
* It should be possible to distribute execution of independent units of work to exploit more cores
   and more disk IO bandwidth.
* It should be easy for plugin authors to extend the operations available on a target without a
   brittle web of target subclassing across the core and plugins.

There were other concerns, like bootstrapping in-repo tools from their sources, but the 3 above
serve to explain almost all the features of the experiment.  Of note in the goals listed above is
the requirement to still make it possible to schedule coarse-grained executions.  This requirement
is driven in part by uncertainty of what model is most appropriate for the universe of tasks known
and unknown and in part by currently global tasks, in particular `IvyResolve`, that will at least
need a transition path to the new engine and may in fact best be modelled globally even after
transition.

## Components

The design goals led to 4 key components in the experiment:

1. The target object model.
2. The target graph parsing system.
3. The execution planners and scheduler.
4. The execution engines.

### Object Model

The core of the object model are
[`Serializable`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/objects.py#L48)
objects.  These namedtuple-like objects that are amenable to serialization, including to and from
json and via pickling.  This is a key requirement for both eventual RPC distribution of execution
data as well as supporting a target graph daemon with out-of-process clients.  The engine experiment
uses
[`Configuration`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/configuration.py#L14)
as a convenient baseclass for most of its `Serializable` objects.

### Target Graph

The target
[`Graph`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/graph.py#L57)
is built around named `Serializable` objects as opposed to targets per-se.  Dependency edges are
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
2. A templating scheme becomes viable.  Since dependency edges are easy to define, `Configuration`
   defines an optional `extends` one-to-one property and an optional `merges` one-to-many list
   property.  These combine with graph support for `Serializable` object factories to allow for
   "target templating".  More accurately, a set of default properties for a `Configuration` (or
   Target) can be written down in a BUILD file as an addressable object that is conceptually
   abstract.  Other targets can then inherit properties and configurations from these templates. 
   This allows normalization of BUILD configuration in general.

In addition to the new edge schema system, the `Serializable` basis of the object model allows for
straight-forward introduction of BUILD file formats.  The experiment ships with three: the legacy
python style with name parameters, a modified python style that takes names from variable
assignments, and a JSON format.

### Planning and Scheduling

In the current engine, work is scheduled and then later performed via the `Task` interface.  In the
experimental engine these two roles are split apart.  A
[`TaskPlanner`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/scheduler.py#L264)
is responsible for scheduling and a Task - or just a plain function - is responsible for execution
and product production.  The scheduling process is driven by
[`Promise`s](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/scheduler.py#L435)
to produce a given product type for a given
[`Subject`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/scheduler.py#L26).

The initial promises are asked for by the
[scheduler](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/scheduler.py#L521),
but then the rest of the scheduling is driven by `TaskPlanner`s in turn asking for promises for the
products they need to
create a [`Plan`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/scheduler.py#L95)
for a piece of work.  Its this promise-driven scheduling that naturally allows for recursion and
fine-grained planning following the the dependency edges of the subjects (generally but not always
targets).

Since fine-grained planners will ask for promises for individual subjects, a coarse-grained planner
has a challenge in aggregating plans.  Instead of forcing this style of planner to maintain awkward
state, an optional
[`finalize_plans`](https://github.com/pantsbuild/pants/blob/3bd6d75949c253e2e11dfece7e593a7e5fdf0908/src/python/pants/engine/exp/scheduler.py#L295)
method can be implemented to aggregate any plans produced in a scheduling round into fewer plans
across more subjects.  An example of this is provided with the
[`GlobalIvyResolvePlanner`](https://github.com/pantsbuild/pants/blob/06e62bd1f00e130d76ada31b932062c5531cd717/src/python/pants/engine/exp/examples/planners.py#L75)
Which implements complete aggregation of all jar resolve promises into one global resolution.

Planning execution requires that all inputs to a task be calculated ahead of time to both ensure
complete invalidation data is at hand and that all execution data is available to ship to a worker
for execution.  Certain planners will need specialized data to create plans for a given subject.
For example, a javac planner might need to know the version of the java platform a given target's
code should be compiled under (say Java 6).  As such, the concepts of target `configurations` and
promise configuration are introduced.  The target `configurations` is just a list of `Configuration`
objects that apply to the target in various situations.  Perhaps a `JvmConfiguration` for the case
described above and a `JavadocConfiguration` for controlling aspects of javadoc gen for the target.
Users can add configurations to a target to support new plugins without need to extend target types
to add new task-specific parameters and task planners can export the configurations they require.

In some cases configuration can be ambiguous.  A target may have 2 configurations that conceptually
apply for a given planner.  In these cases the planner can chose to fail to plan based on the
ambiguity.  If they do so, an affordance is made for users to resolve these ambiguities:
"configuration selectors".  These are just an extension to the address syntax where a trailing
`@[configuration name]` is allowed. So a dependency specified as `src/java/com/example/lib:lib`
specifies no particular configuration, but `src/java/com/example/lib:lib@java8` ask for the lib
compiled targeting java 8.

### Execution

The scheduling process emits an
[`ExecutionGraph`](https://github.com/pantsbuild/pants/blob/06e62bd1f00e130d76ada31b932062c5531cd717/src/python/pants/engine/exp/scheduler.py#L446)
of plans linked by promise edges to other plans.  This can be walked by engines to perform graph
reduction and produce the final products requested by the user.  Two local implementations are
provided, a simple
[serial engine](https://github.com/pantsbuild/pants/blob/06e62bd1f00e130d76ada31b932062c5531cd717/src/python/pants/engine/exp/engine.py#L304)
and a more sophisticated
[multiprocess engine](https://github.com/pantsbuild/pants/blob/06e62bd1f00e130d76ada31b932062c5531cd717/src/python/pants/engine/exp/engine.py#L331)
that can use all cores.

To help visualize execution plans, a visualization tool is provided that, instead of executing the
`ExecutionGraph`, draws it using graphviz.  If you have graphviz installed on your machin and its
binaries in your path, you can produce visualizations like so:

```console
$ ./pants run src/python/pants/engine/exp/examples:viz -- \
  tests/python/pants_test/engine/exp/examples/scheduler_inputs \
  compile \
  src/java/codegen/selector:selected
```

This particular example shows off target and configuration templating, configuration selectors, plan
aggregation for ivy resolves and tool bootstrapping.

## Questions & Problems and TODO

1. Allow for subjectless plans; ie `clean-all`:
   https://github.com/pantsbuild/pants/issues/2413
2. Handle user-IO tasks appropriately with distributed executors in mind:
   https://github.com/pantsbuild/pants/issues/2417
3. Validate configurations specified in the target graph, ie: a target with java sources should
   probably not be allowed to list a python interpreter configuration.
4. Allow for more than one fulfillment of a promise.  An example here is a java library target
   subject that a javac planner can promise a classpath product for (via compilation of java
   sources) and a service-info planner can offer a `META-INF/services/...` resource classpath
   product for. See: https://github.com/pantsbuild/pants/issues/2484

[tuple-design]: https://docs.google.com/a/twitter.com/document/d/1MQLmVGHLnA2xlVgnFjwQQeFZRonTbxM1FyBS5sYwyr8/edit?usp=sharing "Tuple Engine Design Doc"