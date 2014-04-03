##############
First Tutorial
##############

This tutorial walks you through some first steps with Pants build: invoking
commands, looking at the files that define build-able things. It assumes
you're already familiar with
:doc:`basic Pants build concepts <first_concepts>`.
It assumes you're working in a source tree that already has ``pants``
installed (such as Pants's own repo:
`pantsbuild/pants <https://github.com/pantsbuild/pants>`_).

The first time you run ``pants``, try it without arguments. This makes
Pants "bootstrap" itself, downloading and compiling things it needs::

    ./pants

Now you're ready to invoke pants for more useful things.

You invoke pants with *goals* (like ``test`` or ``bundle``) and the
*build targets* to use (like
``tests/java/com/pants/examples/pingpong/BUILD:pingpong``). For example, ::

    ./pants goal test tests/java/com/pants/examples/pingpong/BUILD:pingpong

Goals (the "verbs" of Pants) produce new files from Targets (the "nouns").

As a code author, you define your code's `build targets` in BUILD files.
A build target might produce some output file[s];
it might have sources and/or depend on other build targets.
There might be several BUILD files in the codebase; a target in
one can depend on a target in another. Typically, a directory's BUILD
file defines the target[s] whose sources are files in that directory.

**************
Invoking Pants
**************

Pants knows about goals ("verbs" like ``bundle`` and ``test``) and targets
(build-able things in your source code). A typical pants command-line
invocation looks like ::

    $ ./pants goal test tests/java/com/pants/examples/pingpong/BUILD:pingpong

Looking at the pieces of this we see

``./pants``
    That ``./`` isn't a typo. A source tree that's been set up with Pants build
    has a ``pants`` executable in its top-level directory.

    The first time you run ``./pants``, it might take a while: it will probably
    auto-update by downloading the latest version.

``goal``
    Magic word that you use on most Pants command lines.
    We hope that someday we won't need to use this magic word anymore.
    As a rule of thumb, if you work with JVM code, you need ``goal``;
    if you work with Python code, you leave it out.

``test``
    ``test`` is a *goal*, a "verb" that Pants knows about. The ``test`` goal runs tests
    and reports results.
    (When working with Python code, you don't normally specify a goal on the
    command line. Instead
    Pants "figures out" what to do based on the targets. E.g., it runs tests on test
    targets.)

    Some goals are ``gen`` (generate code from Thrift, Antlr, Protocol Buffer),
    ``compile``, and ``eclipse`` (generate an Eclipse project).
    Pants knows that some of these goals depend on each other. E.g., in this example,
    before it run tests, it must compile the code.

    You can specify more than one goal on a command line. E.g., to generate an
    Eclipse project *and* run tests, we could have said ``eclipse tests``.

``tests/java/com/pants/examples/pingpong/BUILD:pingpong``
    This is a *build target*, a "build-able" thing in your source code. To define
    these, you set up configuration files named ``BUILD`` in your source code file
    tree. (You'll see more about these later.)

    Targets can depend on other targets. E.g., a test suite target normally depends
    on another target containing the "library" code to test; to build the test code,
    Pants also must build the library code.

    You can specify more than one target on a command line. Pants will carry out
    its goals on all specified targets. E.g., you might use this to generate an Eclipse
    project based on Pingpong's source and tests.

Output
======

Pants produces files, both build outputs and intermediate files generated
"along the way". These files live in directories under the top-level directory:

``dist/``
    By default, build outputs go in the ``dist/`` directory. So far, you've
    just run the ``test`` goal, which doesn't output a file. But if you'd
    instead invoked, for example, the ``bundle`` goal on a ``jvm_binary``
    target, Pants would have populated this directory with many JVM ``.jar``
    files.

``.pants.d/``
    Intermediate files go in the ``.pants.d/`` directory. You don't want
    to rely on files in there; if the Pants implementation changes, it's
    likely to change how it uses intermediate files. You don't want to
    edit/delete files in there; you may confuse Pants. But if you want to
    peek at some generated code, the code is probably in here somewhere.

Multiple Goals, Multiple Targets
================================

You can specify multiple goals and multiple targets. Pants applies all the goals to
all the targets, skipping things that wouldn't make sense. E.g., you could

* Invoke ``eclipse`` and ``test`` goals to both generate an Eclipse project and run tests.
* Specify both test-suite and "library" targets so Eclipse sees all the source code.

In this example, it doesn't make sense to run library code as a test, so Pants doesn't do
that. Since pants knows that the ``test`` goal depends on the ``compile`` goal, it
*does* compile the library.

One tricky side effect of this:
You can invoke a goal that doesn't make sense for a target. E.g., you can invoke
the ``test`` goal on a target that's not a test suite. Pants won't complain.
It knows that it should compile code before it tests it; it will happily compile
the build targets. If you're not watching closely, you might see a lot of output
scrolling past and think it was running tests.

Help
====

To get help about a Pants goal, invoke ``./pants goal help`` *goalname*. This lists
the many command-line options you can pass for that goal. E.g., ::

    $ ./pants goal help test
    Usage: ./pants.pex goal test ([target]...)
    
    Options:
      -h, --help            show this help message and exit
      -t CONN_TIMEOUT, --timeout=CONN_TIMEOUT
                            Number of seconds to wait for http connections.
    ...
        --test-specs-color, --no-test-specs-color
                            [True] Emit test result with ANSI terminal color
                            codes.
    
    Test compiled code.

For a list of available goals, ``./pants goal goals``.

For help with things that aren't goals (Most Python operations aren't goals), use ::

    ./pants help

