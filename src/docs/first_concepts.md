Pants Conceptual Overview
=========================

Pants is a build system for software. It works particularly well for a source code workspace
containing many distinct but interdependent pieces.

Pants is similar to `make`, `maven`, `ant`, `gradle`, `sbt`, etc.; but
pants pursues different design goals. Pants optimizes for

-   building multiple, dependent things from source
-   building code in a variety of languages
-   speed of build execution

A Pants build "sees" only the target it's building and the transitive
dependencies of that target. This approach works well for a big
repository containing several things; a tool that builds everything
would bog down.

Goals and Targets
-----------------

To use Pants, you must understand a few concepts:

**Goals** are the "verbs" of Pants.<br>
When you invoke Pants, you name goals on the command line to say what
Pants should do. For example, to run tests, you would invoke Pants with
the `test` goal. To create a bundle--an archive containing a runnable
binary and resource files--you would invoke Pants with the `bundle`
goal. These goals are built into Pants.

**Targets** are the "nouns" of Pants, things pants can act upon.<br>
You annotate your source code with `BUILD` files to define these
targets. For example, if your `tests/com/twitter/mybird/` directory
contains JUnit tests, you have a `tests/com/twitter/mybird/BUILD` file
with a `junit_tests` target definition. As you change your source code,
you'll occasionally change the set of Targets by editing `BUILD` files.
E.g., if you refactor some code, moving part of it to a new directory,
you'll probably set up a new `BUILD` file with a target to build that
new directory's code.

When you invoke Pants, you specify goals and targets: the actions to
take, and the things to carry out those actions upon. Together, your
chosen goals and targets determine what Pants produces. Invoking the
`bundle` goal produces an archive; invoking the `test` goal displays
test results on the console. Assuming you didn't duplicate code between
folders, targets in `tests/com/twitter/mybird/` will have different code
than those in `tests/com/twitter/otherbird/`.

Goals can "depend" on other goals. For example, there are `test` and
`compile` goals. If you invoke Pants with the `test` goal, Pants "knows"
it must compile tests before it can run them, and does so. (This can be
confusing: you can invoke the `test` goal on a target that isn't
actually a test. You might think this would be a no-op. But since Pants
knows it must compile things before it tests them, it will compile the
target.)

Targets can "depend" on other targets. For example, if your `foo` code
imports code from another target `bar`, then `foo` depends on `bar`. You
specify this dependency in `foo`'s target definition in its `BUILD`
file. If you invoke Pants to compile `foo`, it "knows" it also needs to
compile `bar`, and does so.

Target Types
------------

Each Pants build target has a *type*, such as `java_library` or
`python_binary`. Pants uses the type to determine how to apply goals to
that target.

**Library Targets**<br>
To define an "importable" thing, you want a library target type, such as
`java_library` or `python_library`. Another target whose code imports a
library target's code should list the library target in its
`dependencies`.

