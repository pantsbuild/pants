##########################
Python Projects with Pants
##########################

Pants makes the manipulation and distribution of hermetically sealed Python
environments painless.
You can organize your code in the :doc:`Pants way <first_concepts>`,
with targets for binaries, libraries, and tests.
Pants builds Python code into
`PEXes <https://github.com/twitter/commons/blob/master/src/python/twitter/common/python/README.md>`_.
(A PEX is, roughly, an archive file containing a runnable Python environment.)
Pants isn't the only PEX-generation tool out there; but if you have some
"common code" used by more than one PEX, Pants makes it easy to manage
the dependencies.

This page assumes that you've already read :doc:`first_tutorial`.

Pants' Python support changed in 2014. Depending on how old your Pants is,
Pants goals might not work with Python code. If you use older pants,
please see :doc:`python_old`.

Pants' Python support is still changing. Depending on what you're trying to
do, your Pants command might start with ``goal`` or might start with something
else.

**************************
Relevant Goals and Targets
**************************

**Runnable Binary**

  Pants can generate PEXes, executables built from Python.
  Invoke the :ref:`binary goal <gref_phase_binary>`
  on a :ref:`python_binary <bdict_python_binary>`
  target to generate a ``.pex``. You can also invoke the
  :ref:`run goal <gref_phase_run>`
  on a ``python_binary`` to run its code "in place."

**Importable Code**

  :ref:`python_library <bdict_python_library>` BUILD targets make Python code
  "import-able".
  The rule of thumb is that each directory of ``.py`` files has a
  ``BUILD`` file with a ``python_library`` target. A Python target
  that has a ``python_library`` in its ``dependencies`` can import
  its code.

  To use code that's not in your workspace, use a
  :ref:`python_requirement_library <bdict_python_requirement_library>`
  and a :ref:`python_requirement <bdict_python_requirement>` to
  refer to the code.
  To use several several of these via a ``pip``-style
  ``requirements.txt`` file, use a
  :ref:`python_requirements <bdict_python_requirements>`.

**Tests**

  A :ref:`python_tests <bdict_python_tests>` BUILD target has some
  ``pytest`` tests. It normally
  depends on a ``python_library`` target so it can import and test
  the library's code. Use the :ref:`test goal <gref_phase_test>`
  to run these tests.

**Generated Code**

  A :ref:`python_thrift_library <bdict_python_thrift_library>`
  generates Python code from ``.thrift`` source;
  a Python target that has this target in its ``dependencies`` can ``import``
  the generated Python code.

*************************
BUILD for a Simple Binary
*************************

The pantsbuild/pants repo has a simple "hello world" sample Python binary.
You can use ``goal binary`` to build a PEX from it.
You can then run the PEX::

    $ ./pants goal binary src/python/example/hello/main
         ...much output...
    $ ./dist/main.pex # run the generated PEX
    Hello, world!
    $

``src/python/example/hello/main/BUILD`` defines a ``python_binary`` target,
a build-able thing that configures a runnable program made from Python code:

.. literalinclude:: ../../../python/example/hello/main/BUILD
   :start-after: Like Hello

This binary has a source file with its "main". A Python binary's "main" can be
in a depended-upon ``python_library`` or in the ``python_binary``\'s
``source``.

.. literalinclude:: ../../../python/example/hello/main/main.py
   :start-after: Apache License

This code imports code from another target.
To make this work, the binary target has a dependency
``src/python/example/hello/greet`` and the Python
code imports ``example/hello/greet``.

You remember that libraries configure "importable" code;
``example/hello/greet/BUILD`` has a ``python_library``:

.. literalinclude:: ../../../python/example/hello/greet/BUILD
   :start-after: Like Hello

This ``python_library`` pulls in ``greet.py``\'s Python code:

.. literalinclude:: ../../../python/example/hello/greet/greet.py
   :start-after: Apache