If you want help diagnosing some strange Pants behavior, you might verbose output.
To get this, instead of just invoking ``./pants``, set some environment variables:
``PEX_VERBOSE=1 PANTS_VERBOSE=1 PYTHON_VERBOSE=1 ./pants``.

***********
BUILD Files
***********

We told pants what target to build, but where are these defined? Scattered
around the source tree are ``BUILD`` files. These ``BUILD`` files define
targets. For example, this code snippet of
``java/com/twitter/common/examples/pingpong/main/BUILD`` defines the binary
program we compiled and ran.  This target is named ``main`` and
is of type ``jvm_binary``:

.. literalinclude:: ../../../../java/com/pants/examples/pingpong/main/BUILD
   :start-after: under the License.

That ``dependencies`` is interesting. This build target depends on
other build targets; the ``dependencies`` lists those other targets.
To build a runnable Java binary, we need to first compile its dependencies.

The ``main`` binary has one dependency,
``pants('src/java/com/pants/examples/pingpong/handler')``.
That src/.../handler is the *address* of another target. Addresses look,
roughly, like ``path/to/BUILD:targetname``.
We can see this build target in the ``.../pingpong/handler/BUILD`` file:

.. literalinclude:: ../../../../java/com/pants/examples/pingpong/handler/BUILD
   :start-after: java_library:

Pants uses dependency information to figure out how to build your code.
You might find it useful for other purposes, too. For example, if you change
a library's code, you might want to know which test targets depend on that
library: you might want to run those tests to make sure they still work.

Anatomy of a ``BUILD`` Target
=============================

A target definition in a ``BUILD`` file looks something like ::

    scala_library(
      name='util',
      dependencies = [pants('3rdparty:commons-math'),
                      pants('3rdparty:thrift'),
                      pants('src/main/scala/com/foursquare/auth'),
                      pants(':base')],
      sources=globs('*.scala'),
    )

Here, ``scala_library`` is the target's *type*. Different target types support
different arguments. The following arguments are pretty common:

**name**
  We use a target's name to refer to the target. This argument isn't just
  "pretty common," it's required. You use names on the
  command line to specify which targets to operate on. You also use names
  in ``BUILD`` files when one target refers to another, e.g. in
  ``dependencies``:
**dependencies**
  List of things this target depends upon. If this target's code imports code
  that "lives" in other targets, list those targets here. If this
  target imports code that "lives" in ``.jar``\s/``.egg``\s from elsewhere,
  refer to them here.
**sources**
  List of source files. The `globs` function is handy here.

******************
The Usual Commands
******************

**Make sure code compiles and tests pass:**
  Use the ``test`` goal with the targets you're interested in. If they are
  test targets, Pants runs the tests. If they aren't test targets, Pants will
  still compile them since it knows it must compile before it can test.

  ``pants goal test src/java/com/myorg/myproject tests/java/com/myorg/myproject``

**Get Help**
  Get the list of goals::

    ./pants goal goals

  Get help for one goal::

    ./pants goal help onegoal

****
Next
****

To learn more about working with Python projects, see :doc:`python-readme`.

To learn more about working with Java projects, see :doc:`JVMProjects`
