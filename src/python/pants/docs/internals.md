Pants Internals
===============

Pants is a build tool. This document describes some of its internals,
concentrating on how to tailor Pants to your needs, such as integrating
it with other tools.

If you want to run Pants or to write BUILD files, you probably want the
[[Pants Conceptual Overview|pants('src/docs:first_concepts')]] instead.
But if you want to support a new tool or a new language, read on.

How Some Base Classes Interrelate
---------------------------------

**Target**<br>
An addressable thing, such as a `python_binary` or `junit_tests`. To add
support for a new language, you probably want to add new target types to
represent things you can build with that language. Most Target instances
can depend on other Target instances. As a rule of thumb, if code in
Target \_A\_ imports code in Target *B*, then *A* depends on *B*. If *A*
depends on *B*, then when carrying out some goal on *A*, you can be sure
that goal has been carried out on *B*.
<!-- TODO: if there are one or more exemplary Target classes, link to them. -->

**Goal**<br>
A build verb, such as compile or test. Internally, a goal is implemented
as a set of Tasks.

**Task**<br>
A Goal has one or more Tasks, which do the actual work of invoking
tools. A compile Goal, for example, could contain a Task for Java
compilation, a Task for Scala compilation, etc. If you want an existing
Goal to do something new (e.g., compile FooLang), instead of cramming
your code into an existing Task, you probably want to define a new Task
and install it in the existing Goal. A Task looks at the environment and
Targets, invokes some tool, generates things, and reports
success/failure. If you're giving Pants the ability to do something new,
you're probably adding a Task. See
[[Developing a Pants Task|pants('src/python/pants/docs:dev_tasks')]].

**Plugin (or "Backend")**<br>
Collection of Targets, Goals, Tasks, Commands to do something useful. At
Pants' core are the abstractions Target, and Task. These abstractions
don't do anything in particular. To build real code, you need to define
and register some more specific classes. For example, to build Java
code, you want the `JavaLibrary` Target, `ZincCompile` task (registered
in the `compile` goal), and many more. We organize this "real" code into
"plugins". A typical plugin defines several classes and registers them
with the Pants core. For a design discussion on registering plugins, see
the [Plugin
Engine](https://groups.google.com/forum/#!topic/pants-devel/uHGpR2K6FBI)
`pants-devel` thread.

**Context**<br>
An API to the state of the world. A Task uses this to find out things
like the flags the user set on the command line, pants.ini config, and
the state of the build cache. The task uses context.products to
communicate results and requests for build results.

Examining a Goal-Task Chain
---------------------------

It's not so easy to figure out in your head which Goals+Tasks are invoked for some command line.
The dependency relationships between Goals and Tasks gets complex. The `--explain` global flag
helps here. Instead of building something, it echoes a summary of the goals and tasks it
*would* use to build something. For example, you can find out what happens on a `compile`:

    :::bash
    $./pants --explain compile
    Goal Execution Order:

    bootstrap -> imports -> gen -> resolve -> compile

    Goal [TaskRegistrar->Task] Order:

    bootstrap [bootstrap-jvm-tools->BootstrapJvmTools]
    imports [ivy-imports->IvyImports]
    gen [thrift->ApacheThriftGen, scrooge->ScroogeGen, protoc->ProtobufGen, antlr->AntlrGen, ragel->RagelGen, jaxb->JaxbGen, aapt->AaptGen]
    resolve [ivy->IvyResolve]
    compile [jvm->SingletonGroupTask]
    $

This tells you that the resolve goal comes before the compile goal, the
gen goal comes before that, etc. There is more than one Task registered
for the gen goal. In the gen [thrift-\>ApacheThriftGen,... text, thrift
is the name of a task and ApacheThriftGen is the name of the class that
implements it.

Defining a Task
---------------

Defining a new Task tells Pants of some new action it can take. This
might be a new goal or adding new functionality in an existing goal
(e.g., telling the "gen" code-generation goal about some new way to
generate code). See [[Developing a Pants Task|pants('src/python/pants/docs:dev_tasks')]].
