# The (New) Engine

## API

The end user API for the engine is based on the registration of `@rule`s, which are functions
or coroutines with statically declared inputs and outputs. A Pants (plugin) developer can write
and install additional `@rule`s to extend the functionality of Pants.

The set of installed `@rule`s is statically checked as a closed world: this compilation step occurs
on startup, and identifies all unreachable or unsatisfiable rules before execution begins. This
allows most composition errors to be detected immediately, and also provides for easy introspection
of the build. To inspect the set of rules that are installed and which product types can be
computed, you can pass the `--native-engine-visualize-to=$dir` flag, which will write out a graph
of reachable `@rule`s.

Once the engine is instantiated with a valid set of `@rule`s, a caller can synchronously request
computation of any of the product types provided by those `@rule`s by calling:

```python
# Request a ThingINeed (a `Product`) for a thing_i_have (a `Param`).
thing_i_need, = scheduler.product_request(ThingINeed, [thing_i_have])
```

The engine then takes care of concurrently executing all dependencies of the matched `@rule`s to
produce the requested value.

### Products and Params

The engine executes your `@rule`s in order to (recursively) compute a `Product` of the requested
type for a set of `Param`s. This recursive type search leads to a loosely coupled (and yet
still statically checked) form of dependency injection.

When an `@rule` runs, it requires a set of `Param`s that the engine has determined are needed
to compute its transitive `@rule` dependencies. So although an `@rule` might not have a particular
`Param` type in its signature, it might depend on another `@rule` that does need that `Param`, and
would thus need that `Param` in order to run. To see which `Params` the engine needs to run each
`@rule`, refer to the `Visualization` section below.

Any hashable type with useful equality may be used as a `Param`, and additional `Params` can be
provided to an `@rule`'s dependencies via `Get` requests (see below). Each `Param` value in a set
of `Params` is unique by type, so if `@rules` recursively introduce a particular `Param` type,
there will still only be one value for that type in each `@rule`, but it will change as you move
deeper into the dependency graph.

The return value of an `@rule` is known as a `Product`. At some level, you can think
of `(product_type, params_set)` as a "key" that uniquely identifies a particular `Product` value
and `@rule` execution. If an `@rule` is able to produce a `Product` without consuming any `Params`,
then the `@rule` will run exactly once, and the value that it produces will be a singleton.

#### Example

As a very simple example, you might register the following `@rule` that can compute a `String`
Product given a single `Int` argument.

```python
@rule(str, [int])
def int_to_str(an_int):
  return str(an_int)
```

The first argument to the `@rule` decorator is the `Product` (ie, return) type for the `@rule`. The
second argument is a list of "parameter selectors" that declare the types of the input parameters for
the `@rule`. In this case, because the `Product` type is `str` and there is one parameter
selector (for `int`), this `@rule` represents a conversion from `int` to `str`, with no other inputs.

When the engine encounters this `@rule` while compiling the rule graph for `str`-producing-`@rules`,
it will next go hunting for the dependency `@rule` that can produce an `int` using the fewest number
of `Params`. For example, if there was an `@rule` that could produce an `int` without consuming any
`Params` at all (ie, a singleton), then that `@rule` would always be chosen first. If all `@rules` to
produce `int`s required at least one `Param`, then the engine would next see whether the input `Params`
contained an `int`, or whether there were any `@rules` that required only one `Param`, then two
`Params`, and so on.

In cases where this search detects any ambiguity (generally because there are two or more `@rules` that
can provide the same product with the same number of parameters), rule graph compilation will fail with
a useful error message.

### Datatypes

In practical use, builtin types like `str` or `int` do not provide enough information to disambiguate
between various types of data in `@rule` signatures, so declaring small `datatype` definitions to
provide a unique and descriptive type is highly recommended:

```python
class FormattedInt(datatype(['content'])): pass

@rule(FormattedInt, [int])
def int_to_str(an_int):
  return FormattedInt('{}'.format(an_int))

# Field values can be specified with positional and/or keyword arguments in the constructor:
x = FormattedInt('a string')
x = FormattedInt(content='a string')

# Field values can be accessed after construction by name or index:
print(x.content)    # 'a string'
print(x[0])         # 'a string'

# datatype objects can be easily inspected:
print(x)            # 'FormattedInt(content=a string)'
```

#### Types of Fields

`datatype()` accepts a list of *field declarations*, and returns a type which can be subclassed. A
*field declaration* can just be a string (e.g. `'field_name'`), which is then used as the field
name, as with `FormattedInt` above. A field can also be declared with a tuple of two elements: the
field name string, and a `TypeConstraint` for the field (e.g. `('field_name',
Exactly(FieldType))`). The bare type name (e.g. `FieldType`) can also be used as a shorthand for
`Exactly(FieldType)`. If the tuple form is used, the constructor will create your object, then raise
an error if the field value does not satisfy the type constraint.

``` python
class TypedDatatype(datatype([('field_name', Exactly(str, int))])):
  """Example of a datatype with a more complex field type constraint."""
```

