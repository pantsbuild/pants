##########################
Python Projects with Pants
##########################

Pants makes the manipulation and distribution of hermetically sealed Python
environments painless.
You can organize your code in the :doc:`Pants way <first_concepts>`,
with targets for binaries, libraries, and
use it to build Python code into
`PEXes <https://github.com/twitter/commons/blob/master/src/python/twitter/common/python/README.md>`_
(A PEX is, roughly, an archive file containing a runnable Python environment.)
Pants isn't the only PEX-generation tool out there; but if you have some
"common code" used by more than one PEX, Pants is a good way to get that
working.

Pants' Python support changed in 2014. Depending on how old your Pants is,
Pants goals might not work with Python code. If you use older pants (e.g.,
if you work in twitter/commons), please see :doc:`python_old`.

****************************************
TL;DR - 'Hello world!' with Pants Python
****************************************

.. code-block:: bash

  $ git clone git://github.com/twitter/commons
  $ cd commons
  $ mkdir -p src/python/twitter/my_project
  $ vi src/python/twitter/my_project/BUILD

`src/python/twitter/my_project/BUILD`::

  python_binary(
    name = 'hello_world',
    source = 'hello_world.py'
  )

.. code-block:: bash

  $ vi src/python/twitter/my_project/hello_world.py

`src/python/twitter/my_project/hello_world.py` might have contents::

  print('Hello world!')

To run directly:

.. code-block:: bash

  $ ./pants py src/python/twitter/my_project:hello_world
  Build operating on target: PythonBinary(src/python/twitter/my_project/BUILD:hello_world)
  Hello world!


To build:

.. code-block:: bash

  $ ./pants src/python/twitter/my_project:hello_world
  Build operating on targets: OrderedSet([PythonBinary(src/python/twitter/my_project/BUILD:hello_world)])
  Building PythonBinary PythonBinary(src/python/twitter/my_project/BUILD:hello_world):
  Wrote /Users/wickman/clients/science-py-csl/dist/hello_world.pex

and run separately:

.. code-block:: bash

  $ dist/hello_world.pex
  Hello world!

NOTE: The first time you run `./pants`, it will be slow,
as it bootstraps itself inside your directory.  Note, it never
installs anything in a global site-packages.

***************************************
Describing Python environments in Pants
***************************************

Build dependencies in Pants are managed with `BUILD` files
co-located with your source.
In the usual :doc:`Pants way <first_concepts>`, these files
define the "buildable things" in your code and the dependency
relations between them. In the :doc:`Tutorial <first_tutorial>`,
you saw ``BUILD`` targets useful for Java. Python ``BUILD`` targets
will sound familiar:

* :ref:`bdict_python_library`: an import-able piece of Python code.
* :ref:`bdict_python_binary`:  a single source (the executable)
* :ref:`bdict_python_requirement_library`,
  :ref:`bdict_python_requirement`: external dependency, resolved by pypi.
  These tend to live in :doc:`a 3rdparty area<3rdparty_py>`
* :ref:`bdict_python_tests`: collection of ``pytest`` tests

Let's look at the BUILD file in twitter/commons'
``src/python/twitter/tutorial/BUILD``::

  python_binary(
    name = "hello_world",
    source = "hello_world.py",
    dependencies = [
      pants("src/python/twitter/common/app"),
    ]
  )

This BUILD file names one target: `hello_world`, a `python_binary` target.
The `hello_world` target
contains one source file, `hello_world.py`, and depends upon one other
target, the format of which will be described shortly.

Sources are relative to the location of the BUILD
file itself. E.g.,  ``hello_world.py`` in
``src/python/twitter/tutorial/BUILD`` refers to
`src/python/twitter/tutorial/hello_world.py`::

  from twitter.common import app

  def main():
    print('Hello world!')

  app.main()

Dependencies, on the other hand, are relative to the root of
workspace, the location of the `pants` command.
For more about specifying the addresses of dependencies
(and addresses of other things), see :doc:`target_addresses`.

.. this said deps relative to source root. that's not true now. so
   removed that. BUT source root's still useful, so say *something*
   about it.

The ``hello_world`` binary depends on a ``python_library`` target:

