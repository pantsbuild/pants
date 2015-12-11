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
    $ ./pants goals
    <remainder of output omitted for brevity>

Building a Pants PEX for Production
-----------------------------------

You will usually want to use an official published version of pants. But what if you want to
let some of your internal users try out the latest and greatest unreleased code?
What if you want to create a custom build of pants with some unpublished patches?
In that case, you want to build a production ready version of pants including dependencies for
all platforms, not just your development environment.

In the following examples, you'll be using 2 local repos.  The path to the pantsbuild/pants clone
will be `/tmp/pantsbuild` and the path to your repo `/your/repo` in all the examples below; make
sure to substitute your own paths when adapting this recipe to your environment.

You'll need to setup some files one-time in your own repo:

    :::bash
    $ cat pants-production.requirements.txt
    # Replace this path with the path to your pantsbuild.pants clone.
    -f /tmp/pantsbuild/dist/
    pantsbuild.pants

    $ cat BUILD.pants-production
    python_requirements('pants-production.requirements.txt')

    python_binary(
      name='pants',
      entry_point='pants.bin.pants_exe:main',
      # You may want to tweak the list of supported platforms to match your environment.
      platforms=[
        'current',
        'linux-x86_64',
        'macosx-10.4-x86_64',
      ],
      # You may want to adjust the python interpreter constraints, but note that pants requires
      # python2.7 currently.
      compatibility='CPython>=2.7,<3',
      dependencies=[
        ':pantsbuild.pants',
        # List any other pants backend local or remote deps here, ie:
        # ':pantsbuild.pants.contrib.spindle' or 'src/python/your/pants/plugin'
      ]
    )

    $ cat pants-production.ini
    [python-repos]
    # You should replace these repos with your own housing pre-built eggs or wheels for the
    # platforms you support.
    repos: [
        "https://pantsbuild.github.io/cheeseshop/third_party/python/dist/index.html",
        "https://pantsbuild.github.io/cheeseshop/third_party/python/index.html"
      ]

    indexes: ["https://pypi.python.org/simple/"]

To (re-)generate a `pants.pex` you then run these 2 commands:

1. In your pantsbuild/pants clone, create a local pants release from master:

        :::bash
        $ rm -rf dist && ./build-support/bin/release.sh -n

2. In your own repo the following command will create a locally built `pants.pex` for all platforms:

        :::bash
        $ /tmp/pantsbuild/pants --config-override=pants-production.ini clean-all binary //:pants

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

Testing
-------

<a pantsmark="dev_run_all_tests"> </a>

### Running Tests

Pants has many tests. There are BUILD targets to run those tests. We try to keep them passing.
[A Travis-CI job](https://travis-ci.org/pantsbuild/pants) runs tests on each SHA pushed to
origin on `github.com/pantsbuild/pants`.

Most test are runnable as regular Pants test targets. To find tests that work with a particular
feature, you might explore `tests/python/pants_tests/.../BUILD`.

Before [[contributing a change to Pants|pants('src/python/pants/docs:howto_contribute')]],
make sure it passes **all** of our continuous integration (CI) tests: everything builds,
all tests pass. To try all the CI tests in a few configurations, you can run the same script
that our Travis CI does. This can take a while, but it's a good idea to run it before you
contribute a change or merge it to master:

    :::bash
    $ ./build-support/bin/ci.sh

To run just Pants' *unit* tests (skipping the can-be-slow integration tests), use the
`tests/python/pants_test:all` target:

    :::bash
    $ ./pants test tests/python/pants_test:all

If you only want to run tests for changed targets, then you can use the
`test-changed` goal:

    :::bash
    $ ./pants test-changed

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
    $ ./pants py src/python/pants/build_graph
    /Users/lhosken/workspace/pants src/python/pants/build_graph
    Python 2.6.8 (unknown, Mar  9 2014, 22:16:00)
    [GCC 4.2.1 Compatible Apple LLVM 5.0 (clang-500.0.68)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>> from pants.build_graph.target import Target
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

###JVM Tool Development Tips

If you need to debug the tool under nailgun, make
sure you run `pants goal ng-killall` or `pants goal clean-all` after you update the
jar file so that any running nailgun servers are restarted on the next invocation
of Pants.

Also, you may need to clean up some additional state when testing a tool. Some tools
cache a shaded version under `~/.cache/pants/artifact_cache/`.  Clear out the cache
before testing a new version of the tool as follows:

    :::bash
    $ rm -rf ~/.cache.pants/artifact_cache

If you have trouble resolving the file with Ivy after making the
above changes to `BUILD.tools`:

  - Make sure your url is absolute and contains three slashes (`///`) at the start
of the path.
  - If your repo has an `ivysettings.xml` file (the pants repo currently does not),
try adding a minimal `<filesystem>` resolver that doesn't enforce a pom being
present as follows:

        :::xml
        <resolvers>
          <chain name="chain-repos" returnFirst="true">
            <filesystem name="internal"></filesystem>
            ...
          </chain>
        </resolvers>