To test the library's code, we set up
``tests/python/example_test/hello/greet/BUILD`` with a ``python_tests``
target. It depends on the library:

.. literalinclude:: ../../../../tests/python/example_test/hello/greet/greet.py
   :start-after: Apache License

Use ``goal test`` to run the tests::

    $ ./pants goal test tests/python/example_test/hello/greet

    13:29:28 00:00 [main]
                   (To run a reporting server: ./pants goal server)
    13:29:28 00:00   [bootstrap]
    13:29:28 00:00   [setup]
    13:29:28 00:00     [parse]
       ...
    13:29:29 00:01   [test]
    13:29:29 00:01     [pytest]
    13:29:29 00:01       [run]
                         ============== test session starts ===============
                         platform darwin -- Python 2.6.8 -- py-1.4.20 -- pytest-2.5.2
                         plugins: cov, timeout
                         collected 1 items

                         tests/python/example_test/hello/greet/greet.py .

                         ============ 1 passed in 0.02 seconds ============

    13:30:18 00:50     [junit]
    13:30:18 00:50     [specs]
                   SUCCESS
    $


*******************************
Handling ``python_requirement``
*******************************

``BUILD`` files specify outside Python dependencies via
:ref:`python_requirement_library <bdict_python_requirement_library>`
targets wrapping
:ref:`python_requirement <bdict_python_requirement>`\s.

Pants handles these dependencies for you.
It never installs anything globally.
Instead, it builds the dependencies, caches them in `.pants.d`,
and assembles them *a la carte* into an execution environment.

************
PEX Contents
************

To build a PEX, invoke ``./pants goal binary`` on a ``python_binary`` target:

.. code-block:: bash

  $ ./pants goal binary src/python/example/hello/main
    ...
                   SUCCESS
  $ ./dist/main.pex
    Hello, world!

Though the binary itself specifies just one dependency, the transitive
closure of hello/main's dependencies pulled in
hello/greet and, in turn, hello/greet's dependencies.
Pants bundles up the closed set of all dependencies into
into the PEX.

*************************************************
REPL and environment manipulation with `pants py`
*************************************************

Pants has a "py" command that lets you manipulate the environments
described by `python_binary` and `python_library` targets, such as drop into
an interpreter with the environment set up for you.
Note that's "py", **not** "goal py".

``pants py <target>``...

1. For a ``python_binary`` target, builds the environment and executes the
   target.
2. For `python_library` targets, builds the environment that is the transitive
   closure of all targets and drops into an interpreter.
3. For a combination of `python_binary` and `python_library` targets, builds
   the transitive closure of all targets and executes the first binary target.

