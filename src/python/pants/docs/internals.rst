###############
Pants Internals
###############

Pants is a build tool. This document describes some of its internals,
concentrating on how to tailor Pants to your needs, such as integrating it with
other tools.

If you want to run Pants or to write BUILD files, you probably want
the :doc:`first_concepts` instead.  But if you want to support a new tool or a
new language, read on.

*********************************
How Some Base Classes Interrelate
*********************************

**Target**
    An addressable thing, such as a :mod:`python_binary` or :mod:`scala_tests`.
    To add support for a new language, you probably want to add new target types
    to represent things you can build with that language. Most Target instances can
    depend on other Target instances. As a rule of thumb, if code in Target _A_
    imports code in Target *B*, then *A* depends on *B*. If *A*
    depends on *B*, then when carrying out some goal on *A*, you can be sure that
    goal has been carried out on *B*.

    TODO: if there are one or more exemplary Target classes, link to them.

**Goal**
    A build verb, such as `compile` or `test`.
    Internally, a goal is implemented as a set of Tasks.

**Task**
    A Goal has one or more Tasks, which do the actual work of invoking tools.
    A `compile` Goal, for example, could contain a Task for Java
    compilation, a Task for Scala compilation, etc. If you want an existing Goal
    to do something new (e.g., compile FooLang), instead of cramming your code
    into an existing Task, you probably want to define a new Task and `install`
    it in the existing Goal.
    A Task looks at the environment and Targets, invokes some tool, generates
    things, and reports success/failure.
    If you're giving Pants the ability to do something new, you're probably
    adding a Task. See :doc:`dev_tasks`.

**Plugin (or "Backend")**
    Collection of Targets, Goals, Tasks, Commands to do something useful.
    At Pants' core are the abstractions Target, and Task.
    These abstractions don't do anything in particular.
    To build real code, you need to define and register some more specific
    classes.
    For example, to build Java code, you want the ``JavaLibrary`` Target,
    ``JavaCompile`` task (registered in the ``compile`` goal), and many more.
    We organize this "real" code into "plugins". A typical plugin defines
    several classes and registers them with the Pants core.
    For a design discussion on registering plugins, see the
    `Plugin Engine
    <https://groups.google.com/forum/#!topic/pants-devel/uHGpR2K6FBI>`_
    ``pants-devel`` thread.


**Context**
    An API to the state of the world. A Task uses this to find out
    things like the flags the user set on the command line, `pants.ini` config,
    and the state of the build cache. The task uses `context.products` to
    communicate results and requests for build results.

***************************
Examining a Goal-Task Chain
***************************

It's not so easy to figure out in your head which Goals+Tasks are invoked for
some command line.  The dependency relationships between Goals and Tasks can
get complex.  The `--explain` flag helps here. Instead of building something,
it echoes a summary of the goals and tasks it would use to build something.
For example, you can find out what happens on a `compile`::

    $./pants goal compile --explain
    Goal Execution Order:

    bootstrap -> imports -> gen -> check-exclusives -> resolve -> compile

    Goal [TaskRegistrar->Task] Order:

    bootstrap [bootstrap-jvm-tools->BootstrapJvmTools]
    imports [ivy-imports->IvyImports]
    gen [thrift->ApacheThriftGen, scrooge->ScroogeGen, protoc->ProtobufGen, antlr->AntlrGen, ragel->RagelGen, jaxb->JaxbGen, aapt->AaptGen]
    check-exclusives [check-exclusives->CheckExclusives]
    resolve [ivy->IvyResolve]
    compile [jvm->SingletonGroupTask]
    $

This tells you that the `resolve` goal comes before the `compile` goal, the
`gen` goal comes before that, etc. There is more than one Task registered for
the `gen` goal. In the `gen [thrift->ApacheThriftGen,...` text, `thrift` is the
name of a task and `ApacheThriftGen` is the name of the class that implements it.

***************
Defining a Task
***************

Defining a new Task tells Pants of some new action it can take. This might
be a new goal or adding new functionality in an existing goal (e.g., telling
the "gen" code-generation goal about some new way to generate code).
See :doc:`dev_tasks`.

***********
Code Layout
***********

`./ <https://github.com/pantsbuild/pants/tree/master/src/python/pants/base/>`_
  Top-level directory  
  **`__init__.py`** Among other things, defines the symbols
  visible in `BUILD` files. If you add a
  Target type, this file should import it.  
  **`BUILD`** Dogfood and/or recursion.  
  **`*.md`** Docs too important for `docs/`.

`base <https://github.com/pantsbuild/pants/tree/master/src/python/pants/base/>`_
  Defines `Target` and other fundamental pieces/base classes.
  As a rule of thumb, code in ``base`` shouldn't ``import`` anything in
  non-base Pants; but many things in non-base Pants ``import`` from ``base``.
  If you're editing code in ``base`` and find yourself referring to
  the JVM (or other target-language-specific things), you're probably editing
  the wrong thing and want to look further up the inheritance tree.

`bin <https://github.com/pantsbuild/pants/tree/master/src/python/pants/bin/>`_
  The "main" of Pants itself lives here.

`commands <https://github.com/pantsbuild/pants/tree/master/src/python/pants/commands/>`_
  Before we had goals we had commands, and they lived here.  
  **goal.py** Many Goals and Tasks are defined here.

`docs <https://github.com/pantsbuild/pants/tree/master/src/python/pants/docs/>`_
  Documentation. The source of this very document you're reading now lives here.

`goal <https://github.com/pantsbuild/pants/tree/master/src/python/pants/goal/>`_
  The source of `Context` and `Goal` (some important classes) lives here.
  If you extend pants to work with other tools/languages, hopefully you won't need to
  edit these; but you'll probably look at them to see the flow of control.

`java <https://github.com/pantsbuild/pants/tree/master/src/python/pants/java/>`_
  (TODO OMG bluffing) Utility classes useful to many things that work
  with Java code.

`python <https://github.com/pantsbuild/pants/tree/master/src/python/pants/backend/python/>`_
  (TODO OMG bluffing) Utility classes useful to many things that work
  with Python code.

`targets <https://github.com/pantsbuild/pants/tree/master/src/python/pants/targets/>`_
  Source of the Target classes; e.g., the code behind `jvm_binary`
  lives here. If you define a new Target type, add its code here.

`tasks <https://github.com/pantsbuild/pants/tree/master/src/python/pants/backend/core/tasks/>`_
  Source of the Task classes. E.g., `junit_run`, the code that
  invokes JUnit if someone tests a `java_tests` target.

`tests/.../pants <https://github.com/pantsbuild/pants/tree/master/tests/python/pants_test/>`_
  Tests for Pants. These tend to be ``python_tests`` exercising Pants functions.
  ``pants_test.base_build_root_test.BaseBuildRootTest`` is a very handy
  class; it has methods to set up and tear down little source trees with
  ``BUILD`` files.

.. *********
   .pants.d/
   *********
   
   TODO: this.

.. ******************
   BUILD file parsing
   ******************
   
   TODO: this.

.. **************
   ivy resolution
   **************
   
   TODO: this.

.. *******
   hashing
   *******
   
   TODO: this.

.. *************
   task batching
   *************
   
   TODO: this.

.. ***************
   product mapping
   ***************
   
   TODO: this.
