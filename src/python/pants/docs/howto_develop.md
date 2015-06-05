Pants Developers Guide
======================

This page describes the developer workflow when changing Pants itself. (If you wanted
instructions for using Pants to develop other programs, please see
[[First Tutorial|pants('src/docs:first_tutorial')]].)

These instructions assume you've already
<a pantsref="download_source_code">downloaded the source code</a>.

Running from sources
--------------------

As pants is implemented in python it can be run directly from sources.

    :::bash
    $ PANTS_DEV=1 ./pants goals
    *** running pants in dev mode from ./src/python/pants/bin/pants_exe.py ***
    <remainder of output omitted for brevity>

Notice this invocation specifies the `PANTS_DEV` environment variable.
By defining `PANTS_DEV` pants will be run from sources.

Building a Pants PEX for Testing
--------------------------------

The `./pants` wrapper provides a convenient way to produce a `.pex` file for testing pants on
your local workstation. If you call it without the `PANTS_DEV=1` environment described above, it

+   Checks the source tree's top directory for a `pants.pex` and runs
    it if it exists. Otherwise `./pants`...
+   Builds a new `pants.pex`, moves it to the source tree's top
    directory, and runs that.

It looks something like

    :::bash
    $ rm pants.pex
    $ ./pants my-new-feature
    Building pants.pex to /Users/zundel/Src/Pants/pants.pex...
    ...
    Build operating on top level addresses: set([BuildFileAddress(/Users/pantsdev/Src/pants/src/python/pants/bin/BUILD, pants_local_binary)])
    Building PythonBinary PythonBinary(BuildFileAddress(/Users/pantsdev/Src/pants/src/python/pants/bin/BUILD, pants_local_binary)):
    Wrote /Users/pantsdev/Src/pants/dist/pants_local_binary.pex
    /Users/pantsdev/Src/Pants/dist/pants_local_binary.pex -> /Users/pantsdev/Src/Pants/pants.pex
    AMAZING NEW FEATURE PRINTS HERE
    $ ls pants.pex # gets moved here, though originally "Wrote" to ./dist/
    pants.pex
    $ ./pants my-new-feature
    AMAZING NEW FEATURE PRINTS HERE

Using `./pants` to launch Pants thus gives a handy workflow: generate `pants.pex`.
Go back and forth between trying the generated `pants.pex` and fixing source code as inspired by
its misbehaviors. When the fixed source code is in a consistent state, remove `pants.pex` so
that it will get replaced on the next `./pants` run.

Building a Pants PEX for Production
-----------------------------------

You will usually want to use an official published version of pants. But what if you want to
let some of your internal users try out the latest and greatest unreleased code?
What if you want to create a custom build of pants with some unpublished patches?
In that case, you want to build a production ready version of pants including dependencies for
all platforms, not just your development environment.

The following command will create a locally built `pants.pex` for all platforms:

    :::bash
    $ ./pants binary src/python/pants/bin:pants
    ...
    SUCCESS

The resulting `pants.pex` will be in the `dist/` directory:

    :::bash
    $ ls -l dist/pants.pex
    -rwxr-xr-x  1 pantsdev  pantsdev  5561254 Oct  8 09:52 dist/pants.pex

You can see that the pex contains bundled dependencies for both mac and linux:

    :::bash
    $ unzip -l dist/pants.pex | grep -e 'macos\|linux'

You can distribute the resulting `pants.pex` file to your users via your favorite method.
A user can just copy this pex to the top of their Pants workspace and use it:

    :::bash
    $ cp /mnt/fd0/pants.pex .
    $ ./pants.pex goal test examples/tests/java/org/pantsbuild/example/hello/greet:

There are some parameters in `src/python/pants/bin/BUILD` that you may want to tweak for your
production distribution. For example, you may want to force the Python interpreter to be a
specific version:

    :::python
    PANTS_COMPATIBILITY = 'CPython>=2.7,<2.8'

Testing
-------

<a pantsmark="dev_run_all_tests"> </a>

### Running Tests

