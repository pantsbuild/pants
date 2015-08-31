BUILD files
===========

To tell Pants about your source code, you have files named `BUILD` in
directories of your source tree. These files define build-able targets
and specify source code layout. This page goes into some detail about
`BUILD` files. If you instead wanted API docs for things defined in
`BUILD` files (`java_library`, `python_binary`, etc.), please see the
[BUILD Dictionary](build_dictionary.html). If you want less detail-y
information about `BUILD` files,
[[the Tutorial|pants('src/docs:first_tutorial')]]
is a good place to start.

`BUILD` files are little Python scripts with some
[useful functions](build_dictionary.html) automatically imported. Thus,
function invocations look `like(this)`, lists look `[like, this]`, and
dictionaries (hashmaps) look `{"like": "this"}`; Python's syntax uses
[indentation](http://en.wikipedia.org/wiki/Python_syntax_and_semantics#Indentation)
to indicate scope; if you copy-paste some `BUILD` code from one place to
another, you might need to adjust the indentation. You can [learn more
about Python](http://docs.python.org/tutorial), but you should be able
to "get along" in `BUILD` files if you know functions, lists,
dictionaries, and indentation.

Debugging a BUILD File
----------------------

If you're curious to know how Pants interprets your `BUILD` file, these
techniques can be especially helpful:

*Did I define the targets I meant to?* Use `list`:

    :::bash
    $ ./pants list examples/src/java/org/pantsbuild/example/hello/greet
    examples/src/java/org/pantsbuild/example/hello/greet:greet

*Did a change in one `BUILD` file break others?*
List **every** target to find out:
Use the recursive wildcard: `list ::`

    :::bash
    $ ./pants list ::
      ...lots of output...
      File "pants/commands/command.py", line 79, in __init__
      File "pants/commands/goal_runner.py", line 144, in setup_parser
      File "pants/base/build_graph.py", line 351, in inject_address_closure
    TransitiveLookupError: great was not found in BUILD file examples/src/java/org/pantsbuild/example/h
    ello/greet/BUILD. Perhaps you meant:
      :greet
      referenced from examples/src/scala/org/pantsbuild/example/hello/welcome:welcome
    $ # Instead of listing all targets, an error message. We found a problem

*Do I pull in the dependencies I expect?* Use `depmap` (JVM languages only):

    :::bash
    $ ./pants depmap examples/tests/java/org/pantsbuild/example/hello/greet
    internal-examples.tests.java.org.pantsbuild.example.hello.greet.greet
      internal-3rdparty.junit
        internal-3rdparty.hamcrest-core
          org.hamcrest-hamcrest-core-1.3
        junit-junit-dep-4.11
      internal-examples.src.java.org.pantsbuild.example.hello.greet.greet
      internal-examples.src.resources.org.pantsbuild.example.hello.hello
      junit-junit-dep-4.11
      org.hamcrest-hamcrest-core-1.3

*What source files do I depend on?* Use `filedeps`:

    :::bash
    $ ./pants filedeps examples/src/java/org/pantsbuild/example/hello/main
    ~archie/workspace/pants/examples/src/resources/org/pantsbuild/example/hello/BUILD
    ~archie/workspace/pants/examples/src/java/org/pantsbuild/example/hello/main/BUILD
    ~archie/workspace/pants/examples/src/java/org/pantsbuild/example/hello/main/config/greetee.txt
    ~archie/workspace/pants/examples/src/java/org/pantsbuild/example/hello/greet/Greeting.java
    ~archie/workspace/pants/examples/src/resources/org/pantsbuild/example/hello/world.txt
    ~archie/workspace/pants/examples/src/java/org/pantsbuild/example/hello/main/HelloMain.java
    ~archie/workspace/pants/examples/src/java/org/pantsbuild/example/hello/greet/BUILD

Default Target
--------------

A build target with the same name as the `BUILD` file's containing directory is the
*default target*. To signal "*this* is the main useful target here" and as a convenience to users,
have a default.

Consider these libraries that use `tugboat` functionality. You can see that this code depends on
just the default `tugboat` target, and thus uses just core functionality:

    :::python
    # depends on plain ol' tugboat
    java_library(name='theodore',
      dependencies=[
        'src/java/com/twitter/tugboat',
      ],
      sources=globs('*.java'),
    )

You can tell this code uses optional functionality because it depends on
a specific non-default target:

    :::python
    # depends on optional tugboat functionality
    java_library(name='hank',
      dependencies=[
        'src/java/com/twitter/tugboat:hispeed',
      ],
      sources=globs('*.java'),
    )

Default targets are more convenient to reference on the command line. There are a
<a pantsref="addresses_synonyms">few ways to refer to a target</a> on the command line.
It's especially convenient to refer to a default target on the command line. Consider these two
ways to refer to the same target:

    //src/java/org/pantsbuild/tugboat:tugboat  # absolute target name
    src/java/org/pantsbuild/tugboat/           # convenient command-line-completion syntax

By providing a default-name target, you make it easier for people to refer to it on the command
line. This gives them a better experience. BUILD files dependencies can be less verbose,
improving readability.

The 1:1:1 Rule
--------------

Your code's organization, including `BUILD` target configuration, makes
building easier or harder. Some folks summarize clear and scalable code
layout choice with the **1:1:1** rule of thumb:

-   **1 Folder**
-   **1 Package**
-   **1 BUILD Target**

If there's a set of code that usually goes together, it makes sense for
it to be in one folder using one package namespace. The folder should
have a `BUILD` file with one target to build that set of code.

If there's a subset of code that *doesn't* usually go together with the
rest of the code in some directory/target, it makes sense to move that
code out into another folder and its own package namespace. The new
folder should have its own `BUILD` file containing a target to build
that code.

Code belongs at the "leaves" of your directory tree. E.g., if
`.../foo/Foo.java` exists, you don't want to create
`.../foo/bar/Bar.java` in a subdirectory. (Or if you do, then you want
to move the other foo code to `../foo/justfoonotbar/Foo.java` or
somesuch.) This keeps all the code for a package in 1 Folder, 1 BUILD
target.

**1:1:1** is a "rule of thumb", not a law. If your code breaks this
rule, it will still build. **1:1:1** tends to make your code easier to
work with.

If you're new to Pants, you might feel overwhelmed by all these `BUILD`
files; you might think it's simpler to have fewer of them: maybe just
one `BUILD` file in the "top folder" for a project that builds code from
several directories. But this "target coarseness" can waste your time:
you have a huge target that depends on everything that your source
depends on. If you divide your code into smaller, coherent targets, each
of those targets has only a subset of those dependencies.

Avoid rglobs
------------

Many pants targets have sources, a list of filenames owned by the
target. It's common pattern to specify source files with globs; it's a
common *anti-pattern*, especially in targets hastily converted from
Maven poms, to specify source files with rglobs, the recursive version
of globs.

While valid, rglobs increases the chances of multiple targets claiming
the same sources. Consider the following refactor adding a subpackage:

    :::python
    # 'maint' subpackage has been added.
    # src/java/com/twitter/tugboat/BUILD
    # src/java/com/twitter/tugboat/Tugboat.java
    # src/java/com/twitter/tugboat/maint/BUILD
    # src/java/com/twitter/tugboat/maint/MaintenanceLog.java

    # target src/java/com/twitter/tugboat
    # Existing target now unintentionally claims the 'maint' package.
    java_library(name='tugboat',
      sources=rglobs('*.java'),
    )

    # target src/java/com/twitter/tugboat/maint
    # Sources are claimed by multiple targets.
    java_library(name='maint',
      sources=globs('*.java'),
    )

Existing tugboat users now depend on tugboat's maint package, even
though the dependency was never intended. **Avoiding rglobs helps avoid
surprises.**

Using `rglobs` also makes it easy to fall into making circular
dependencies. You want to avoid circular dependencies. If you later want
to factor your big target into a few focused-purpose targets, you'll
have to untangle those circular dependencies.

When a target should claim files in subpackages, it's both easy and
recommended to explicitly list which subpackages should be claimed.

    :::python
    # target src/java/com/twitter/tugboat
    # Intentionally claims the 'maint' package.
    java_library(name='tugboat',
      sources=globs(
        '*.java',
        'maint/*.java',
      ),
    )

Define Separate Targets for Interface and Implementation
--------------------------------------------------------

If your code defines an API to be used by other modules, define a target
that builds just that interface.

Many programs provide a plugin interface so users can provide their own
functionality. For example, a tool might define a `DataImporter` interface
and let users provide plugins for each data source.

The simple approach of providing a single BUILD target for both
interface and implementations has a significant drawback: anyone wishing
to implement the interface must also depend on all dependencies for all
implementations co-published with the interface. The classpath bloats.
The risk of dependency conflicts increases greatly. For example:

    :::python
    # Less than ideal layout - interface and implementations together.
    # src/java/com/twitter/etl/from/BUILD
    # src/java/com/twitter/etl/from/DataImporter.java
    # src/java/com/twitter/etl/from/FileDataImporter.java
    # src/java/com/twitter/etl/from/HBaseDataImporter.java

    # DO NOT bundle interface and implementations - forces extra dependencies.
    java_library(name='from',
      dependencies=[
        '3rdparty/jvm/org/apache/hbase',
      ],
      sources=globs('*.java'),
    )

To avoid this bloat, define separate packages for code that introduces many extra dependencies.
For example, if `FileDataImporter.java` only uses standard library classes, it's appropriate to
package it with the interface. HBase, however, is quite large, has many transitive dependencies,
and is only required by jobs that actually read from HBase. Not `DataImporter` user wants to pull
down all those dependencies. Separate it out into its own target:

    :::python
    # Ideal repo layout - hbase as a subpackage and separate target.
    # src/java/com/twitter/etl/from/BUILD
    # src/java/com/twitter/etl/from/DataImporter.java
    # src/java/com/twitter/etl/from/FileDataImporter.java
    # src/java/com/twitter/etl/from/hbase/BUILD
    # src/java/com/twitter/etl/from/hbase/HBaseDataImporter.java

    # pants target src/java/com/twitter/etl/from
    # Including FileDataImporter is appropriate because it has no additional dependencies.
    java_library(name='from',
      dependencies=[], # no extra dependencies
      sources=globs('*.java'),
    )

    # pants target src/java/com/twitter/etl/from/hbase
    java_library(name='hbase',
      dependencies=[
        '3rdparty/jvm/org/apache/hbase',
        'src/java/com/twitter/etl/from',
      ],
      sources=globs('*.java'),
    )

Existing code using a package for both an interface and implementations
should still expose the interface separately.

    :::python
    # Less than ideal layout - interface and implementations together.
    # src/java/com/twitter/etl/from/BUILD
    # src/java/com/twitter/etl/from/DataImporter.java
    # src/java/com/twitter/etl/from/FileDataImporter.java
    # src/java/com/twitter/etl/from/HBaseDataImporter.java

    # Default target contains interface and lightweight implementation.
    java_library(name='from',
      sources=[
        'DataImporter.java',
        'FileDataImporter.java',
      ],
    )

    # Implementation with heavyweight dependencies exposed separately.
    java_library(name='hbase',
      dependencies=[
        '3rdparty/jvm/org/apache/hbase',
        'src/java/com/twitter/etl/from',
      ],
      sources=['HBaseDataImporter.java'],
    )

Depend on API in Library Targets, Implementation in Binary Targets
------------------------------------------------------------------

Some projects helpfully publish their API separately from
implementation, especially if multiple implementations are available.
SLF4J is a widely-used example.

Consider the following library target that depends on both slf4j-api and
the specific implementation slf4j-jdk14.

    :::python
    # Incorrect - forces a logging implementation on all library users.
    scala_library(name='mylib',
      dependencies=[
        '3rdparty:slf4j-api',
        '3rdparty:slf4j-jdk14',
      ],
    )

    jvm_binary(name='mybin',
      dependencies=[':mylib'],
    )

Structure these dependencies to only depending on the API in library
code. Allow binary targets to specify the logging implementation of
their choosing.

    :::python
    # Better approach - only depend on API in a library target.
    scala_library(name='mylib',
      dependencies=[
        '3rdparty:slf4j-api',
      ],
    )

    # Bring your own API implementation in the binary.
    jvm_binary(name='mybin',
      dependencies=[
        '3rdparty:slf4j-jdk14',
        ':mylib',
      ],
    )

Which `BUILD` Files are "Executed"? (and how?)
----------------------------------------------

`BUILD` files are little Python scripts. When you notice a target in one
`BUILD` file can depend on a target in another `BUILD` file, you might
think those little Python scripts are linked together into one big
Python program, but that's not exactly what's going on. If one `BUILD`
file has a Python variable `x = "Hello world"` and another `BUILD` file
says `print(x)`, you'll get an error: `x` is not defined.

Pants executes `BUILD` files separately. Commands in `BUILD` files
define targets and register those targets in a Pants data structure.

Though your repo might contain many `BUILD` files, Pants might not
execute all of them. If you invoke:

    :::bash
    ./pants test examples/tests/java/org/pantsbuild/example/hello/greet:greet

Pants executes the source tree's top-level `BUILD` file (executed on
every Pants run) and
`examples/tests/java/org/pantsbuild/example/hello/greet/BUILD`. The `greet`
target depends on targets from other `BUILD` files, so Pants executes
those `BUILD` files, too; it iterates over the dependency tree,
executing `BUILD` files as it goes. It does *not* execute `BUILD` files
that don't contain targets in that dependency tree.

If there's some `BUILD` code that should be executed on every run, put
it in the source tree's top-level `BUILD` file; that gets executed on
every Pants run.

`BUILD.*` files
--------------

We call them "`BUILD` files" because they're usually named `BUILD`, but
they can also be named `BUILD.something`, where *something* is typically
a short nickname for an organization, e.g., `BUILD.twitter`. This can be
handy if your organization has some internal definitions that you need
to combine with code that you open-source, perhaps a `credentials`
definition that only makes sense behind your organization's firewall.

A build target defined in `BUILD.foo` can't have the same `name` as a
build target defined in the same directory's `BUILD` file; they share a
namespace.

<a pantsmark="build_pants_wrapper_gone"> </a>

What happened to the `pants()` wrapper around targets?
------------------------------------------------------

If you have an existing project using Pants and have recently upgraded, you
may encounter this exception:

    AddressLookupError: name 'pants' is not defined

In previous versions of Pants, targets declared in the `dependencies`
attribute had to be wrapped in a call to the `pants()` method:

    :::python
    java_library(name='foo',
        dependencies=[pants('bar')])

The `pants()` method has since been replaced with a noop and as of Pants 0.0.24 is officially
deprecated. As of pants 0.0.46, use of this method now triggers an exception. Thus, the above
snippet should be re-written to use the target as a plain string:

    :::python
    java_library(name='foo',
        dependencies=['bar'])

You can use `sed` or a similar utility to quickly remove these
references from your BUILD files with a regular expression.

    :::bash
    # Run this command from the root of your repo.
    $ sed -i "" -e 's/pants(\([^)]*\))/\1/g' `find . -name "BUILD*"`
