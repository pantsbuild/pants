# The New Engine

## Scheduling

In the current RoundEngine, work is scheduled and then later performed via the `Task` interface. In
the new engine execution occurs via simple functions, with inputs selected via an input
selection clause made up of `Selector` objects (described later).

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

### API

#### End User API

The end user API for the engine is based on the registration of `Rules`, which are made up of:

1. a `Product` or return type of a function,
2. a list of dependency `Selectors` which match inputs to the function,
3. the function itself.

A `Rule` fully declares the inputs and outputs for its function: there is no imperative API for
requesting additional inputs during execution of a function. While a tight constraint,
this has the advantage of forcing decomposition of work into functions which are loosely
coupled by only the types of their inputs and outputs, and which are naturally isolated, cacheable,
and parallelizable.

A function is guaranteed to execute only when all of its inputs are ready for use. The Scheduler
considers executing a Rule when it determines that it needs to produce the declared
output `Product` type of that function for a particular `Subject`. But the Scheduler will only
actually run a Rule if it is able to (recursively) find sources for each of the
function's inputs.

See below for more information on `Products`, `Subjects`, and `Selectors`.

#### Internal API

Internally, the `Scheduler` uses end user `Rules` to create private `Node` objects and
build a `Graph` of futures that links them to their dependency Nodes. A Node represents a unique
computation and the data for a Node implicitly acts as its own key/identity.

To compute a value for a Node, the Scheduler uses the `Node.run` method starting from requested
roots. If a Node needs more inputs, it requests them via `Context.get`, which will declare a
dependency, and memoize the computation represented by the `Node`.

The initial Nodes are [launched by the scheduler](https://github.com/pantsbuild/pants/blob/16d43a06ba3751e22fdc7f69f009faeb59a33930/src/rust/engine/src/scheduler.rs#L116-L126),
but the rest of the scheduling is driven by Nodes recursively calling `Context.get` to request
dependencies.

### Products and Subjects

A `Product` is a strongly typed value specific to a particular `Subject`. End user Rules execute
in order to (recursively) compute a Product for a Subject: as a very simple example, one might
register the following Rule that can compute a `String` Product given a single `Int` input
by calling the `str` function:

    @rule(StringType, [Select(IntType)])
    def int_to_str(an_int):
      return str(an_int)

When the Scheduler wants to decide whether it can use this Rule to create a string for a
Subject, it will first see whether there are any ways to get an IntType for that Subject. If
the subject is already of `type(subject) == IntType`, then the Rule will be able to
execute immediately. On the other hand, if the type _doesn't_ match, the Scheduler doesn't give up:
it will next look for any other registered Rules that can compute an IntType Product for the
Subject (and so on, recursively.)

This recursive type search leads to some very interesting (and, admittedly, somewhat "magical")
properties. If there is any path through the Rule graph that allows for conversion
from one type to another, it will be found and executed.

### Selectors

As demonstrated above, the `Selector` classes select function inputs in the context of a particular
`Subject` (and its `Variants`: discussed below). For example, it might select a `Product` for the given
Subject (`Select`), or for other Subject(s) selected from fields of a Product (`SelectDependencies`,
`SelectProjection`).

One very important thing to keep in mind is that Selectors like `SelectDependencies` and `SelectProjection`
"change" the Subject within a particular subgraph. For example, `SelectDependencies`
results in new subgraphs for each Subject in a list of values that was computed for some original Subject.
Concretely, a Rule could use SelectDependencies to select FileContent for each entry in a Files list,
and then concatentate that content into a string:

    @rule(StringType, [SelectDependencies(FileContent, Files)])
    def concat(file_content_list):
      return ''.join(fc.content for fc in file_content_list)

This Rule declares that: "for any Subject for which we can compute a 'Files' object, we can also
compute a StringType". Each subgraph will contain an attempt to get FileContent for a different
File Subject from the Files list.

In practical use, using `StringType` or `IntType` directly would probably not provide enough information
to disambiguate between various types of data: So declaring small `datatype` definitions to provide
a unique and descriptive type is strongly recommended:

    class ConcattedFiles(datatype('ConcattedFiles', ['content'])):
      pass

### Variants

Certain Rules will also need parameters provided by their dependents in order to tailor their output
Products to their consumers.  For example, a javac planner might need to know
the version of the java platform for a given dependent binary target (say Java 6), or an ivy Rule
might need to identify a globally consistent ivy resolve for a test target.  To allow for this the
engine introduces the concept of `variants`, which are passed recursively from dependents to
dependencies.

If a Rule uses a `SelectVariants` Selector to indicate that a variant is required, consumers can use
a `@[type]=[name]` address syntax extension to pass a variant that matches a particular configuration
for a Rule. A dependency declared as `src/java/com/example/lib:lib` specifies no particular variant, but
`src/java/com/example/lib:lib@java=java8` asks for the configured variant of the lib named "java8".

Additionally, it is possible to specify the "default" variants for an Address by installing a Rule
function that can provide `Variants(default=..)`. Again, since the purpose of variants is to collect
information from dependents, only default variant values which have not been set by a dependent
will be used.

## Execution

The Scheduler executes work concurrently wherever possible; to help visualize executions, a visualization
tool is provided that, after executing a `ProductGraph`, generates a `dot` file that can be rendered using
Graphviz:

```console
$ mkdir viz
$ ./pants --native-engine-visualize-to=viz list some/example/directory:
$ ls viz
run.0.dot
```
