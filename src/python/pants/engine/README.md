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

# The object is also a tuple, and can be destructured:
some_content, = x
print(some_content) # 'a string'

# datatype objects can be easily inspected:
print(x)            # 'FormattedInt(content=a string)'
```

#### Types of Fields

`datatype()` accepts a list of *field declarations*, and returns a type which can
be subclassed. A *field declaration* can just be a string (e.g. `'field_name'`),
which is then used as the field name, as with `FormattedInt` above. A field can
also be declared with a tuple of two elements: the field name string, and a type
for the field (e.g. `('field_name', FieldType)`). If the tuple form is used, the
constructor will create your object, then raise an error if
`type(self.field_name) != FieldType`. Note that this means providing an instance
of a *subclass* of a field's declared type will **fail** this type check in the
constructor!

Please see [Datatypes in Depth](#datatypes-in-depth) for further discussion on
using `datatype` objects with the v2 engine.

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

Currently, it is only possible to load rules into the pants scheduler in two ways: by importing and using them in `src/python/pants/bin/engine_initializer.py`, or by adding them to the list returned by a `rules()` method defined in `src/python/backend/<backend_name>/register.py`. Plugins cannot add new rules yet. Unit tests, however, can mix in `SchedulerTestBase` from `tests/python/pants_test/engine/scheduler_test_base.py` to generate and execute a scheduler from a given set of rules.

In general, there are three types of rules you can define:

1. an `@rule`, which has a single product type and selects its inputs as described above.
2. a `SingletonRule`, which matches a product type with a value so the type can then be `Select`ed in an `@rule`.
3. a `RootRule`, which declares a type that can be used as a *subject*, which means it can be provided as an input to a `product_request()` or a `Get` statement.

This interface is being actively developed at this time and this documentation may be out of date.

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

## Datatypes in Depth

`datatype` objects can be used to colocate multiple dependencies of an
`@rule`. For example, to compile C code, you typically require both source code
and a C compiler:

``` python
class CCompileRequest(datatype(['c_compiler', 'c_sources'])):
  pass

class CObjectFiles(datatype(['files_snapshot'])):
  pass

# The engine ensures this is the only way to get from
# CCompileRequest -> CObjectFiles.
@rule(CObjectFiles, [Select(CCompileRequest)])
def compile_c_sources(c_compile_request):
  c_compiler, c_sources = c_compile_request
  compiled_object_files = c_compiler.compile(c_sources)
  return CObjectFiles(compiled_object_files)
```

Encoding different stages of a build process into different `datatype`
subclasses which have all the information they need and no more makes it easier
to add functionality to the build by consuming and/or producing types from a
concise shared set of `datatype` definitions. For example:

``` python
# "Vendoring" refers to checking a source or binary copy of a 3rdparty
# library into source control. In this case, we assume the snapshot contains
# _only_ binary object files for the current platform.
class VendoredLibrary(datatype(['files_snapshot'])):
  pass

@rule(CObjectFiles, [Select(VendoredLibrary)])
def get_vendored_object_files(vendored_library):
  return CObjectFiles(vendored_library.files_snapshot)
```

We have added the ability to depend on checked-in binary object files with an
extremely small amount of code, because we can assume that `VendoredLibrary` is
constructed with a snapshot containing only object files, so we can ensure that
the `CObjectFiles` we construct also upholds that guarantee. The key to making
that assumption possible is encoding assumptions about our objects into specific
types, and letting the engine invoke the correct sequence of rules.

### Encoding Assumptions into Types

Passing around an instance of a primitive type such as `str` or `int` can
sometimes require significant mental overhead to keep track of assumptions that
the code makes about the object's value. If the `str` needs to be formatted a
specific way or the `int` must be within a certain range, using those types
directly can require repeated validation of the object wherever it's used, for
example to avoid injection attacks from user-provided strings, or attempting to
read a negative number of bytes from a file. Outside of the variable name, with
a `str` object there is no context about what validation or transformations have
been performed on the object or how it will be used.

One way to keep track of assumptions made about an object's value is to make a
wrapper type for that object, and then control the ways that instances of the
wrapper type can be created. One way to implement this is to override the
wrapper type's constructor and raise an exception if the object's value is
invalid. Declaring a typed field for a `datatype` takes this approach, but it
can be extended for arbitrary types of input validation:

``` python
# Declare a datatype with a single field 'int_value',
# which must be an int when the datatype is constructed.
class NonNegativeInt(datatype([('int_value', int)])):
  def __new__(cls, *args, **kwargs):
    # Call the superclass constructor first to check the type of `int_value`.
    this_object = super(NonNegativeInt, cls).__new__(cls, *args, **kwargs)

    if this_object.int_value < 0:
      raise cls.make_type_error("value is negative: {!r}"
                                .format(this_object.int_value))

    return this_object
```

`make_type_error()` creates an exception object which can be raised in a
`datatype`'s constructor to note a type checking failure, and automatically
includes the type name in the error message. However, any other exception type
can be raised as well.

For `NonNegativeInt`, the input is extremely simple (we're not calling any
methods on the `int`), and the validation is extremely straightforward (can be
expressed in a single `if`). These characteristics make it natural to declare a
specific type for the field in the call to `datatype()` and to ensure validity
with a check in the `__new__()` method. Using type checking in this way makes
types like `NonNegativeInt` usable in many different scenarios without
additional boilerplate for the user.

`VendoredLibrary` and `CObjectFile` are the opposite: a synchronous scan of
every file in a `VendoredLibrary`'s `files_snapshot` to verify that they are all
indeed object files for the correct platform every time we construct one would
be difficult to justify, because the inputs are much more complex to construct,
and the result much more difficult to validate. In this case, making simple,
focused `datatype` definitions makes it easier to correctly consume, manipulate,
and produce them to form a common set of `@rule` definitions. The engine ensures
that there is at most one sequence of rules transforming type A to type B, and
makes this feasible by automatically linking together the rules to convert type
A to type B. Making a set of rules maximally composable implicitly helps to
ensure correctness by reusing logic as much as possible.
