######################
Task Developer's Guide
######################

In Pants, code that does "real build work"
(e.g., downloads prebuilt artifacts, compiles Java code, runs tests)
lives in *Tasks*. To add a feature to Pants so that it can, e.g.,
compile a new language, you want to write a new Task.

This page documents how to develop a Pants Task, enabling you to teach pants
how to do things it does not already know how to do today.
To see the Tasks that are built into Pants, look over
``src/python/pants/backend/*/tasks/*.py``.
The code makes more sense if you know the concepts from :doc:`internals`.
The rest of this page introduces some concepts especially useful when
defining a Task.

Hello Task
==========

To implement a Task, you define a subclass of
`pants.backend.core.tasks.task.Task <https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/core/tasks/task.py>`_
and define an ``execute`` method for that class.
The ``execute`` method does the work.

The Task can see (and affect) the state of the build via its
``.context`` member, a
`pants.goal.context.Context. <https://github.com/pantsbuild/pants/blob/master/src/python/pants/goal/context.py>`_

**Which targets to act on?** A typical Task wants to act on all "in play"
targets that match some predicate. Here, "'in play' targets" means those
targets the user specified on the command line, the targets needed to build
those targets, the targets needed to build *those* targets, etc. Call
``self.context.targets()`` to get these.  This method takes an optional
parameter, a predicate function; this is useful for filtering just those
targets that match some criteria.

Task Installation: Associate Task with Goal[s]
==============================================

Defining a Task is nice, but doesn't hook it up so users can get to it.
*Install* a task to make it available to users. To do this,
you register it with Pants, associating it with a goal.
A plugin's ``register.py`` registers goals in its ``register_goals``
function. Here's an excerpt from
`Pants' own JVM backend <https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/jvm/register.py>`_:

.. literalinclude:: ../backend/jvm/register.py
   :start-after: pants/issues/604 register_goals
   :end-before: Compilation

That ``task(...)`` is a name for ``pants.goal.task_registrar.TaskRegistrar``.
Calling its ``install`` method installs the task in a goal with the same name.
To install a task in goal ``foo``, use ``Goal.by_name('foo').install``.
You can install more than one task in a goal; e.g., there are separate tasks
to run Java tests and Python tests; but both are in the ``test`` goal.

product_types and require_data: Why "test" comes after "compile"
================================================================

It might only make sense to run your Task after some other Task has finished.
E.g., Pants has separate tasks to compile Java code and run Java tests; it
only makes sense to run those tests after compiling. To tell Pants about
these inter-task dependencies...

The "early" task class defines a ``product_types`` class method that
returns a list of strings:

.. literalinclude:: ../backend/jvm/tasks/ivy_imports.py
   :start-after: pants/issues/604 product_types start
   :end-before: pants/issues/604 product_types finish

The "late" task defines a ``prepare`` method that calls
``round_manager.require_data`` to "require" one of those
same strings:

.. literalinclude:: ../backend/codegen/tasks/protobuf_gen.py
   :start-after: pants/issues/604 prep start
   :end-before: pants/issues/604 prep finish

Pants uses this information to determine which tasks must run
frist to prepare data required by other tasks. (If one task requires
data that no task provides, Pants errors out.)

Products Map: how one task uses products of another
===================================================

One task might need the products of another. E.g., the Java test runner
task uses Java ``.class`` files that the Java compile task produces.
Pants tasks keep track of this in a
`pants.goal.products.ProductMapping. <https://github.com/pantsbuild/pants/blob/master/src/python/pants/goal/products.py>`_

The ``ProductMapping`` is basically a dict.
Calling ``self.context.products.get('jar_dependencies')`` looks up
``jar_dependencies`` in that dict. Tasks can set/change the value stored
at that key; later tasks can read (and perhaps further change) that value.
That value might be, say, a dictionary that maps target specs to file paths.

require_data, is_required
-------------------------

It might "expensive" for a task to generate some not-always-useful product.
E.g., if Ivy takes a while to compute jar dependencies but they're not always
needed, then it might make sense to skip generating them in most cases.
In one tasks's ``__init__``, it can call
``self.context.products.isrequired('jar_dependencies')`` to say it needs that
data.
The Ivy task uses ``if self.context.products.isrequired('jar_dependencies'):``
to find out if another task needs this data.

Task Configuration
==================

Tasks may be configured in two ways:

* a configuration file
* command-line flags

The configuration file is normally called ``pants.ini`` and is a standard
``ini`` file loaded with ``ConfigParser``. During instantiation, tasks have
access to a ``pants.base.config.Config`` to read these settings. ::

   # Let's read mykey from the mytask pants.ini section.
   self.context.config.get('mytask', 'mykey')

To define a command-line flag, handle your Task's ``register_options`` class
method and call the passed-in ``register`` function:

.. literalinclude:: ../backend/core/tasks/list_goals.py
   :start-after: ListGoals
   :end-before: console_output

Option values are available via ``self.get_options()``::

   # Did user pass in the --all CLI flag (or set it in .ini)?
   if self.get_options().all:

GroupTask
=========

Some ``Task``\s are grouped together under a parent ``GroupTask``.
Specifically, the JVM compile tasks::

    jvm_compile = GroupTask.named(
    'jvm-compilers',
    product_type=['classes_by_target', 'classes_by_source'],
    flag_namespace=['compile'])

    jvm_compile.add_member(ScalaCompile)
    jvm_compile.add_member(AptCompile)
    jvm_compile.add_member(JavaCompile)

A ``GroupTask`` allows its constituent tasks to 'claim' targets for processing, and can iterate
between those tasks until all work is done. This allows, e.g., Java code to depend on Scala code
which itself depends on some other Java code.

JVM Tool Bootstrapping
======================

If you want to integrate an existing JVM-based tool with a pants task, Pants
must be able to bootstrap it. That is, a running Pants will need to fetch
the tool and create a classpath with which to run it.

Your job as a task
developer is to set up the arguments passed to your tool (e.g.: source file names
to compile) and do something useful after the tool has run. For example, a code
generation tool would identify targets that own IDL sources, pass those sources
as arguments to the code generator, create targets of the correct type to own
generated sources, and mutate the targets graph rewriting dependencies on targets
owning IDL sources to point at targets that own the generated code.

.. comment TODO(https://github.com/pantsbuild/pants/issues/681)
   highlight useful snippets instead of saying "here's a link to the
   source and a list of things we hope you notice".

The `Scalastyle <http://www.scalastyle.org/>`_ tool enforces style policies
for scala code. The
`Pants Scalastyle task <https://github.com/pantsbuild/pants/blob/master/src/python/pants/backend/jvm/tasks/scalastyle.py>`_
shows some useful idioms for JVM tasks.

* Inherit ``NailgunTask`` to avoid starting up a new JVM.
* Specify the tool executable as a Pants ``jar``; Pants knows how to download
  and run those.
* Let organizations/users override the jar in ``pants.ini``; it makes it
  easy to use/test a new version.