``src/python/twitter/common/app/BUILD``::

  python_library(
    name = "app",
    sources = globs('*.py'),
    dependencies = [
      pants('src/python/twitter/common/dirutil'),
      pants('src/python/twitter/common/lang'),
      pants('src/python/twitter/common/options'),
      pants('src/python/twitter/common/util'),
      pants('src/python/twitter/common/app/modules'),
    ]
  )

which in turn includes even more dependencies.
Pants manages these transitive closure
of all these dependencies and manipulates collections of these targets for you.

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

The `python_requirement` for a particular dependency should appear
only once in a BUILD file.  It creates a local target name which can
then be included in other dependencies in the file. ::

  python_requirement('django-celery')

  python_library(
    name = 'mylib_1',
    sources = [
      'mylib_1.py',
    ],
    dependencies = [
      pants(':django-celery')
    ]
  )

  python_library(
    name = 'mylib_2',
    sources = [
      'mylib_2.py',
    ],
    dependencies = [
      pants(':django-celery')
    ]
  )

*************************
``python_thrift_library``
*************************

A `python_thrift_library` target takes the same arguments as `python_library`
arguments, except that files described
in `sources` must be thrift files.
If your library or binary depends upon this target type, Python bindings
will be autogenerated and included within your environment.


**************
Building a PEX
**************

To build a PEX, invoke ``./pants goal binary`` on a
``python_binary`` target:

.. code-block:: bash

  $ PANTS_VERBOSE=1 ./pants goal binary src/python/twitter/tutorial:hello_world
    ...
  Wrote /private/tmp/wickman-commons/dist/hello_world.pex

Though the binary itself specifies just one dependency, the transitive
closure of `hello_world`'s dependencies pulled in all of
`src/python/twitter/common/app` and its descendants.
That's because those library targets depend
upon other library targets, that in turn depend on even more.
Pants bundles up the closed set of all dependencies into
into `hello_world.pex`.

We can simply execute the PEX:

.. code-block:: bash

  $ dist/hello_world.pex
  Hello world!

****************************************
Environment manipulation with `pants py`
****************************************

Pants has a "py" command that lets you manipulate the environments
described by `python_binary` and `python_library` targets, such as drop into
an interpreter with the environment set up for you.
Note that's "py", **not** "goal py".

`pants py` semantics
====================

By default, `pants py <target>`...

1. For `python_binary` targets, builds the environment and executes the target
2. For `python_library` targets, builds the environment that is the transitive
   closure of all targets and drops into an interpreter.
3. For a combination of `python_binary` and `python_library` targets, builds
   the transitive closure of all targets and executes the first binary target.


external dependencies
=====================

Let's take `src/python/twitter/tutorial/BUILD` and split out the dependencies from
our `hello_world` target into `hello_world_lib` and add dependencies upon
Tornado and psutil.::

    python_binary(
      name = "hello_world",
      source = "hello_world.py",
      dependencies = [
        pants(":hello_world_lib")
      ]
    )

    python_library(
      name = "hello_world_lib",
      dependencies = [
        pants("src/python/twitter/common/app"),
        python_requirement("tornado"),
        python_requirement("psutil"),
      ]
    )

This uses the ``python_requirement`` target which can refer to any string
in ``pkg_resources.Requirement`` format as
recognized by tools such as ``easy_install`` and ``pip`` as described above.

Now that we've created a library-only target `src/python/twitter/tutorial:hello_world_lib`, let's drop
into it using `pants py` with verbosity turned on so that we can see what's
going on in the background:

