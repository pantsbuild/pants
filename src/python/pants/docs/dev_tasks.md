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
[pants.task.task.Task](https://github.com/pantsbuild/pants/blob/master/src/python/pants/task/task.py)
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
it with Pants, associating it with a goal. A [[plugin's|pants('src/python/pants/docs:howto_plugin')]] `register.py`
registers goals in its `register_goals` function. Here's an excerpt from
[Pants' own Python
backend](https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/python/register.py):

!inc[start-at=def register_goals&end-at=Python projects from python_library](../backend/python/register.py)

That `task(...)` is a name for
`pants.goal.task_registrar.TaskRegistrar`. Calling its `install` method
installs the task in a goal with the same name. To install a task in
goal `foo`, use `Goal.by_name('foo').install`. You can install more than
one task in a goal; e.g., there are separate tasks to run Java tests and
Python tests; but both are in the `test` goal.

Products: How one Task consumes the output of another
---------------------------------------------------

One task might need to consume the "products" (outputs) of another. E.g., the Java test runner
task uses Java `.class` files that the Java compile task produces. Pants
tasks keep track of this in the
[pants.goal.products.ProductMapping](https://github.com/pantsbuild/pants/blob/master/src/python/pants/goal/products.py)
that is provided in the task's context at `self.context.products`.

The `ProductMapping` is basically a dict. Calling
`self.context.products.get('jar_dependencies')` looks up
`jar_dependencies` in that dict. Tasks can set/change the value stored
at that key; later tasks can read (and perhaps further change) that
value. That value might be, say, a dictionary that maps target specs to
file paths.

`product_types` and `require_data`: Why "test" comes after "compile"
--------------------------------------------------------------------

It might only make sense to run your Task after some other Task has
finished. E.g., Pants has separate tasks to compile Java code and run
Java tests; it only makes sense to run those tests after compiling. To
tell Pants about these inter-task dependencies...

The "early" task class defines a `product_types` class method that
returns a list of strings:

!inc[start-at=  def product_types&end-at=runtime_classpath](../backend/jvm/tasks/resources_task.py)

The "late" task defines a `prepare` method that calls
`round_manager.require_data` to "require" one of those same strings:

!inc[start-at=  def prepare&end-at=runtime_classpath](../backend/jvm/tasks/detect_duplicates.py)

Pants uses this information to determine which tasks must run first to
prepare data required by other tasks. (If one task requires data that no
task provides, Pants errors out.)

A task can have more than one product type. You might want to know which type[s] were `require`d
by other tasks. If one product is especially "expensive" to make, perhaps your task should only
do so if another task will use it. Use `self.context.products.isrequired` to find out if a task
required a product type:

!inc[start-at=products.isrequired(&end-before=def](../backend/jvm/tasks/jvmdoc_gen.py)

Task Configuration
------------------

Tasks may be configured via the options system.

To define an option, implement your Task's `register_options`
class method and call the passed-in `register` function:

!inc[start-at=  def register_options&end-before=--confs](../backend/jvm/tasks/checkstyle.py)

Option values are available via `self.get_options()`:

    :::python
    # Did user pass in the --my-option CLI flag (or set it in pants.ini)?
    if self.get_options().my_option:

### Scopes

Every task has an options *scope*: If the task is registered as `my-task` in goal `my-goal`, then its
scope is `my-goal.my-task`, unless goal and task are the same string, in which case the scope is simply
that string. For example, the `ZincCompile` task has scope `compile.zinc`, and the `filemap`
task has the scope `filemap`.

The scope is used to set options values. E.g., the value of `self.get_options().my_option` for a
task with scope `scope` is set by, in this order:
  - The value of the cmd-line flag `--scope-my-option`.
  - The value of the environment variable `PANTS_SCOPE_MY_OPTION`.
  - The value of the pants.ini var `my_option` in section `scope`.

Note that if the task being run is specified explicitly on the command line, you can omit the
scope from the cmd-line flag name. For example, instead of
`./pants compile --compile-java-foo-bar` you can do `./pants compile.java --foo-bar`. See
[[Invoking Pants|pants('src/docs:invoking')]] for more information.

### Fine-tuning Options

When calling the `register` function, passing a few additional arguments
will affect the behaviour of the registered option. The most common parameters are:

- `type`: Constrains the type of the option. Takes a python type constructor (like `int`), or a
  constructor like `list_option` from [pants.option.custom_types](https://github.com/pantsbuild/pants/blob/master/src/python/pants/option/custom_types.py). If not specified, the option will be a string.
- `default`: Sets a default value that will be used if the option is not specified by the user.
- `action`: A string action that specifies that passing the registered option should do something other than
  set a literal value (which is the default when no `action` is specified.) The two most common actions are:
    - *store_true*: Causes the presence of the option to set the option value to `True`. Also automatically
    creates an inverse option prefixed with "--no-".
    - *append*: If an option is specified multiple times, the `append` action will append them to a list
    representing the option's value.
- `advanced`: Indicates that an option is intended either for use by power users, or for use in
  pants.ini. By default, advanced options are not displayed in `./pants help`.
- `fingerprint`: Indicates that the value of the registered option affects the products
  of the task, such that changing the option would result in different products. When `True`,
  changing the option will cause targets built by the task to be invalidated and rebuilt.


GroupTask
---------

`Task`s may be grouped together under a parent `GroupTask`.
Specifically, the JVM compile tasks:

    :::python
    jvm_compile = GroupTask.named(
    'jvm-compilers',
    product_type=['compile_classpath', 'classes_by_source'],
    flag_namespace=['compile'])

    jvm_compile.add_member(AptCompile)
    jvm_compile.add_member(ZincCompile)

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

Enabling Artifact Caching For Tasks
--------------------------

An artifact is the output file produced by a task processing some target.
For example, the artifacts of a `JavaCompile` task on a target
`java_library` would be the `.class` files produced by compiling the library.
In this scenario, the `java_library` (i.e. the target) would have its sources
used to compute a cache key, and the `.class` files would be used as the cached value.

If your task follows an isolated strategy where each target produces artifacts into
its own directory, then the task will be able to take advantage of automatic
target workdir caching. If your task has more complicated behavior
(for example, all targets produce artifacts into the same directory), then check
out the manual caching section below.

**Automatic target workdir caching**

Automatic target workdir caching works by assigning a results directory to
each VersionedTarget (VT) of the InvalidationCheck yielded by `Task->invalidated`.
A task operating on a given VT should place the resulting artifacts in the VT's
`results_dir`. After exiting the `invalidated` context block, these artifacts
will be automatically uploaded to the artifact cache.

This interface for caching is disabled by default. To enable, override
`Task->cache_target_dirs` to return True.

**Manual caching**

Manual caching is much more complicated than automatic target workdir caching,
and as such should only be used for non-standard usecases. Instead of placing
artifacts in known target directories, artifacts may be placed anywhere -- although
it is now the responsibility of the task developer to manually upload
VT / artifact pairs to the cache. Here is a template for how manual caching
would be implemented in the `execute` method:

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
independently of all other targets. However you might want to write multiple
targets and their artifacts together under a single cache key. A good example of
this is Ivy resolution, where the set of resolved 3rd party dependencies is a property
of all targets taken together, not of each target individually.

To implement caching for groupings of targets, you can use a `VersionedTargetSet`
in place of a `VersionedTarget`, and group the `invalid_vts` within
`VersionedTargetSet`s. If you choose to do this, however, you must override the
`check_artifact_cache_for` method in your task to return the groupings
of targets you want to read (`VersionedTargetSet`s). If you don't, you will miss
the cache, because by default Pants reads each target from the cache
independently.

    def check_artifact_cache_for(self, invalidation_check):
      return [VersionedTargetSet.from_versioned_targets(invalidation_check.invalid_vts)]
