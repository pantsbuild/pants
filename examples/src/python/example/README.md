Python Projects with Pants
==========================

Pants makes the manipulation and distribution of hermetically sealed
Python environments painless. You can organize your code in the
[[Pants way|pants('src/docs:first_concepts')]]
with targets for binaries, libraries, and
tests. Pants builds Python code into
[PEXes](https://github.com/pantsbuild/pex/blob/master/docs/whatispex.rst).
(A PEX is, roughly, an archive file containing a runnable Python
environment.) Pants isn't the only PEX-generation tool out there; but if
you have some "common code" used by more than one PEX, Pants makes it
easy to manage the dependencies.

This page assumes that you've already read
[[the Pants Tutorial|pants('src/docs:first_tutorial')]].

Relevant Goals and Targets
--------------------------

**Runnable Binary**

> Pants can generate PEXes, executables built from Python. Invoke the
> <a pantsref="oref_goal_binary">`binary`</a> goal on a
> <a pantsref="bdict_python_binary">`python_binary`</a> target to generate a `.pex`.
> You can also invoke the
> <a pantsref="oref_goal_run">`run`</a> goal on a
> `python_binary` to run its code "in place."

**Importable Code**

> <a pantsref="bdict_python_library">`python_library`</a> BUILD targets make Python
> code "import-able". The rule of thumb is that each directory of `.py`
> files has a `BUILD` file with a `python_library` target. A Python
> target that has a `python_library` in its `dependencies` can import
> its code.
>
> To use code that's not in your workspace, use a
> <a pantsref="bdict_python_requirement_library">`python_requirement_library`</a>
> and a
> <a pantsref="bdict_python_requirement">`python_requirement`</a> to refer to
> the code. To use several several of these via a `pip`-style
> `requirements.txt` file, use a
> <a pantsref="bdict_python_requirements">`python_requirements`</a>.
> For details, see [[Python 3rdparty Pattern|pants('examples/src/python/example:3rdparty_py')]].

**Tests**

> A <a pantsref="bdict_python_tests">`python_tests`</a> BUILD target has some `pytest` tests.
> It normally depends on a `python_library` target so it can import and test the library's code.
> Use the <a pantsref="oref_goal_test">`test`</a> goal to run these tests.

**Generated Code**

> A <a pantsref="bdict_python_thrift_library">`python_thrift_library`</a> generates
> Python code from `.thrift` source; a Python target that has this
> target in its `dependencies` can `import` the generated Python code.

BUILD for a Simple Binary
-------------------------

The pantsbuild/pants repo has a simple "hello world" sample Python
binary. You can use `binary` to build a PEX from it. You can then
run the PEX:

    :::bash
    $ ./pants binary examples/src/python/example/hello/main
         ...much output...
    $ ./dist/main.pex # run the generated PEX
    Hello, world!
    $ ./dist/main.pex Whirled
    Hello, Whirled!
    $

You can also run the binary "from source" with the `run` goal:

    :::bash
    $ ./pants run.py --args='Whirled' examples/src/python/example/hello/main
         ...much output...
    14:32:01 00:00     [py]
    14:32:02 00:01       [run]
    Hello, Whirled!

    14:32:02 00:01     [jvm]
                   SUCCESS
    $

[`examples/src/python/example/hello/main/BUILD`](https://github.com/pantsbuild/pants/blob/master/examples/src/python/example/hello/main/BUILD)
defines a `python_binary` target, a build-able thing that defines a runnable program made from
Python code:

!inc[start-at=python_binary](hello/main/BUILD)

This binary has a source file, `main.py`, with its "main". A Python binary's "main" can be in a
depended-upon `python_library` or in the `python_binary`'s `source`. (Notice that's `source`,
not `sources`; a binary can have only one source file. If you want more, put them in a
`python_library` and let the `python_binary` depend on that.)

!inc[start-at=main](hello/main/main.py)

This code imports code from another target. To make this work, the
binary target has a dependency `examples/src/python/example/hello/greet`
and the Python code can thus import things from `example.hello.greet`.

You remember that libraries configure "importable" code;
`example/hello/greet/BUILD` has a `python_library`:

!inc[start-at=python_library](hello/greet/BUILD)

This `python_library` pulls in `greet.py`'s Python code:

!inc[start-at=green](hello/greet/greet.py)

BUILD for Tests
---------------

To test the library's code, we set up
[`examples/tests/python/example_test/hello/greet/BUILD`](https://github.com/pantsbuild/pants/blob/master/examples/tests/python/example_test/hello/greet/BUILD)
with a `python_tests` target. It depends on the library:

!inc[start-at=python_tests](../../../tests/python/example_test/hello/greet/BUILD)

Use `test` to run the tests. This uses `pytest`:

    :::bash
    $ ./pants test examples/tests/python/example_test/hello/greet

    13:29:28 00:00 [main]
                   (To run a reporting server: ./pants server)
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

                         examples/tests/python/example_test/hello/greet/greet.py .

                         ============ 1 passed in 0.02 seconds ============

    13:30:18 00:50     [junit]
    13:30:18 00:50     [specs]
                   SUCCESS
    $

Handling `python_requirement`
-----------------------------

`BUILD` files specify outside Python dependencies via
<a pantsref="bdict_python_requirements">`python_requirements`</a> and a
`requirements.txt` file and/or
<a pantsref="bdict_python_requirement_library">`python_requirement_library`</a> targets wrapping
<a pantsref="bdict_python_requirement">`python_requirement`</a>s.

Pants handles these dependencies for you. It never installs anything
globally. Instead, it builds the dependencies, caches them in `.pants.d`,
and assembles them *a la carte* into an execution environment.

PEX Contents
------------

To build a PEX, invoke `./pants binary` on a `python_binary`
target:

    :::bash
    $ ./pants binary examples/src/python/example/hello/main
      ...
                     SUCCESS
    $ ./dist/main.pex
      Hello, world!

Though the binary itself specifies just one dependency, the transitive
closure of hello/main's dependencies pulled in hello/greet and, in turn,
hello/greet's dependencies. Pants bundles up the closed set of all
dependencies into into the PEX.

Interactive Console with `repl` Goal
------------------------------------

Use the <a pantsref="oref_goal_repl">`repl`</a> goal with a Python target to run an interactive
Python REPL session.
Within the session, you can `import` the target's code and the code of its dependencies.

To drop into our example library target `examples/src/python/example/hello/greet` with verbosity
turn on to see what's going on in the background:

    :::bash
    $ ./pants -ldebug repl examples/src/python/example/hello/greet

    15:11:41 00:00 [main]
                   (To run a reporting server: ./pants server)
      ...lots of build output...
    15:11:42 00:01   [repl]
    15:11:42 00:01     [python-repl]Building chroot for [PythonLibrary(BuildFileAddress(/Users/lhosken/workspace/pants/examples/src/python/example/hello/greet/BUILD, greet))]:
      Dumping library: PythonLibrary(BuildFileAddress(/Users/lhosken/workspace/pants/examples/src/python/example/hello/greet/BUILD, greet))
      Dumping requirement: ansicolors==1.0.2
      Dumping distribution: .../ansicolors-1.0.2-py2-none-any.whl

    15:11:42 00:01       [run]
    Python 2.7.5 (default, Mar  9 2014, 22:15:05)
    [GCC 4.2.1 Compatible Apple LLVM 5.0 (clang-500.0.68)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>>

Pants loads `ansicolors` (`greet`'s 3rdparty dependency). It would have
fetched this dependency over the network if necessary. (It wasn't
necessary to download `ansicolors`; Pants had already fetched it while
"bootstrapping" itself.)

To convince yourself that the environment contains `greet`'s dependencies, you can inspect
`sys.path` and import libraries:

    :::python
    >>> from example.hello.greet.greet import greet
    >>> greet("escape codes")
    u'\x1b[32mHello, escape codes!\x1b[0m'
    >>> from colors import red
    >>> red("other escape codes")
    '\x1b[31mother escape codes\x1b[0m'

**Dependencies built by Pants are never installed globally**. These
dependencies only exist for the duration of the Python interpreter
forked by Pants.

`python_binary` `entry_point`
---------------------------

An advanced feature of `python_binary` targets, you may in addition
specify direct entry points into PEX files rather than a source file.
For example, if we wanted to build an a la carte fab wrapper for fabric:

    :::python
    python_binary(name = "fab",
      entry_point = "fabric.main:main",
      dependencies = [
        "3rdparty/python:fabric",
      ]
    )

We build:

    :::bash
    $ ./pants src/python/fabwrap:fab
    ...
    Wrote /private/tmp/wickman-pants/dist/fab.pex

And now dist/fab.pex behaves like a standalone fab binary:

    :::bash
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

More About Python Tests
-----------------------

Pants runs Python tests with `pytest`. You can pass CLI options to `pytest` with
`test.pytest --options`. For example, to only run tests whose names contain `req`,
you could run:

    :::bash
    $ ./pants test.pytest --options='-k req' examples/tests/python/example_test/hello/greet
    ...
                     ============== test session starts ===============
                     platform darwin -- Python 2.6.8 -- py-1.4.20 -- pytest-2.5.2
                     plugins: cov, timeout
                     collected 2 items

                     ========= 2 tests deselected by '-kfoo' ==========
                     ========== 2 deselected in 0.01 seconds ==========

    13:34:28 00:02     [junit]
    13:34:28 00:02     [specs]
               SUCCESS

You can pass CLI options to `pytest` via passthrough parameters if `test.pytest` is the last goal
and task on your command line. E.g., to run only tests whose names contain `req` via passthrough
parameters:

    :::bash
    $ ./pants test.pytest examples/tests/python/example_test/hello/greet -- -k req
       ...lots of build output...
    10:43:04 00:01   [test]
    10:43:04 00:01     [run_prep_command]
    10:43:04 00:01       [prep_command]
    10:43:04 00:01     [pytest]
    10:43:04 00:01       [run]
                         ============== test session starts ===============
                         platform darwin -- Python 2.7.5 -- py-1.4.26 -- pytest-2.6.4
                         plugins: cov, timeout
                         collected 2 items

                         examples/tests/python/example_test/hello/greet/greet.py .

                         ========= 1 tests deselected by '-kreq' ==========
                         ===== 1 passed, 1 deselected in 0.05 seconds =====

    10:43:05 00:02     [junit]
    10:43:05 00:02     [specs]
                   SUCCESS

...and to "unsilence" py.test (not suppress stderr and stdout), pass `-- -s`:

    :::bash
    $ ./pants test.pytest examples/tests/python/example_test/hello/greet -- -s

...and to remind yourself of py.test's help:

    :::bash
    $ ./pants test.pytest examples/tests/python/example_test/hello/greet -- -h

### Code Coverage

To get code coverage data, set the `--coverage` flag in `test.pytest` scope.
If you haven't configured coverage data, it doesn't do much:

    :::bash
    $ ./pants test.pytest --coverage=1 examples/tests/python/example_test/hello/greet:greet
        ...lots of build output...
                         ============ 2 passed in 0.23 seconds ============
                         Name    Stmts   Miss  Cover
                         ---------------------------
                         No data to report.

    14:30:36 00:04     [junit]
    14:30:36 00:04     [specs]

This uses the `python_tests.coverage` target attribute to determine what
modules to measure coverage against for each `python_tests` target run.
If the attribute is not present it's assumed the coverage should be
measured over the same packages that house the test target's sources.
This heuristic only works with parallel source and test package
structures and reliance upon it is discouraged.

There are 2 alternatives to specifying coverage attributes on all
`python_tests` targets, but both override any existing coverage
attributes in-play to form a global coverage specification for the test
run.

`--coverage=modules:[module1](,...,[moduleN])` allows specification of
package or module names to track coverage against. For example:

    :::bash
    $ ./pants test.pytest --coverage=modules:example.hello.greet,example.hello.main examples/tests/python/example_test/hello/greet:greet
        ...lots of build output...
                     ============ 2 passed in 0.22 seconds ============
                     Name                                               Stmts   Miss Branch BrMiss  Cover
                     ------------------------------------------------------------------------------------
                     examples/src/python/example/hello/greet/__init__       0      0      0      0   100%
                     examples/src/python/example/hello/greet/greet          4      0      0      0   100%
                     ------------------------------------------------------------------------------------
                     TOTAL                                                  4      0      0      0   100%

This measures coverage against all python code in `example.hello.greet` and `example.hello.main`.
It ignores `python_library` `coverage=...` attributes.

Similarly, a set of base paths can be specified containing the code for
coverage to be measured over:

    :::bash
    $ ./pants test.pytest --coverage=paths:example/hello examples/tests/python/example_test/hello/greet:greet
        ...lots of build output...
                     ============ 2 passed in 0.23 seconds ============
                     Name                                               Stmts   Miss Branch BrMiss  Cover
                     ------------------------------------------------------------------------------------
                     examples/src/python/example/hello/__init__             0      0      0      0   100%
                     examples/src/python/example/hello/greet/__init__       0      0      0      0   100%
                     examples/src/python/example/hello/greet/greet          4      0      0      0   100%
                     ------------------------------------------------------------------------------------
                     TOTAL                                                  4      0      0      0   100%

Paths are relative to the source root housing the python code; for this example,
`examples/src/python`.

### Interactive Debugging on Test Failure

You can invoke the Python debugger on a test failure by leaving out the
`test` and passing `--pdb`. This can be useful for inspecting the
state of objects especially if you are mocking interfaces.

Building a `setup.py` Distutils Package
---------------------------------------

You can build Distutils packages from `python_library` targets.

To make a `python_library` "setup-able", give it a `provides` parameter; this parameter's value
should be a <a pantsref="bdict_setup_py">`setup_py`</a> call; this call's parameters will be
passed to the `setup` function.

    :::python
    python_library(
      name='test_infra',
      dependencies=[
        'tests/python/pants_test:base_test',
        ...
      ],
      provides=setup_py(
        name='pantsbuild.pants.testinfra',
        version='0.0.24',
        description='Test support for writing pants plugins.',
        long_description='''A much longer description of this package. Pages and pages!''',
        url='https://github.com/pantsbuild/pants',
        license='Apache License, Version 2.0',
        zip_safe=True,
        namespace_packages=['pants_test'],
        classifiers=[
          'Intended Audience :: Developers',
          'License :: OSI Approved :: Apache Software License',
          'Operating System :: MacOS :: MacOS X',
          'Operating System :: POSIX :: Linux',
          'Programming Language :: Python',
          'Topic :: Software Development :: Build Tools',
          'Topic :: Software Development :: Testing',
        ]
      )
    )

The <a pantsref="oref_goal_setup-py">`setup-py`</a> goal builds a package from such a target:

    :::bash
    $ ./pants setup-py src/python/pants:test_infra
    10:23:06 00:00 [main]
                   (To run a reporting server: ./pants server)
    10:23:07 00:01   [bootstrap]
    10:23:07 00:01   [setup]
    10:23:07 00:01     [parse]
                   Executing tasks in goals: setup-py
    10:23:07 00:01   [setup-py]
    10:23:07 00:01     [setup-py]
                       Running packager against /Users/you/workspace/pants/dist/pantsbuild.pants.testinfra-0.0.24
                       Writing /Users/you/workspace/pants/dist/pantsbuild.pants.testinfra-0.0.24.tar.gz
                   SUCCESS


Manipulating PEX behavior with environment variables
----------------------------------------------------

You can alter a PEX file's behavior during invocation by setting some
environment variables.

### `PEX_INTERPRETER=1`

If you have a PEX file with a prescribed executable source or
`entry_point`, you can still drop into an interpreter with the
environment bootstrapped. Set `PEX_INTERPRETER=1` in your environment,
and the PEX bootstrapper skips any execution and instead launches an
interactive interpreter session.

### `PEX_VERBOSE=1`

If your environment is failing to bootstrap or simply bootstrapping very
slowly, it can be useful to set `PEX_VERBOSE=1` in your environment to
get debugging output printed to the console. Debugging output includes:

1.  Fetched dependencies
2.  Built dependencies
3.  Activated dependencies
4.  Packages scrubbed out of sys.path
5.  The sys.path used to launch the interpreter

### `PEX_MODULE=entry_point`

If you have a PEX file without a prescribed entry point, or want to
change the `entry_point` for a single invocation, you can set
`PEX_MODULE=entry_point` using the same format as described in the
<a pantsref="bdict_python_binary">`python_binary`</a> Pants target.

This can be useful for bundling up some packages together and using that
single file to execute scripts from each of them.

Another common pattern is to link pytest into your PEX file, and run
`PEX_MODULE=pytest my_pex.pex tests/*.py` to run your test suite in its
isolated environment.

### `PEX_COVERAGE`

There is nascent support for performing code coverage within PEX files
by setting `PEX_COVERAGE=<suffix>`. By default the coverage files will
be written into the current working directory with the file pattern
`.coverage.<suffix>`. This requires that the coverage Python module has
been linked into your PEX.

You can then combine the coverage files by running `PEX_MODULE=coverage`
`my_pex.pex` `.coverage.suffix*` and run a report using
`PEX_MODULE=coverage`
`my_pex.pex` report. Since PEX files are just zip files, coverage is able
to understand and extract source and line numbers from them in order to
produce coverage reports.
