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
# Request a ThingINeed (a `Product`) for the thing_i_have (a `Subject`).
thing_i_need, = scheduler.product_request(ThingINeed, [thing_i_have])
```

The engine then takes care of concurrently executing all dependencies of the matched `@rule`s to
produce the requested value.

### Products and Subjects

The engine executes your `@rule`s in order to (recursively) compute a `Product` of the requested
type for a given `Subject`. This recursive type search leads to a very loosely coupled (and yet
still statically checked) form of dependency injection.

When an `@rule` runs, it runs for a particular `Subject` value, which is part of the unique
identity for that instance of the `@rule`. An `@rule` can request dependencies for different
`Subject` values as it runs (see the section on `Get` requests below). Because the subject for
an `@rule` is chosen by callers, a `Subject` can be of any (hashable) type that a user might want
to compute a product for.

The return value of an `@rule` for a particular `Subject` is known as a `Product`. At some level,
you can think of (`subject_value`, `product_type`) as a "key" that uniquely identifies a particular
Product value and `@rule` execution.

#### Example

As a very simple example, you might register the following `@rule` that can compute a `String`
Product given a single `Int` input.

```python
@rule(StringType, [Select(IntType)])
def int_to_str(an_int):
  return '{}'.format(an_int)
```

The first argument to the `@rule` decorator is the Product (ie, return) type for the `@rule`. The
second argument is a list of `Selector`s that declare the types of the input arguments to the
`@rule`. In this case, because the Product type is `StringType` and there is one `Selector`
(`Select(IntType)`), this `@rule` represents a conversion from `IntType` to `StrType`, with no
other inputs.

When the engine statically checks whether it can use this `@rule` to create a string for a
Subject, it will first see whether there are any ways to get an IntType for that Subject. If
the subject is already of `type(subject) == IntType`, then the `@rule` will be satisfiable without
any other dependencies. On the other hand, if the type _doesn't_ match, the engine doesn't give up:
it will next look for any other registered `@rule`s that can compute an IntType Product for the
Subject (and so on, recursively).

### Datatypes

In practical use, using basic types like `StringType` or `IntType` does not provide enough
information to disambiguate between various types of data. So declaring small `datatype`
definitions to provide a unique and descriptive type is strongly recommended:

```python
class FormattedInt(datatype(['content'])): pass

@rule(FormattedInt, [Select(IntType)])
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
print(repr(x))      # "FormattedInt(content='a string')"
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
  """Example of a datatype with a more complex field type constraint.

  The __str__ will display information about the type constraint of each field along with its value, while the __repr__ will just show an expression which could be evaluated to produce the instance of the datatype.
  """

x = TypedDatatype('string argument')
print(x)       # 'TypedDatatype(field_name<Exactly(str or int)>=string argument)'
print(repr(x)) # "TypedDatatype(field_name='string argument')"

y = TypedDatatype(3)
print(y)       # 'TypedDatatype(field_name<Exactly(str or int)>=3)'
print(repr(y)) # "TypedDatatype(field_name=3)"

# Raises an exception:
z = TypedDatatype([])
# pants.util.objects.TypedDatatypeInstanceConstructionError: type check error in class TypedDatatype: errors type checking constructor arguments:
# field 'field_name' was invalid: value [] (with type 'list') must satisfy this type constraint: Exactly(str or int).
```

Assigning a specific type to a field can be somewhat unidiomatic in Python, and may be unexpected or
unnatural to use. Additionally, the engine already applies a form of implicit type checking by
ensuring there is a unique path from subject to product when a product request is made. However,
regardless of whether the object is created directly with type-checked fields or whether it's
produced from a set of rules by the engine's dependency injection, it is extremely useful to
formalize the assumptions made about the value of an object into a specific type, even if the type
just wraps a single field. The `datatype()` function makes it simple and efficient to apply that
strategy.

### Selectors and Gets

As demonstrated above, the `Selector` classes select `@rule` inputs in the context of a particular
`Subject` (and its `Variants`: discussed below). But it is frequently necessary to "change" the
subject and request products for subjects other than the one that the `@rule` is running for.

In cases where this is necessary, `@rule`s may be written as coroutines (ie, using the python
`yield` statement) that yield "`Get` requests" that request products for other subjects. Just like
`@rule` parameter Selectors, `Get` requests instantiated in the body of an `@rule` are statically
checked to be satisfiable in the set of installed `@rule`s.

#### Example

For example, you could declare an `@rule` that requests FileContent for each entry in a Files list,
and then concatentates that content into a (typed) string:

```python
@rule(ConcattedFiles, [Select(Files)])
def concat(files):
  file_content_list = yield [Get(FileContent, File(f)) for f in files]
  yield ConcattedFiles(''.join(fc.content for fc in file_content_list))
