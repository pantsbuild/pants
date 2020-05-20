Pants Developers Guide
======================

See [the new docs](https://pants.readme.io/docs/contributor-sources) for how to set up Pants to develop locally.

The rest of this page documents things that have not yet been moved to the new site.

Building Pants PEX for Production
-----------------------------------

You will usually want to use an official published version of Pants. But what if you want to
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
      entry_point='pants.bin.pants_loader:main',
      # You may want to tweak the list of supported platforms to match your environment.
      platforms=[
        'current',
        'linux-x86_64',
        'macosx-10.4-x86_64',
      ],
      # You may want to adjust the Python interpreter constraints. Note that Pants requires Python 3.6+.
      # Pex currently does not support flexible interpreter constraints (tracked by
      # https://github.com/pantsbuild/pex/issues/690), so you must choose which version to target.
      compatibility=['CPython==3.6.*'],
      dependencies=[
        ':pantsbuild.pants',
        # List any other pants backend local or remote deps here, ie:
        # ':pantsbuild.pants.contrib.go' or 'src/python/your/pants/plugin'
      ]
    )

    $ cat pants-production.toml
    [python-repos]
    # You should replace these repos with your own housing pre-built eggs or wheels for the
    # platforms you support.
    repos = [
      "https://pantsbuild.github.io/cheeseshop/third_party/python/dist/index.html",
      "https://pantsbuild.github.io/cheeseshop/third_party/python/index.html"
    ]

    indexes = ["https://pypi.org/simple/"]

To (re-)generate a `pants.pex` you then run these 2 commands:

1. In your pantsbuild/pants clone, create a local pants release from master:

        :::bash
        $ rm -rf dist && ./build-support/bin/release.sh -n

2. In your own repo the following command will create a locally built `pants.pex` for all platforms:

        :::bash
        $ /tmp/pantsbuild/pants --pants-config-files=pants-production.toml clean-all binary //:pants

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
    $ ./pants binary src/java/org/pantsbuild/tools/jar:main

The above command will create `dist/jar-tool.jar` according to the _jvm_binary_
target defined in `src/java/org/pantsbuild/tools/jar/BUILD`


You'll need to update the jar dependency that this tool uses for Pants to see the
development version.  See
<a pantsref="test_3rdparty_jvm_snapshot">Using a SNAPSHOT JVM Dependency</a>
which describes how to specify the `url` and `mutable` attributes of a `jar`
dependency found on the local filesystem:

    :::python
    jar_library(name='jar-tool',
        jars=[
          jar(org='org.pantsbuild', name='jar-tool', rev='1.2.3-SNAPSHOT',
              url='file:///Users/squarepants/Src/pants/dist/jar-tool.jar', mutable=True),
      ],
    )

For debugging, append JVM args to turn on the debugger for the appropriate tool in
`pants.toml`:

    :::toml
    [jar-tool]
    jvm_options = ["-Xdebug", "-Xrunjdwp:transport=dt_socket,server=y,suspend=y,address=5005"]

Note that most tools run under nailgun by default. The easiest way to
debug them is to disable nailgun by specifying the command line option
`--execution-strategy=subprocess` or setting `execution_strategy = "subprocess"` in the specific tool
section or in the `[DEFAULT]` section of `pants.toml`.

    :::toml
    [DEFAULT]
    execution_strategy = "subprocess"

### JVM Tool Development Tips

If you need to debug the tool under nailgun, make
sure you run `pants goal ng-killall` or `pants goal clean-all` after you update the
jar file so that any running nailgun servers are restarted on the next invocation
of Pants.

Also, you may need to clean up some additional state when testing a tool. Some tools
cache a shaded version under `~/.cache/pants/artifact_cache/`.  Clear out the cache
before testing a new version of the tool as follows:

    :::bash
    $ rm -rf ~/.cache/pants/artifact_cache

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