.. code-block:: bash

  $ PANTS_VERBOSE=1 ./pants py src/python/twitter/tutorial:hello_world_lib
  Build operating on target: PythonLibrary(src/python/twitter/tutorial/BUILD:hello_world_lib)
    Resolver: Calling environment super => 0.019ms
  Building PythonBinary PythonLibrary(src/python/twitter/tutorial/BUILD:hello_world_lib):
    Dumping library: PythonLibrary(src/python/twitter/tutorial/BUILD:hello_world_lib) [relative module: ]
    Dumping library: PythonLibrary(src/python/twitter/common/app/BUILD:app) [relative module: ]
    Dumping library: PythonLibrary(src/python/twitter/common/dirutil/BUILD:dirutil) [relative module: ]
    Dumping library: PythonLibrary(src/python/twitter/common/lang/BUILD:lang) [relative module: ]
    Dumping library: PythonLibrary(src/python/twitter/common/options/BUILD:options) [relative module: ]
    Dumping library: PythonLibrary(src/python/twitter/common/util/BUILD:util) [relative module: ]
    Dumping library: PythonLibrary(src/python/twitter/common/app/modules/BUILD:modules) [relative module: ]
    Dumping requirement: tornado
    Dumping requirement: psutil
    Resolver: Calling environment super => 0.029ms
    Resolver: Activating cache /private/tmp/wickman-commons/3rdparty/python => 356.432ms
    Resolver: Resolved tornado => 357.219ms
    Resolver: Activating cache /private/tmp/wickman-commons/.pants.d/.python.install.cache => 41.117ms
    Resolver: Fetching psutil => 10144.264ms
    Resolver: Building psutil => 1794.474ms
    Resolver: Distilling psutil => 224.896ms
    Resolver: Constructing distribution psutil => 2.855ms
    Resolver: Resolved psutil => 12210.066ms
    Dumping distribution: .../tornado-2.2-py2.6.egg
    Dumping distribution: .../psutil-0.4.1-py2.6-macosx-10.4-x86_64.egg
  Python 2.6.7 (r267:88850, Aug 31 2011, 15:49:05)
  [GCC 4.2.1 (Apple Inc. build 5664)] on darwin
  Type "help", "copyright", "credits" or "license" for more information.
  (InteractiveConsole)
  >>> 

In the background, `pants` used cached version of `tornado` but fetched
`psutil` from pypi and any necessary transitive dependencies (none in this
case) and built a platform-specific version for us.

You can convince yourself that the environment contains all the dependencies
by inspecting `sys.path` and importing libraries as you desire::

  >>> import psutil
  >>> help(psutil)
  >>> from twitter.common import app
  >>> help(app)

It should be stressed that *dependencies built by Pants are never installed globally*.
These dependencies only exist for the duration of the Python interpreter forked by Pants.


Running a binary with ``pants py``
==================================

Let us turn our `hello_world.py` into a basic `top` application using `tornado`::

  from twitter.common import app

  import psutil
  import tornado.ioloop
  import tornado.web

  class MainHandler(tornado.web.RequestHandler):
    def get(self):
      self.write('<pre>Running pids:\n%s</pre>' % '\n'.join(map(str, psutil.get_pid_list())))

  def main():
    application = tornado.web.Application([
      (r"/", MainHandler)
    ])
    application.listen(8888)
    tornado.ioloop.IOLoop.instance().start()

  app.main()

We have now split our application into two parts: the `hello_world` binary
target and the `hello_world_lib` library target.  If we run `pants py
src/python/twitter/tutorial:hello_world_lib`, the default behavior is to
drop into an interpreter.

If we run `pants py src/python/twitter/tutorial:hello_world`, the default behavior is to run
the binary target pointed to by `hello_world`:

.. code-block:: bash

  $ ./pants py src/python/twitter/tutorial:hello_world

Then point your browser to http://localhost:8888

``pants py --pex``
==================

There is also a --pex option to pants py that allows you to build a PEX
file from a union of python_library targets that does not necessarily have a
`python_binary` target defined for it.  Since there is no entry point
specified, the resulting .pex file just behaves like a Python interpreter,
but with the sys.path bootstrapped for you:

.. code-block:: bash

  $ ./pants py --pex src/python/twitter/tutorial:hello_world_lib
  Build operating on target: PythonLibrary(src/python/twitter/tutorial/BUILD:hello_world_lib)
  Wrote /private/tmp/wickman-commons/dist/hello_world_lib.pex

  $ ls -la dist/hello_world_lib.pex
  -rwxr-xr-x  1 wickman  wheel  1404174 Apr 10 13:00 dist/hello_world_lib.pex

Now if you use dist/hello_world_lib.pex, since it has no entry point, it will drop you into an interpreter:

.. code-block:: bash

  $ dist/hello_world_lib.pex
  Python 2.6.7 (r267:88850, Aug 31 2011, 15:49:05)
  [GCC 4.2.1 (Apple Inc. build 5664)] on darwin
  Type "help", "copyright", "credits" or "license" for more information.
  (InteractiveConsole)
  >>> import tornado

As mentioned before, it's like a single-file lightweight alternative to a
virtualenv.  We can even use it to run our `hello_world.py` application:

.. code-block:: bash

  $ dist/hello_world_lib.pex src/python/twitter/tutorial/hello_world.py

This can be an incredibly powerful and lightweight way to manage and deploy
virtual environments without using `virtualenv`.

PEX file as interpreter
=======================

As mentioned above, PEX files without default entry points behave like Python interpreters that
carry their dependencies with them.  For example, let's create a target that
provides a Fabric dependency within `src/python/twitter/tutorial/BUILD`::

  python_library(
    name = 'fabric',
    dependencies = [
      python_requirement('Fabric')
    ]
  )

And let's build a fabric PEX file:

.. code-block:: bash

  $ ./pants py --pex src/python/twitter/tutorial:fabric
  Build operating on target: PythonLibrary(src/python/twitter/tutorial/BUILD:fabric)
  Wrote /private/tmp/wickman-commons/dist/fabric.pex

By default it does nothing more than drop us into an interpreter:

.. code-block:: bash

  $ dist/fabric.pex
  Python 2.6.7 (r267:88850, Aug 31 2011, 15:49:05)
  [GCC 4.2.1 (Apple Inc. build 5664)] on darwin
  Type "help", "copyright", "credits" or "license" for more information.
  (InteractiveConsole)
  >>>

But suppose we have a local script that depends upon Fabric, `fabric_hello_world.py`::

  from fabric.api import *

  def main():
    local('echo hello world')

  if __name__ == '__main__':
    main()

We can now use `fabric.pex` as if it were a Python interpreter but with
fabric available in its environment.  Note that fabric has never been
installed globally in any site-packages anywhere.  It is just bundled inside
of fabric.pex:

.. code-block:: bash

  $ dist/fabric.pex fabric_hello_world.py
  [localhost] local: echo hello world
  hello world



*************************
python_binary entry_point
*************************

An advanced feature of `python_binary` targets, you may in addition specify
direct entry points into PEX files rather than a source file.  For example,
if we wanted to build an a la carte `fab` wrapper for fabric::

  python_binary(name = "fab",
    entry_point = "fabric.main:main",
    dependencies = [
      python_requirement("fabric"),
    ]
  )


We build:

.. code-block:: bash

  $ ./pants src/python/twitter/tutorial:fab
  Build operating on targets: OrderedSet([PythonBinary(src/python/twitter/tutorial/BUILD:fab)])
  Building PythonBinary PythonBinary(src/python/twitter/tutorial/BUILD:fab):
  Wrote /private/tmp/wickman-commons/dist/fab.pex

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

Pants also has excellent support for JVM-based builds and can do similar
things like resolving external JARs and packaging them as standalone
environments with default entry points.

************
Python Tests
************

By default Python tests are run via `pytest`. Any option that `py.test` has can be used since
arguments are passed on by `pants`.

``python_tests`` Targets
========================

When setting up your test targets, the BUILD file will be something like::

  python_tests(
    name = "your_tests",
    sources = globs("*.py"),
    coverage = ["twitter.your_namespace"],
    dependencies = [
      pants("3rdparty/python:mock")
      pants("src/python/twitter/your_namespace")
   ]
  )

The above target is very similar to a `python_library` with the addition of the `coverage` argument.
`coverage` allows you to retrict the namespaces for which code coverage data is generated.

Running Python Tests
====================

To run your Python tests, invoke the ``test`` goal on ``python_tests`` targets::

  $ ./pants goal test tests/python/twitter/your_tests/BUILD:your_tests
  Build operating on targets: OrderedSet([PythonTests(tests/python/twitter/your_tests/BUILD:your_tests)])
  ================================================== test session starts ===================================================
  platform darwin -- Python 2.6.7 -- pytest-2.3.5
  collected 15 items:

  tests/python/twitter/your_tests/module1_test.py ....
  tests/python/twitter/your_tests/module2_test.py ....
  tests/python/twitter/your_tests/module3_test.py ....

  =============================================== 15 passed in 0.44 seconds ================================================
  tests.python.twitter.your_tests.your_tests                                    .....   SUCCESS


Sometimes you only want to run specific tests (or exclude them). The `-k` option controls the
tests to run. `-k` will do substring matches on test method names and can also use keywords like
`not` and `or` to refine results.

.. https://github.com/pantsbuild/pants/issues/275 TODO, switch this
   to use 'goal test' instead. (I dunno the "goal test" equivalent)