Pants has many tests. There are BUILD targets to run those tests. We try to keep them passing.
[A Travis-CI job](https://travis-ci.org/pantsbuild/pants) runs tests on each SHA pushed to
origin on `github.com/pantsbuild/pants`.

Most test are runnable as regular Pants test targets. To find tests that work with a particular
feature, you might explore `tests/python/pants_tests/.../BUILD`.

Typically, you're not sure precisely which tests you need to run, so you run all of them.

To run all tests,

    :::bash
    $ ./pants test tests::

To run just Pants' *unit* tests (skipping the can-be-slow integration tests), use the
`tests/python/pants_test:all` target:

    :::bash
    $ ./pants test tests/python/pants_test:all

Before [[contributing a change to Pants|pants('src/python/pants/docs:howto_contribute')]],
make sure it passes **all** of our continuous integration (CI) tests: everything builds,
all tests pass. To try all the CI tests in a few configurations, you can run the same script
that our Travis CI does. This can take a while, but it's a good idea to run it before you
contribute a change or merge it to master:

    :::bash
    $ ./build-support/bin/ci.sh

You can run your code through the Travis-CI before you submit a change. Travis-CI is integrated
with the pull requests for the `pantsbuild/pants` repo. Travis-CI will test it soon after the pull
request is created. It will queue up a new job every time you subsequently push your branch.

To kick off a new CI-build, push a branch to
<a pantsref="download_source_code">your fork</a> of `pantsbuild/pants`.
Create a pull request on the `pantsbuild/pants` [repo](https://github.com/pantsbuild/pants),
not your fork. If you are posting a review request, put the pull request number into the Bug
field. Then, when you close the request, you can navigate from the bug number to easily close
the pull request.

Debugging
---------

To run Pants under `pdb` and set a breakpoint, you can typically add

    :::python
    import pdb; pdb.set_trace()

...where you first want to break. If the code is in a test, instead use

    :::python
    import pytest; pytest.set_trace()

To run tests and bring up `pdb` for failing tests, you can instead pass `--pdb` to
`test.pytest --options`:

    :::bash
    $ ./pants test.pytest --options='--pdb' tests/python/pants_test/tasks:
    ... plenty of test output ...
    tests/python/pants_test/tasks/test_targets_help.py E
    >>>>>>>>>>>>>>>>>>>>>>>>>>>>>> traceback >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

    cls = <class 'pants_test.tasks.test_targets_help.TargetsHelpTest'>

        @classmethod
        def setUpClass(cls):
    >     super(TargetsHelpTest, cls).setUpClass()
    E     AttributeError: 'super' object has no attribute 'setUpClass'

    tests/python/pants_test/tasks/test_targets_help.py:24: AttributeError
    >>>>>>>>>>>>>>>>>>>>>>>>>>>>> entering PDB >>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    > /Users/lhosken/workspace/pants/tests/python/pants_test/tasks/test_targets_help.py(24)setUpClass()
    -> super(TargetsHelpTest, cls).setUpClass()
    (Pdb)

Debug quickly; that test target will time out in a couple of minutes,
quitting you out.

To start an interactive Python shell that can `import` Pants modules,
use the usual `./pants py` on a `python_library` target that builds (or
depends on) the modules you want:

    :::bash
    $ ./pants py src/python/pants/backend/core/targets:common
    /Users/lhosken/workspace/pants src/python/pants/backend/core/targets:common
    Python 2.6.8 (unknown, Mar  9 2014, 22:16:00)
    [GCC 4.2.1 Compatible Apple LLVM 5.0 (clang-500.0.68)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>> from pants.backend.core.targets import repository
    >>>

Developing and Debugging a JVM Tool
-----------------------------------

Some Pants tools are written in Java and Scala. If you need
to debug one of these tools and change code, keep in mind that these tools don't
run straight from the Pants source tree.  They expect their jar dependencies to be
resolved through external jar dependencies.  This means that to use a development
version of a tool you will need to adjust the external dependency information
in `BUILD.tools` to point Pants at a development version of your jar file.

First, create a jar file for the tool with the `binary` goal.

    :::bash
    $ ./pants binary src/scala/org/pantsbuild/zinc::

The above command will create `dist/main.jar` according to the _jvm_binary_
target defined in `src/scala/org/pantsbuild/zinc/BUILD`


You'll need to update the jar dependency that this tool uses for Pants to see the
development version.  See
<a pantsref="test_3rdparty_jvm_snapshot">Using a SNAPSHOT JVM Dependency</a>
which describes how to specify the `url` and `mutable` attributes of a `jar`
dependency found on the local filesystem:

    :::python
    jar_library(name='zinc',
        jars=[
          jar(org='org.pantsbuild', name='zinc', rev='1.2.3-SNAPSHOT',
              url='file:///Users/squarepants/Src/pants/dist/main.jar', mutable=True),
      ],
    )

For debugging, append JVM args to turn on the debugger for the appropriate tool in
`pants.ini`:

    :::ini
    [compile.zinc-java]
    jvm_options: ['-Xdebug', '-Xrunjdwp:transport=dt_socket,server=y,suspend=y,address=5005']

Note that most tools run under nailgun by default. The easiest way to
debug them is to disable nailgun by specifying the command line option
`--no-use-nailgun` or setting `use_nailgun: False` in the specific tool section or in the
`[DEFAULT]` section of `pants.ini`.

    :::ini
    [DEFAULT]
    use_nailgun: False

If you need to debug the tool under nailgun, make
sure you run `pants goal ng-killall` or `pants goal clean-all` after you update the
jar file so that any running nailgun servers are restarted on the next invocation
of Pants.

Also, you may need to clean up some additional state when testing a tool. Some tools
cache a shaded version under `~/.cache/pants/artifact_cache/`.  Clear out the cache
before testing a new version of the tool as follows:

    :::bash
    $ rm -rf ~/.cache.pants/artifact_cache