**Binary Targets**<br>
To define a "runnable" thing, you want a `jvm_binary` or `python_binary`
target. A binary probably has a `main` and dependencies. (We encourage a
binary's main to be separate from the libraries it uses to run, if any.)

**External Dependencies**<br>
Not everything's source code is in your repository. Your targets can
depend on `.jar`s or `.eggs`s from elsewhere.

**Test Targets**<br>
To define a collection of tests, you want a `junit_tests` or
`python_tests` target. The test target depends upon the targets whose
code it tests. This isn't just logical, it's handy, too: you can
compute dependencies to figure out what tests to run if you change some
target's code.

For a list of all Target types (and other things that can go in `BUILD`
files), see the <a href="build_dictionary.html">BUILD Dictionary</a>.

What Pants Does
---------------

When you invoke Pants, you specify goals (actions to take) and targets
(things to act upon).

**Pants plans a list of goals.** You specify one or more goals on the
command line. Pants knows that some goals depend on others. If you
invoke Pants with, say, the `test` goal to test some code, Pants knows
it must first compile code; before it can compile code, it needs to
resolve artifact dependencies and generate code from IDL files (e.g.,
Thrift). Pants thus generates a topologically-sorted list of goals, a
*build execution plan*. This plan might look something like

> resolve-idl -\> gen -\> resolve -\> compile -\> resources -\> test

Pants does *not* consider targets while planning; some of these goals
might thus turn out to be no-ops. E.g., Pants might plan a `gen`
(generate code) goal even if you don't, in fact, use any generated code.

**Pants computes a target dependencies graph.** It starts with the
target[s] you specify on the command line. It notes which targets they
depend on, which targets those targets depend on, which targets *those*
targets depend on, and so on.

**Pants then attempts to carry out its planned goals.** It proceeds goal
by goal. If it has a problem carrying out one goal, it does not continue
to the other goals. (Thus, if you attempt to test targets *A* and *B*,
but there's a compilation error in *A*, then Pants won't test *B* even
if it compiled fine.)

For each goal, Pants attempts to apply that goal to all targets in its
computed dependency tree[s]. It starts with depended-upon targets and
works its way up to depending targets. Each Pants target has a type;
Pants uses this to determine how to apply a goal to that target. In many
cases, applying a goal to a target is a no-op. In the more interesting
cases, Pants does something. It probably invokes other tools. For
example, depending on the code in the relevant targets, that "compile"
goal might invoke `javac` a few times and `scalac`.

Pants caches things it builds. Thus, if you change one source file and
re-build, Pants probably doesn't "build the world." It just builds a few
things. Pants keys its cache on hashed file contents. This is a
straightforward way to build the right things after some files' contents
change. (It *can* surprise you if you `touch` a file, start a compile,
and nothing happens. If you want to, e.g., see `Foo.java`'s compile
warnings again, instead of using `touch`, you might append a newline.)

Why Choose Pants?
-----------------

As your engineering organization grows past 100 people, your codebase grows even faster.
As your codebase grows, your tools need to scale with it. If you keep buiding everything, builds
get slower. If you don't build everything, then you need to know which parts to build. You want
to decompose your code into parts, each part quickly buildable.

You need a way to keep track of which parts of your code depend on which other parts.

* To build *this* app, which code must be built? (And which can be ignored?)
* If you change *this* low-level "common" code, which other code is affected?

Pants eases this organization into quick-compiling pieces. Pants models code modules (known as
"targets") and their dependencies in `BUILD` files—in a manner similar to Google's [internal build
system](http://google-engtools.blogspot.com/2011/08/build-in-cloud-how-build-system-works.html).
It builds only the parts of the codebase you actually need, ignoring the rest.

Pants builds faster because it builds less. It helps you organize your code into small chunks and it
only builds the chunks you need. As your codebase grows and those chunks grow, it's relatively easy
to subdivide them into more chunks. Pants supports local and distributed caching so it doesn't
re-build things it doesn't have to. If you make a small change, Pants can do a quick incremental
build.

Pants features include:

- Builds [Java, Scala](http://pantsbuild.github.io/JVMProjects.html), and
  [Python](http://pantsbuild.github.io/python-readme.html).
- Generates code from [thrift](http://pantsbuild.github.io/ThriftDeps.html), Protocol
  Buffers.
- Supports a distributed cache.
- Fetches external dependencies from Maven (JVM) repos and Pypi-like Python package repos.
- Runs tests, spawns REPLs, builds deployable packages.
- Runs on Linux and Mac OS X.

Where Pants is missing a feature you need, adding that feature may be easier than you thought.
You can extend Pants with plugins written in Python. Support for new languages is especially
straightforward. Pants' active developer community is eager to integrate your improvements to Pants.

If your codebase is growing beyond your toolchain's capacity but you're reluctant to divide it
into totally separate projects, you might want to give Pants a try. It may be of particular
interest if you have complex dependencies, generated code, and custom build steps.

Next Step
---------

If you're ready to give Pants a try, go to
[[First Tutorial|pants('src/docs:first_tutorial')]].
