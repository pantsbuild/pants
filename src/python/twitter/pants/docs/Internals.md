Pants is a build tool. This document describes some of its internals,
concentrating on how to tailor Pants to your needs, such as integrating it with
other tools.
If you want to run Pants or to write BUILD files, you probably want the
[[main Pants doc|pants('src/python/twitter/pants:readme')]] instead.
But if you want to support a new tool or a new language, read on.

# How Some Base Classes Interrelate

**`Target`**: An addressable thing, such as a `python_binary` or `scala_test`.
To add support for a new language, you probably want to add new target types
to represent things you can build with that language. Most Target instances can
depend on other Target instances. As a rule of thumb, if code in Target _A_
imports code in Target _B_, then _A_ depends on _B_. If _A_
depends on _B_, then when carrying out some goal on _A_, you can be sure that
goal has been carried out on _B_.

TODO if there are one or more exemplary Target classes, link to them.

**"goal" a.k.a. `Phase`**: From the users' point of view, when they invoke
`pants test binary src/python/mach_turtle` the "goals" are `test` and `binary`,
the actions requested. Internally, these are implemented in terms of
Goals and Phases. Confusingly (and hopefully to be changed), the things that
the user calls "goals" are actually Phases. A Phase has one or more Goals:

**`Goal`**: The glue that binds Phases and Tasks together. A Phase has one or
more Goals. A Goal has a Task, which does the actual work of invoking tools.
A `compile` Phase, for example, could contain a Goal for Python
compilation, a Goal for Java compilation, etc.; each of those Goals has
one Task. If you want an existing Phase to do something new, instead of
cramming your code into an existing Goal, you probably want to define a new
Goal and `install` it in the existing Phase. A Goal can depend on Phases,
expressing that Pants should carry out those Phases before carrying out the
Goal. For example, the java-test Goal depends on the `compile` Phase because
testing uncompiled code is hard.

**`Task`**: The thing that does the actual work for some Goal. It looks
at the environment and Targets, invokes some tool, generates things, and reports
success/failure. It can define command-line flags to check.

TODO if there are one or more exemplary Task classes, link to them.

**`Context`**: An API to the state of the world. A Task uses this to find out
things like the flags the user set on the command line, `pants.ini` config,
and the state of the build cache. The task uses `context.products` to
communicate results and requests for build results.

# Examining a Phase-Goal-Task Chain

It's not so easy to figure out in your head which Goals+Tasks are invoked for
some command line command.
The dependency relationships between Phases, Goals, and Tasks can get complex.
The `--explain` flag helps here. Instead of building something,
it echoes a summary of the phases, goals, and tasks it would use to
build something. For example, you can find out what happens on a `compile`:

    $ <b>./pants goal compile --explain</b>
    Phase Execution Order:
    
    resolve-idl -> thriftstore-codegen -> gen -> resolve -> compile
    
    Phase [Goal->Task] Order:
    
    resolve-idl [idl->IdlResolve, extract->Extract]
    thriftstore-codegen [thriftstore-codegen->ThriftstoreCodeGen]
    gen [thrift->ThriftGen, scrooge->ScroogeGen, protoc->ProtobufGen, antlr->AntlrGen
    resolve [ivy->IvyResolve]
    compile [checkstyle->Checkstyle]
    $

This tells you that the `resolve` phase comes before the `compile` phase, the
`gen` phase comes before that, etc. There is more than one Goal registered for
the `gen` phase. In the `gen [thrift->ThriftGen,...` text, `thrift` is
the name of a Goal and `ThriftGen` is the name of its Task class.

# Where to put a new Goal

TODO: this

# Code Layout

[./](https://github.com/twitter/commons/tree/master/src/python/twitter/pants/base/)
: Top-level directory  
  **`__init__.py`** Among other things, defines the symbols
  visible in `BUILD` files. If you add a
  Target type, this file should import it.  
  **`BUILD`** Dogfood and/or recursion.  
  **`*.md`** Docs too important for `docs/`.

[base](https://github.com/twitter/commons/tree/master/src/python/twitter/pants/base/)
: Defines `Target` and TODO

[bin](https://github.com/twitter/commons/tree/master/src/python/twitter/pants/bin/)
: The "main" of Pants itself lives here.

[commands](https://github.com/twitter/commons/tree/master/src/python/twitter/pants/commands/)
: Before we had goals we had commands, and they lived here.  
  **`goal.py`** Many Goals and Phases are defined here.

[docs](https://github.com/twitter/commons/tree/master/src/python/twitter/pants/docs/)
: Documentation. The source of this very document you're reading now lives here.

[goal](https://github.com/twitter/commons/tree/master/src/python/twitter/pants/goal/)
: The source of `Context`, `Goal`, and `Phase` (some
  important classes) lives here. If you extend pants to work with other
  tools/languages, hopefully you won't need to edit these; but you'll
  probably look at them to see the flow of control.

[java](https://github.com/twitter/commons/tree/master/src/python/twitter/pants/java/)
: (TODO OMG bluffing) Utility classes useful to many things that work
  with Java code.

[python](https://github.com/twitter/commons/tree/master/src/python/twitter/pants/python/)
: (TODO OMG bluffing) Utility classes useful to many things that work
  with Python code.

[targets](https://github.com/twitter/commons/tree/master/src/python/twitter/pants/targets/)
: Source of the Target classes; e.g., the code behind `jvm_binary`
  lives here. If you define a new Target type, add its code here.

[tasks](https://github.com/twitter/commons/tree/master/src/python/twitter/pants/tasks/)
: Source of the Task classes. E.g., `junit_run`, the code that
  invokes JUnit if someone tests a `java_tests` target.

# .pants.d/

TODO: this.

# BUILD file parsing

TODO: this.

# ivy resolution

TODO: this.

# hashing

TODO: this.

# task batching

TODO: this.

# product mapping

TODO: this.
