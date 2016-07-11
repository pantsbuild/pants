BUILD files
===========

A large, well-organized codebase divides into many small components. These components,
and the code dependencies between them, form a directed graph.

In Pants paralance, these components are called _targets_. The information about your
targets and their dependencies lives in files named `BUILD`, scattered throughout your
source tree. A `BUILD` file in a given directory describes targets that own the
source files in or under that directory.

+ See [[tutorial|pants('src/docs:first_tutorial')]] for an easy introduction to `BUILD` files.
+ See the [BUILD Dictionary](build_dictionary.html) for an exhaustive list of all `BUILD` file syntax.

Target Granularity
------------------

A target can encapsulate any amount of code, from a single source file to
(as a silly hypothetical) the entire codebase.  In practice, you'll want to
pick a granularity that reflects a "sensible" level at which to express
dependencies: Too coarse, and you lose the benefits of fine-grained invalidation.
Too fine, and you drown in BUILD boilerplate.

Many programming languages (E.g., Java, Python, Go) have a concept of a _package_, usually
corresponding to a single filesystem directory. It turns out that this is often the appropriate level
of granularity for targets.  The idiom of having one target per directory, representing
a single package, is sometimes referred to as the _1:1:1 rule_. It's by no means required,
but has proven in practice to be a good rule of thumb.  And of course there are always exceptions.

Note that Pants forbids circular dependencies between targets. That is, the dependency graph must
be a DAG. In fact, this is good codebase hygiene in general. So if you have any tightly-bound
cross dependencies between certain packages, they will all have to be part of a single target until
you untangle the dependency "hairball".


Target Definitions
------------------

A target definition in a `BUILD` file looks something like

    :::python
    java_library(
      name='util',
      dependencies = [
        '3rdparty:commons-math',
        '3rdparty:thrift',
        'src/java/org/pantsbuild/auth',
        ':base'
      ],
      sources=globs('*.java', exclude=[['Base.java']]),
    )

**java_library**<br>
Each target will have a different _target type_, which is `java_library` in this case.
This tells Pants tasks what can be done with the target.


**name**<br>
The target's name, along with the path to its BUILD file, forms its _address_.
The address has two important roles:

+ It's used on the command line to specify which targets to operate on.
+ It's used in other `BUILD` files to reference the target as a dependency.


**dependencies**<br>
List of targets that this target depends upon. If this target's code imports
or otherwise depends on code in other targets, list those targets here.

+ To reference a target `target` defined in `path/to/BUILD` use `path/to:target`.
+ If the target has the same name as the BUILD file's directory, you can omit the repetition:
  <br>`path/to/target` instead of `path/to/target:target`.
+ If the target is defined in the same BUILD file, you can omit the path:
  <br>`:target` instead of `path/to:target`.
+ [[More details|pants('src/docs:target_addresses')]] on how to address targets in a list of dependencies.


**sources**<br>
The source files in this target. These are usually specified in one of two ways:

+ Enumerating the files: `sources=['FileUtil.java', 'NetUtil.java']`.
+ Globbing over the files in the BUILD file's directory: `sources=globs('*.java')`.
  <br>This means you don't have to modify your BUILD file when you add a new source file.

You can exclude files from the results of a glob. For example, to glob over unit tests
but not integration tests you could use something like this:
<br>`sources=globs('*.py', exclude=[globs('*_integration.py')])`.
<br>The value of `exclude=` is a list of things that evaluate to lists of source files,
i.e., globs or literal lists. This is why there are double-brackets around `Base.java` in
the example target above.

You can also recursively glob over files in all subdirectories of the BUILD file's directory: `sources=rglobs('*.java')`.
However this is discouraged as it tends to lead to coarse-grained dependencies, and Pants's
advantages come into play when you have many fine-grained dependencies.

`BUILD.*` files
---------------

BUILD files are usually just named `BUILD`, but they can also be named `BUILD.ext`, with any
extension.  Pants considers all files matching `BUILD(.*)` in a single directory to be a single
logical BUILD file. In particular, they share a single namespace, so target names must be
distinct across all such files.

This has various uses, such as the ability to separate internal-only BUILD definitions from those
that should be pushed to an open-source mirror of an internal repo: You can put the former
in `BUILD.internal` files and the latter in `BUILD.oss` files.


Debugging BUILD Files
---------------------

If you're curious to know how Pants interprets your `BUILD` files, these
techniques can be especially helpful:

*What targets does a BUILD file define?* Use the `list` goal:

    :::bash
    $ ./pants list examples/src/java/org/pantsbuild/example/hello/greet
    examples/src/java/org/pantsbuild/example/hello/greet:greet

*Are any BUILD files broken?*
List **every** target to see if there are any errors:
Use the  recursive wildcard `::` with the list goal:

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

*Do I pull in the transitive dependencies I expect?* Use `depmap`:

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
    ~archie/workspace/pants/examples/src/java/org/pantsbuild/example/hello/greet/BUILD
    ~archie/workspace/pants/examples/src/java/org/pantsbuild/example/hello/main/config/greetee.txt
    ~archie/workspace/pants/examples/src/resources/org/pantsbuild/example/hello/BUILD
    ~archie/workspace/pants/examples/src/java/org/pantsbuild/example/hello/main/HelloMain.java
    ~archie/workspace/pants/examples/src/resources/org/pantsbuild/example/hello/world.txt
    ~archie/workspace/pants/examples/src/java/org/pantsbuild/example/hello/main/BUILD
    ~archie/workspace/pants/examples/src/java/org/pantsbuild/example/hello/greet/Greeting.java

Use the `-h` flag to get help on these commands and their various options.