```

This `@rule` declares that: "for any Subject for which we can compute `Files`, we can also compute
`ConcattedFiles`". Each yielded `Get` request results in FileContent for a different File Subject
from the Files list.

### Variants

Certain `@rule`s will also need parameters provided by their dependents in order to tailor their output
Products to their consumers.  For example, a javac `@rule` might need to know the version of the java
platform for a given dependent binary target (say Java 9), or an ivy `@rule` might need to identify a
globally consistent ivy resolve for a test target.  To allow for this the engine introduces the
concept of `Variants`, which are passed recursively from dependents to dependencies.

If a Rule uses a `SelectVariants` Selector to indicate that a variant is required, consumers can use
a `@[type]=[name]` address syntax extension to pass a variant that matches a particular configuration
for a `@rule`. A dependency declared as `src/java/com/example/lib:lib` specifies no particular variant, but
`src/java/com/example/lib:lib@java=java8` asks for the configured variant of the lib named "java8".

Additionally, it is possible to specify the "default" variants for an Address by installing an `@rule`
function that can provide `Variants(default=..)`. Since the purpose of variants is to collect
information from dependents, only default variant values which have not been set by a dependent
will be used.

## Internal API

Internally, the engine uses end user `@rule`s to create private `Node` objects and
build a `Graph` of futures that links them to their dependency Nodes. A Node represents a unique
computation and the data for a Node implicitly acts as its own key/identity.

To compute a value for a Node, the engine uses the `Node.run` method starting from requested
roots. If a Node needs more inputs, it requests them via `Context.get`, which will declare a
dependency, and memoize the computation represented by the requested `Node`.

The initial Nodes are [launched by the engine](https://github.com/pantsbuild/pants/blob/16d43a06ba3751e22fdc7f69f009faeb59a33930/src/rust/engine/src/scheduler.rs#L116-L126),
but the rest of execution is driven by Nodes recursively calling `Context.get` to request their
dependencies.

### Registering Rules

Currently, it is only possible to load rules into the pants scheduler in two ways: by importing and
using them in `src/python/pants/bin/engine_initializer.py`, or by adding them to the list returned
by a `rules()` method defined in `src/python/backend/<backend_name>/register.py`. Plugins cannot add
new rules yet. Unit tests, however, can mix in `SchedulerTestBase` from
`tests/python/pants_test/engine/scheduler_test_base.py` to generate and execute a scheduler from a
given set of rules.

In general, there are three types of rules you can define:

1. an `@rule`, which has a single product type and selects its inputs as described above.
2. a `SingletonRule`, which matches a product type with a value so the type can then be `Select`ed
   in an `@rule`.
3. a `RootRule`, which declares a type that can be used as a *subject*, which means it can be
   provided as an input to a `product_request()`.

In more depth, a `RootRule` for some type is required when no other rule provides that type (i.e. it
is not provided with a `SingletonRule` or as the product of any `@rule`). In the absence of a
`RootRule`, any subject type involved in a request "at runtime" (i.e. via `product_request()`),
would show up as an an unused or impossible path in the rule graph. Another potential name for
`RootRule` might be `ParamRule`, or something similar, as it can be thought of as saying that the
type represents a sort of "public API entrypoint" via a `product_request()`.

Note that `Get` requests do not require a `RootRule`, as their requests are statically verified when
the `@rule` definition is parsed, so we know before runtime that they might be requested.

This interface is being actively developed at this time and this documentation may be out of
date. Please feel free to file an issue or pull request if you notice any outdated or incorrect
information in this document!

## Execution

The engine executes work concurrently wherever possible; to help visualize executions, a visualization
tool is provided that, after executing a `Graph`, generates a `dot` file that can be rendered using
Graphviz:

```console
$ mkdir viz
$ ./pants --native-engine-visualize-to=viz list some/example/directory:
$ ls viz
run.0.dot
```

## Native Engine

The native engine is integrated into the pants codebase via `native.py` in
this directory along with `build-support/bin/native/bootstrap.sh` which ensures a
pants native engine library is built and available for linking. The glue is the
sha1 hash of the native engine source code used as its version by the `Native`
class. This hash is maintained by `build-support/bin/native/bootstrap.sh` and
output to the `native_engine_version` file in this directory. Any modification
to this resource file's location will need adjustments in
`build-support/bin/native/bootstrap.sh` to ensure the linking continues to work.

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