Let's drop into our library target ``src/python/example/hello/greet``
with verbosity turn on to see what's going on in the background::

    $ PANTS_VERBOSE=1 ./pants py src/python/example/hello/greet
    /Users/lhosken/workspace/pants src/python/example/hello/greet
    Building chroot for [PythonLibrary(BuildFileAddress(/Users/lhosken/workspace/pants/src/python/example/hello/greet/BUILD, greet))]:
      Dumping library: PythonLibrary(BuildFileAddress(/Users/lhosken/workspace/pants/src/python/example/hello/greet/BUILD, greet))
      Dumping requirement: ansicolors==1.0.2
      Dumping distribution: .../ansicolors-1.0.2-py2-none-any.whl
    Python 2.6.8 (unknown, Mar  9 2014, 22:16:00)
    [GCC 4.2.1 Compatible Apple LLVM 5.0 (clang-500.0.68)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>>

Pants loads ``ansicolors`` (greet's 3rdparty dependency). It would have fetched
this dependency over the network if necessary. (It wasn't necessary to download
``ansicolors``; Pants already fetched it while "bootstrapping" itself.)

You can convince yourself that the environment contains all the dependencies
by inspecting `sys.path` and importing libraries as you desire::

  >>> from example.hello.greet.greet import greet
  >>> greet("escape codes")
  u'\x1b[32mHello, escape codes!\x1b[0m'
  >>> from colors import red
  >>> red("other escape codes")
  '\x1b[31mother escape codes\x1b[0m'

**Dependencies built by Pants are never installed globally**.
These dependencies only exist for the duration of the Python
interpreter forked by Pants.

``pants py --pex``
==================

You can use ``./pants py --pex`` to build a PEX
file from ``python_library`` targets with no
`python_binary` target.  Since there is no entry point
specified, the resulting ``.pex`` file just behaves like a Python interpreter,
but with the sys.path bootstrapped for you::

    $ ./pants py --pex src/python/example/hello/greet
    /Users/lhosken/workspace/pants src/python/example/hello/greet
    Wrote /Users/lhosken/workspace/pants/dist/src.python.example.hello.greet.greet.pex
    $

If you run ``dist/src.python.example.hello.greet.greet.pex``, since it has
no entry point, it drops you into an interpreter::

    $ ./dist/src.python.example.hello.greet.greet.pex
    Python 2.6.8 (unknown, Mar  9 2014, 22:16:00)
    [GCC 4.2.1 Compatible Apple LLVM 5.0 (clang-500.0.68)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>> from example.hello.greet.greet import greet
    >>> greet("pex")
    u'\x1b[32mHello, pex!\x1b[0m'
    >>>

It's like a single-file lightweight alternative to a virtualenv.
We can even use it to run our `main.py` application::

    $ dist/src.python.example.hello.greet.greet.pex src/python/example/hello/main/main.py
    Hello, world!
    $

This can be an incredibly powerful and lightweight way to manage and deploy
virtual environments without using `virtualenv`.

*************************
python_binary entry_point
*************************

An advanced feature of `python_binary` targets, you may in addition specify
direct entry points into PEX files rather than a source file.  For example,
if we wanted to build an a la carte `fab` wrapper for fabric::

  python_binary(name = "fab",
    entry_point = "fabric.main:main",
    dependencies = [
      pants("3rdparty/python:fabric"),
    ]
  )


We build:

.. code-block:: bash

  $ ./pants src/python/fabwrap:fab
  Build operating on targets: OrderedSet([PythonBinary(src/python/fabwrap/BUILD:fab)])
  Building PythonBinary PythonBinary(src/python/fabwrap/BUILD:fab):
  Wrote /private/tmp/wickman-pants/dist/fab.pex

And now `dist/fab.pex` behaves like a standalone `fab` binary:

.. code-block:: bash

  $ dist/fab.pex -h
  Usage: fab [options] <command>[:arg1,arg2=val2,host=foo,hosts='h1;h2',...] ...

  Options:
    -h, --help            show this help message and exit
    -d NAME, --display=NAME
                          print detailed info about command NAME
    -F FORMAT, --list-format=FORMAT
                          formats --list, choices: short, normal, nested
    -l, --list            print list of possible commands and exit
    --set=KEY=VALUE,...   comma separated KEY=VALUE pairs to set Fab env vars
    --shortlist           alias for -F short --list
    -V, --version         show program's version number and exit
    -a, --no_agent        don't use the running SSH agent
    -A, --forward-agent   forward local agent to remote end
    --abort-on-prompts    abort instead of prompting (for password, host, etc)
    ...

***********************
More About Python Tests
***********************

Pants runs Python tests with ``pytest``. You can pass CLI options to ``pytest``
with ``--test-pytest-options``. For example, to only run tests whose names
match the pattern \*foo\*, you could run ::

    $ ./pants goal test tests/python/example_test/hello/greet --test-pytest-options='-k foo'
    ...
                     ============== test session starts ===============
                     platform darwin -- Python 2.6.8 -- py-1.4.20 -- pytest-2.5.2
                     plugins: cov, timeout
                     collected 1 items

                     ========= 1 tests deselected by '-kfoo' ==========
                     ========== 1 deselected in 0.01 seconds ==========

    13:34:28 00:02     [junit]
    13:34:28 00:02     [specs]
               SUCCESS


Code Coverage
=============

.. for me,
   PANTS_PY_COVERAGE=1 ./pants tests/python/example_test/hello/greet
   horks up
   Coverage.py warning: Module example_test.hello.greet was never imported.
   Coverage.py warning: No data was collected.
   ...
   (crash dump with CoverageException: No data to report.)
   https://github.com/pantsbuild/pants/issues/328

To get code coverage data, set the `PANTS_PY_COVERAGE` environment variable::

    $ PANTS_PY_COVERAGE=1  ./pants tests/python/example_test/hello/greet:greet

Interactive Debugging on Test Failure
=====================================

You can invoke the Python debugger on a test failure by
leaving out the ``goal test`` and passing ``--pdb``.
This can be useful for
inspecting the state of objects especially if you are mocking interfaces.

Other Testing Frameworks
========================

.. https://github.com/pantsbuild/pants/issues/276 TODO Did this go away?

Although most tests can run under `pytest`, if you need to use a different testing framework, you
can. Set the `entry_point` keyword argument when calling python_tests::

  python_tests(
    name = 'tests',
    sources = [],
    dependencies = [
      pants('src/python/twitter/infraops/supplybird:supplybird-lib'),
      pants('3rdparty/python:mock')
    ],
    entry_point="twitter.infraops.supplybird.core.run_tests"
  )

The `entry_point` exits with a non-zero status if there are test failures.

Keep in mind, however, that much of the above documentation assumes you are using `pytest`.

****************************************************
Manipulating PEX behavior with environment variables
****************************************************

You can alter a PEX file's behavior during invocation
by setting some environment variables.

PEX_INTERPRETER=1
=================

If you have a PEX file with a prescribed executable source or ``entry_point``,
you can still drop into an interpreter with the environment bootstrapped.
Set `PEX_INTERPRETER=1` in your environment, and the PEX bootstrapper
skips any execution and instead launches an interactive interpreter session.

PEX_VERBOSE=1
=============

If your environment is failing to bootstrap or simply bootstrapping very slowly, it can be useful to
set `PEX_VERBOSE=1` in your environment to get debugging output printed to the console.  Debugging output
includes:

1. Fetched dependencies
2. Built dependencies
3. Activated dependencies
4. Packages scrubbed out of `sys.path`
5. The `sys.path` used to launch the interpreter

PEX_MODULE=entry_point
======================

If you have a PEX file without a prescribed entry point, or want to change
the ``entry_point`` for a single invocation, you can set
``PEX_MODULE=entry_point`` using the same format as described in the
:ref:`python_binary <bdict_python_binary>` Pants target.

This can be useful for bundling up some packages together and
using that single file to execute scripts from each of them.

Another common pattern is to link `pytest` into your PEX file, and run
``PEX_MODULE=pytest my_pex.pex tests/*.py`` to run your test suite in its
isolated environment.

PEX_COVERAGE
============

There is nascent support for performing code coverage within PEX files by
setting `PEX_COVERAGE=<suffix>`.  By default the coverage files will be written
into the current working directory with the file pattern `.coverage.<suffix>`.  This
requires that the `coverage` Python module has been linked into your PEX.

You can then combine the coverage files by running `PEX_MODULE=coverage
my_pex.pex .coverage.suffix*` and run a report using `PEX_MODULE=coverage
my_pex.pex report`.  Since PEX files are just zip files, `coverage` is able
to understand and extract source and line numbers from them in order to
produce coverage reports.


.. TODO: converting python_library targets to eggs

.. TODO: auto dependency resolution from within PEX files

.. TODO: dynamically self-updating PEX files

.. TODO: tailoring your dependency resolution environment with pants.ini,
   including local cheeseshop mirrors 

.. toctree::
   :maxdepth: 1

   pex_design
   python_old
