Pants Concepts
==============

To use Pants effectively, it helps to understand a few concepts:

+ **Goals** help users tell pants what actions to take
+ **Tasks** are the pants modules that run actions
+ **Targets** describe what files to take those actions upon
+ **Target types** define the types of operations that can be performed on
a target
+ **Addresses** describe the location of a target in the repo

Goals and Tasks
---------------

**Goals** are the "verbs" of Pants.  When you invoke Pants, you name
goals on the command line to say what Pants should do. For example, to
run tests, you would invoke Pants with the `test` goal. To create a
bundle--an archive containing a runnable binary and resource
files--you would invoke Pants with the `bundle` goal.

**Tasks** actually perform the work.  When you invoke a goal, it finds
all the tasks needed to make that goal work. Sometimes, there is a one
to one mapping between a task name and a goal name, but often multiple tasks
are registered in a goal.  For example, the `junit`
task runs tests for JVM projects.  It is registered in the `test`
goal and sometimes referred to as `test.junit`.

In a nutshell, goals are the way users specify tasks.  Sometimes goals
are helpful groupings of tasks to make it easier for users to tell
pants what they want to do.

Tasks can depend on other tasks. When you invoke a goal in
Pants, it builds a list of dependent tasks that need to be executed
first.  So, when you invoke the `test` goal, it will also invoke the
tasks in the `gen`, `resolve` and `compile` goals, because tasks for
code generation, artifact resolution, and compilation need to occur
before a test can be run.  To find out more about how task dependencies
are computed, read about *product types* in
[[Developing a Pants Task|pants('src/docs:dev_tasks')]].

Targets
-------

**Targets** are the "nouns" of Pants, things pants can act upon. You
annotate your source code with `BUILD` files to define these
targets. For example, if your `tests/com/twitter/mybird/` directory
contains JUnit tests, you have a `tests/com/twitter/mybird/BUILD` file
with a `junit_tests` target definition. As you change your source code,
you'll occasionally change the set of Targets by editing `BUILD` files.
E.g., if you refactor some code, moving part of it to a new directory,
you'll probably set up a new `BUILD` file with a target to build that
new directory's code.

Targets can "depend" on other targets. For example, if your `foo` code
imports code from another target `bar`, then `foo` depends on `bar`. You
specify this dependency in `foo`'s target definition in its `BUILD`
file. If you invoke Pants to compile `foo`, it "knows" it also needs to
compile `bar`, and does so.


Target Types
------------

**Target Types** describe the kind of target to be operated on. Each
Pants build target has a *type*, such as `java_library` or
`python_binary`. Tasks choose to work on particular targets by
selecting the target types they are interested in from the build
graph.

For a list of all Target types (and other things that can go in `BUILD`
files), see the <a href="build_dictionary.html">BUILD Dictionary</a>.
The following list describes the most common target types:

**Library Targets**<br>
To define an "importable" thing, you want a library target type, such as
`java_library` or `python_library`. Another target whose code imports a
library target's code should list the library target in its
`dependencies`.

**Binary Targets**<br>
To define a "runnable" thing, you want a `jvm_binary` or `python_binary`
target. A binary probably has a `main` and dependency libraries. (We encourage a
binary's main to be separate from the libraries it uses to run, if any.)

**External Dependencies**<br>
Not everything is source code is in your repository. Your targets can
depend on `.jar`s or `.whl`s from elsewhere.

**Test Targets**<br>
To define a collection of tests, you want a `junit_tests` or
`python_tests` target. The test target depends upon the targets whose
code it tests. This isn't just logical, it's handy, too: you can
compute dependencies to figure out what tests to run if you change some
target's code.

Addresses
---------
**Addresses**  describe the location of a target in the build
graph.  The address has two parts:  the directory to the BUILD file
and the name of the target within that BUILD file.

For example, if you have a `tests/com/twitter/mybird/BUILD` file
with a `junit_tests(name='test-flight)` target definition, you would
write the address as:

    tests/com/twitter/mybird:test-flight

You use an address whenever you specify a target to build on the
command line or when one target depends on another in a BUILD file.
To find out more about addresses, see
[[Target Addresses|pants('src/docs:target_addresses')]].


What Pants Does
---------------

When you invoke Pants, you specify goals (actions to take) and targets
(things to act upon).

**Pants plans a list of tasks.** You specify one or more goals on the
command line. Pants finds the tasks needed to complete that goal.
Pants knows that some tasks depend on others. If you
invoke Pants with, say, the `test` goal to test some code, Pants knows
it must first compile code; before it can compile code, it needs to
resolve artifact dependencies and generate code from IDL files (e.g.,
Thrift). Pants thus generates a topologically-sorted list of goals and
tasks to perform, a
*build execution plan*. This plan might look something like

    :::bash
	./pants --explain test src/java::
	Goal Execution Order:

	bootstrap -> imports -> unpack-jars -> deferred-sources -> gen
       -> jvm-platform-validate -> resolve -> compile -> resources -> test

Pants does *not* consider targets while planning; some of these tasks
might thus turn out to be no-ops. E.g., Pants might plan a `gen`
(generate code) task even if you don't, in fact, use any generated code.

**Pants computes a target dependencies graph.** It starts with the
target[s] you specify on the command line. It notes which targets they
depend on, which targets those targets depend on, which targets *those*
targets depend on, and so on.

**Pants then attempts to carry out its planned tasks.** It proceeds goal
by goal. If it has a problem carrying out one task, it does not continue
to the others. (Thus, if you attempt to test targets *A* and *B*,
but there's a compilation error in *A*, then Pants won't test *B* even
if it compiled fine.)

For each task in the plan, Pants executes that task to all
targets in its computed dependency tree[s]. It starts with
depended-upon targets and works its way up to depending targets. Each
Pants target has a type; Pants uses this to determine how to apply a
task to that target. In many cases, applying a task to a target is a
no-op. In the more interesting cases, Pants does something. It
probably invokes other tools. For example, depending on the code in
the relevant targets, that "compile" goal might invoke `javac` a few
times and `scalac`.

Pants caches things it builds. Thus, if you change one source file and
re-build, Pants probably doesn't "build the world." It just builds a few
things. Pants keys its cache on hashed file contents. This is a
straightforward way to build the right things after some files' contents
change. (It *can* surprise you if you `touch` a file, start a compile,
and nothing happens. If you want to, e.g., see `Foo.java`'s compile
warnings again, instead of using `touch`, you might append a newline.)

Next Step
---------

If you're ready to give Pants a try, go to
[[First Tutorial|pants('src/docs:first_tutorial')]].