.. code-block:: bash

  $ ./pants tests/python/twitter/your_tests/BUILD:your_tests -k 'module1_instantiation_test or module1_foo_test' -v
  Build operating on targets: OrderedSet([PythonTests(tests/python/twitter/your_tests/BUILD:your_tests)])
  ================================================== test session starts ===================================================
  platform darwin -- Python 2.6.7 -- pytest-2.3.5
  collected 15 items:

  tests/python/twitter/your_tests/module1_test.py:3: Module1Test.module1_instantiation_test PASSED
  tests/python/twitter/your_tests/module1_test.py:21: Module1Test.module1_foo_test PASSED

  ======================= 13 tests deselected by '-kmodule1_instantiation_test or module1_foo_test' ========================
  ================================================ 2 passed in 0.14 seconds ================================================
  tests.python.twitter.your_tests.your_tests                                    .....   SUCCESS

You can also mark tests via a decorator::

  @pytest.mark.module1
  def module1_instantiation_test():
      # testing code here

Using `-m` you can specify the marks of tests that you want to execute.

Code Coverage
=============

To get code coverage data, set the `PANTS_PY_COVERAGE` environment variable:

.. code-block:: bash

  $ PANTS_PY_COVERAGE=1 ./pants tests/python/twitter/your_tests/BUILD:your_tests
  Build operating on targets: OrderedSet([PythonTests(tests/python/twitter/your_tests/BUILD:your_tests)])
  ============================================================ test session starts ============================================================
  platform darwin -- Python 2.6.7 -- pytest-2.3.5
  collected 15 items:

  tests/python/twitter/your_tests/module1_test.py ....
  tests/python/twitter/your_tests/module2_test.py ....
  tests/python/twitter/your_tests/module3_test.py ....
  ---------------------------------------------- coverage: platform darwin, python 2.6.7-final-0 ----------------------------------------------
  Name                                                                                                     Stmts   Miss Branch BrMiss  Cover
  ------------------------------------------------------------------------------------------------------------------------------------------
  /private/var/folders/p0/ztm93vq94qzfc1nyfkq_4l7r0000gn/T/tmp6BcJ1r/twitter/your_namespace/__init__           0      0      0      0   100%
  /private/var/folders/p0/ztm93vq94qzfc1nyfkq_4l7r0000gn/T/tmp6BcJ1r/twitter/your_namespace/module1           62     62      8      8     0%
  /private/var/folders/p0/ztm93vq94qzfc1nyfkq_4l7r0000gn/T/tmp6BcJ1r/twitter/your_namespace/module2           34      6      6      0    85%
  /private/var/folders/p0/ztm93vq94qzfc1nyfkq_4l7r0000gn/T/tmp6BcJ1r/twitter/your_namespace/module3          170    170     51     51     0%
  ------------------------------------------------------------------------------------------------------------------------------------------
  TOTAL                                                                                                      266    238     57     59    11%
  Coverage HTML written to dir /Users/your_username/workspace/science/dist/coverage/tests/python/twitter/your_tests
  ========================================================= 15 passed in 2.07 seconds =========================================================
  tests.python.twitter.your_tests.your_tests                                    .....   SUCCESS


Interactve Debugging on Test Failure
====================================

You can invoke the Python debugger on a test failure by passing ``--pdb``.
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

The `entry_point` should exit with a non-zero status if there are any test failures.

Keep in mind, however, that much of the above documentation assumes you are using `pytest`.

****************************************************
Manipulating PEX behavior with environment variables
****************************************************

Given a PEX file, it is possible to alter its default behavior during invocation.

PEX_INTERPRETER=1
=================

If you have a PEX file with a prescribed executable source or `entry_point` specified, it may still
occasionally be useful to drop into an interpreter with the environment bootstrapped.  If you
set `PEX_INTERPRETER=1` in your environment, the PEX bootstrapper will skip any execution and instead
launch an interactive interpreter session.


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
the `entry_point` for the duration of a single invocation, you can set
`PEX_MODULE=entry_point` using the same format as described in the
`python_binary` Pants target.

This can be a useful tool for bundling up a number of packages together and
being able to use a single file to execute scripts from each of them.

Another common pattern is to link `pytest` into your PEX file, and run
`PEX_MODULE=pytest my_pex.pex tests/*.py` to run your test suite in its
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
