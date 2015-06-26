Task Developer's Guide
======================

In Pants, code that does "real build work" (e.g., downloads prebuilt
artifacts, compiles Java code, runs tests) lives in *Tasks*. To add a
feature to Pants so that it can, e.g., compile a new language, you want
to write a new Task.

This page documents how to develop a Pants Task, enabling you to teach
pants how to do things it does not already know how to do today. To see
the Tasks that are built into Pants, look over
`src/python/pants/backend/*/tasks/*.py`. The code makes more sense if
you know the concepts from internals. The rest of this page introduces
some concepts especially useful when defining a Task.

Hello Task
----------

To implement a Task, you define a subclass of
[pants.backend.core.tasks.task.Task](https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/core/tasks/task.py)
and define an `execute` method for that class. The `execute` method does
the work.

The Task can see (and affect) the state of the build via its `.context`
member, a
[pants.goal.context.Context](https://github.com/pantsbuild/pants/blob/master/src/python/pants/goal/context.py).

**Which targets to act on?** A typical Task wants to act on all "in
play" targets that match some predicate. Here, "'in play' targets" means
those targets the user specified on the command line, the targets needed
to build those targets, the targets needed to build *those* targets,
etc. Call `self.context.targets()` to get these. This method takes an
optional parameter, a predicate function; this is useful for filtering
just those targets that match some criteria.

Task Installation: Associate Task with Goal[s]
----------------------------------------------

Defining a Task is nice, but doesn't hook it up so users can get to it.
*Install* a task to make it available to users. To do this, you register
it with Pants, associating it with a goal. A plugin's `register.py`
registers goals in its `register_goals` function. Here's an excerpt from
[Pants' own JVM
backend](https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/jvm/register.py):

!inc[start-after=pants/issues/604 register_goals&end-before=Compilation](../backend/jvm/register.py)

That `task(...)` is a name for
`pants.goal.task_registrar.TaskRegistrar`. Calling its `install` method
installs the task in a goal with the same name. To install a task in
goal `foo`, use `Goal.by_name('foo').install`. You can install more than
one task in a goal; e.g., there are separate tasks to run Java tests and
Python tests; but both are in the `test` goal.

`product_types` and `require_data`: Why "test" comes after "compile"
--------------------------------------------------------------------

It might only make sense to run your Task after some other Task has
finished. E.g., Pants has separate tasks to compile Java code and run
Java tests; it only makes sense to run those tests after compiling. To
tell Pants about these inter-task dependencies...

The "early" task class defines a `product_types` class method that
returns a list of strings:

!inc[start-after=pants/issues/604 product_types start&end-before=pants/issues/604 product_types finish](../backend/jvm/tasks/ivy_imports.py)

The "late" task defines a `prepare` method that calls
`round_manager.require_data` to "require" one of those same strings:

!inc[start-after=pants/issues/604 prep start&end-before=pants/issues/604 prep finish](../backend/codegen/tasks/protobuf_gen.py)

Pants uses this information to determine which tasks must run first to
prepare data required by other tasks. (If one task requires data that no
task provides, Pants errors out.)

A task can have more than one product type. You might want to know which type[s] were `require`d
by other tasks. If one product is especially "expensive" to make, perhaps your task should only
do so if another task will use it. Use `self.context.products.isrequired` to find out if a task
required a product type. `isrequired` returns a predicate function that a task can use to find
out if any task required a product (`isrequired` returns `None` if none did) and which targets
were required&mdash;`require` takes an optional target filter predicate function; you can call
this function to find out which targets to generate the product for:

!inc[start-at=isrequired('jar_dependencies')&end-before=def](../backend/jvm/tasks/ivy_resolve.py)

Products Map: how one task uses products of another
---------------------------------------------------

One task might need the products of another. E.g., the Java test runner
task uses Java `.class` files that the Java compile task produces. Pants
tasks keep track of this in a
[pants.goal.products.ProductMapping.](https://github.com/pantsbuild/pants/blob/master/src/python/pants/goal/products.py)

The `ProductMapping` is basically a dict. Calling
`self.context.products.get('jar_dependencies')` looks up
`jar_dependencies` in that dict. Tasks can set/change the value stored
at that key; later tasks can read (and perhaps further change) that
value. That value might be, say, a dictionary that maps target specs to
file paths.

Task Configuration
------------------

Tasks may be configured via options.

To define an option, handle your Task's `register_options`
class method and call the passed-in `register` function:

!inc[start-after=ListGoals&end-before=console_output](../backend/core/tasks/list_goals.py)

Option values are available via `self.get_options()`:

    :::python
    # Did user pass in the --my-option CLI flag (or set it in .ini)?
    if self.get_options().my_option:

Every task has an options scope: If the task is registered as `task` in goal `goal`, then its
scope is `goal.task`, unless goal and task are the same string, in which case the scope is simply
that string. For example, the `JavaCompile` task has scope `compile.java`, and the `filemap`
task has the scope `filemap`.

The scope is used to set options values. E.g., the value of `self.get_options().my_option` for a
task with scope `scope` is set by, in this order:
  - The value of the cmd-line flag `--scope-my-option`.
  - The value of the environment variable `PANTS_SCOPE_MY_OPTION`.
  - The value of the config var `my_option` in section `scope`.

Note that if the task being run is specified explicitly on the command line, you can omit the
scope from the cmd-line flag name. For example, instead of
`./pants compile --compile-java-foo-bar` you can do `./pants compile.java --foo-bar`.


GroupTask
---------

Some `Task`s are grouped together under a parent `GroupTask`.
Specifically, the JVM compile tasks:

    :::python
    jvm_compile = GroupTask.named(
    'jvm-compilers',
    product_type=['classes_by_target', 'classes_by_source'],
    flag_namespace=['compile'])

    jvm_compile.add_member(ScalaCompile)
    jvm_compile.add_member(AptCompile)
    jvm_compile.add_member(JavaCompile)

A `GroupTask` allows its constituent tasks to 'claim' targets for
processing, and can iterate between those tasks until all work is done.
This allows, e.g., Java code to depend on Scala code which itself
depends on some other Java code.

JVM Tool Bootstrapping
----------------------

If you want to integrate an existing JVM-based tool with a pants task,
Pants must be able to bootstrap it. That is, a running Pants will need
to fetch the tool and create a classpath with which to run it.

Your job as a task developer is to set up the arguments passed to your
tool (e.g.: source file names to compile) and do something useful after
the tool has run. For example, a code generation tool would identify
targets that own IDL sources, pass those sources as arguments to the
code generator, create targets of the correct type to own generated
sources, and mutate the targets graph rewriting dependencies on targets
owning IDL sources to point at targets that own the generated code.
<!-- TODO(https://github.com/pantsbuild/pants/issues/681)
     highlight useful snippets instead of saying "here's a link to the
     source and a list of things we hope you notice" -->

The [Scalastyle](http://www.scalastyle.org/) tool enforces style
policies for scala code. The [Pants Scalastyle
task](https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/jvm/tasks/scalastyle.py)
shows some useful idioms for JVM tasks.

-   Inherit `NailgunTask` to avoid starting up a new JVM.
-   Specify the tool executable as a Pants `jar`; Pants knows how to
    download and run those.
-   Let organizations/users override the jar in `pants.ini`; it makes it
    easy to use/test a new version.

Enabling Caching For Tasks
--------------------------

Pants will attempt to read task results from the cache automatically, however,
Pants cannot automatically decide what to write to the cache. In a task's `execute` method,
you must manually provide each target and its artifacts as an update to the
cache.

A target's artifacts are the output files produced as a result of
processing the target via some job. For example, the output files of a `JavaCompile`
task on a target `java_library` would be the `.class` files produced by compiling
the library. In this scenario, the `java_library` (i.e. the target) would have its
sources used to compute a cache key, and the `.class` files would be used as the cached value.
Here is a template for how this process works in the `execute` method:

    def execute(self):
      targets = self.context.targets()
      with self.invalidated(targets) as invalidation_check:

        # for each VersionedTarget in invalidation_check.invalid_vts,
        # run your task on the target and remember where the output files are
        output_files = do_some_work()

        if self.artifact_cache_writes_enabled():
          # build a list of (VersionedTarget, output_files) pairs
          pairs = match_up(invalidation_check.invalid_vts, output_files)

          self.update_artifact_cache(pairs)

The above implementation writes each target/artifact (key/val) pair to the cache
independently of all other targets. If you instead want to write multiple
targets and their artifacts together under a single cache key (TODO: what is a
good example of when you would want to do this?), you can use a `VersionedTargetSet`
in place of a `VersionedTarget`, and group the `invalid_vts` within
`VersionedTargetSet`s. If you choose to do this, however, you must override
the `check_artifact_cache_for` method in your task to return the groupings
of targets you want to read (`VersionedTargetSet`s). If you don't, you will miss
the cache, because by default Pants reads each target from the cache
independently.

    def check_artifact_cache_for(self, invalidation_check):
      return [VersionedTargetSet.from_versioned_targets(invalidation_check.invalid_vts)]