Assigning a specific type to a field can be somewhat unidiomatic in Python, and may be unexpected or
unnatural to use. However, regardless of whether the object is created directly with type-checked
fields or whether it's produced from a set of rules by the engine's dependency injection, it is
extremely useful to formalize the assumptions made about the value of an object into a specific type,
even if the type just wraps a single field. The `datatype()` function makes it simple and efficient
to apply that strategy.

### Gets and RootRules

As demonstrated above, parameter selectors select `@rule` arguments in the context of a set of `Params`.
But where do `Params` come from?

One source of `Params` is the root of a request, where a `Param` type that may be provided by a caller
of the engine can be declared using a `RootRule`. Installing a `RootRule` is sometimes necessary to
seal the rule graph in cases where a `Param` could only possibly be computed outside of the rule graph
and then passed in.

The second case for introducing new `Params` occurs within the running graph when an `@rule` needs
to pass values to its dependencies that are necessary to compute a product. In this case, `@rule`s may
be written as coroutines (ie, using the python `yield` statement) that yield "`Get` requests" that request
products for other `Params`. Just like `@rule` parameter selectors, `Get` requests instantiated in the
body of an `@rule` are statically checked to be satisfiable in the set of installed `@rule`s.

#### Example

For example, you could declare an `@rule` that requests FileContent for each entry in a Files list,
and then concatentates that content into a (datatype-wrapped) string:

```python
@rule(ConcattedFiles, [Files])
def concat(files):
  file_content_list = yield [Get(FileContent, File(f)) for f in files]
  yield ConcattedFiles(''.join(fc.content for fc in file_content_list))
```

This `@rule` declares that: "for any `Params` for which we can compute `Files`, we can also compute
`ConcattedFiles`". Each yielded `Get` request results in FileContent for a different File `Param`
from the Files list. And, happily, all of these requests can proceed in parallel.

### Advanced Param Usage

Sometimes `@rule`s will need to consume multiple `Params` in order to tailor their output Products
to their consumers.

For example, a javac `@rule` might need to know the version of the java platform for a given
dependent binary target, or an ivy `@rule` might need to identify a globally consistent ivy resolve
for a test target. In both of these cases, the `@rule` requires two `Params` to be in scope. But
due to the fact that `Params` are implicitly propagated from dependents to dependencies, it's possible
for these `Params` to be provided much higher in the graph, without intermediate `@rules` needing to
be aware of them.

The result would be that any subgraph that transitively consumed a `Param` to produce Java 11 (for
example) would be safely isolated and distinct from one that produced Java 9.

_(This section needs an example, but that will have to wait for
[#7490](https://github.com/pantsbuild/pants/issues/7490)!)_

## Internal API

Internally, the engine uses end user `@rule`s to create private `Node` objects and
build a `Graph` of futures that links them to their dependency Nodes. A Node represents a unique
computation and the data for a Node implicitly acts as its own key/identity.

To compute a value for a Node, the engine uses the `Node.run` method starting from requested
roots. If a Node needs more inputs, it requests them via `Context.get`, which will declare a
dependency, and memoize the computation represented by the requested `Node`.

This recorded `Graph` tracks all dependencies between `@rules` and builtin "intrinsic" rules that
provide filesystem and network access. That dependency tracking allows for invalidation and dirtying
of `Nodes` as their dependencies change.

## Registering Rules

The recommended way to install `@rules` is to return them as a list from a `def rules()` definition
in a plugin's `register.py` file. Unit tests can either invoke `@rules` with fully mocked
dependencies via `pants_test.engine.util.run_rule`, or extend `pants_test.test_base.TestBase` to
construct and execute a scheduler for a given set of rules.

In general, there are two types of rules that you can define:

1. an `@rule`, which has a single product type and selects its inputs as described above.
2. a `RootRule`, which declares a type that a caller of the engine may provide as a `Param` in a
   call to `Scheduler.product_request(..)` (ie, at the "root" of the graph).

This interface is being actively developed at this time and this documentation may be out of
date. Please feel free to file an issue or pull request if you notice any outdated or incorrect
information in this document!

## Visualization

To help visualize executions, the engine can render both the static rule graph that is compiled
on startup, and also the content of the `Graph` that is produced while `@rules` run. This generates
`dot` files that can be rendered using Graphviz:

```console
$ mkdir viz
$ ./pants --native-engine-visualize-to=viz list some/example/directory:
$ ls viz
run.0.dot
```

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
[here][https://docs.google.com/document/d/1OARyIZSnw6XQiPlMydi57l_tS_JbFTJH6KLX61kPInI/edit?usp=sharing].

Meanwhile, need for fine-grained parallelism was acute to help speed up jvm compilation, especially
in the context of scala and mixed scala & java builds.  Twitter spiked on a project to implement
a target-level scheduling system scoped to just the jvm compilation tasks.  This bore fruit and
served as further impetus to get a "tuple-engine" designed and constructed to bring the benefits
seen in the jvm compilers to the wider pants world of tasks.
