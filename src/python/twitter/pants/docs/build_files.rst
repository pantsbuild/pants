BUILD files
===========

To tell Pants about your source code, you have files named ``BUILD`` in
directories of your source tree. These files define build-able targets
and specify source code layout. This page goes into some detail about
``BUILD`` files. If you instead wanted API docs for things defined in
``BUILD`` files (``java_library``, ``python_binary``, etc.), please see the
:doc:`BUILD Dictionary<build_dictionary>`. If you want less detail-y
information about ``BUILD`` files, :doc:`first_tutorial` is a good place
to start.

``BUILD`` files are little Python scripts with
:doc:`some useful functions<build_dictionary>`
automatically imported. Thus, function invocations look
``like(this)``, lists look ``[like, this]``, and dictionaries (hashmaps)
look ``{"like": "this"}``; Python's syntax uses
`indentation <http://en.wikipedia.org/wiki/Python_syntax_and_semantics#Indentation>`_
to indicate scope; if you copy-paste some ``BUILD`` code from one place to
another, you might need to adjust the indentation. You can
`learn more about Python <http://docs.python.org/tutorial>`_\,
but you should be able to "get along" in ``BUILD`` files if you know
functions, lists, dictionaries, and indentation.

.. _debugging:

Debugging a BUILD File
**********************

If you're curious to know how Pants interprets your ``BUILD`` file, these
goals can be especially helpful:

``list`` Did I define the targets I meant to? ::

    $ ./pants goal list src/java/com/twitter/common/examples/pingpong:
    src/java/com/twitter/common/examples/pingpong/BUILD:pingpong-lib
    src/java/com/twitter/common/examples/pingpong/BUILD:pingpong

``list ::`` List **every** target to find out:
Did a change in one ``BUILD`` file break others? ::

    $ ./pants goal list ::
      ...lots of output...
      File "twitter/pants/targets/internal.py", line 174, in dependencies
      File "twitter/pants/targets/internal.py", line 189, in _maybe_apply_deps
      File "twitter/pants/targets/internal.py", line 195, in update_dependencies
      File "twitter/pants/targets/pants_target.py", line 60, in resolve
    KeyError: 'Failed to find target for: src/python/twitter/pants/docs/BUILD:obsolete'
    $ # Instead of listing all targets, a strack trace. We found a problem

``depmap`` Do I pull in the dependencies I expect?
(JVM languages only) (This lists dependencies from your source; it doesn't catch
dependencies pulled in from 3rdparty ``.jars``)::

    $ ./pants goal depmap src/java/com/twitter/common/examples/pingpong:pingpong-lib
    internal-src.java.com.twitter.common.examples.pingpong.pingpong-lib
      internal-src.java.com.twitter.common.application.application
        internal-src.java.com.twitter.common.application.modules.applauncher
          internal-src.java.com.twitter.common.application.action
            ...more output...

``filedeps`` What source files do I depend on? ::

    $ ./pants goal filedeps src/java/com/twitter/common/examples/pingpong:pingpong-lib
    ~archie/pantsbuild/src/java/com/twitter/common/util/Stat.java
    ~archie/pantsbuild/src/java/com/twitter/common/net/http/handlers/pprof/ContentionProfileHandler.java
    ...more output...

.. _usage-default-target:

Default Target
**************

A build target with the same name as the ``BUILD`` file's containing
directory is the *default target*. To signal \"*this* is the main useful
target here" and as a convenience to users, you should always have a default.

Consider these libraries that use ``tugboat`` functionality. You can see that
this code depends on just the default ``tugboat`` target, and thus uses just core
functionality::

    # depends on plain ol' tugboat
    java_library(name='theodore',
      dependencies=[
        pants('src/java/com/twitter/tugboat'),
      ],
      sources=globs('*.java'),
    )

You can tell this code uses optional functionality because it depends on a specific
non-default target::

    # depends on optional tugboat functionality
    java_library(name='hank',
      dependencies=[
        pants('src/java/com/twitter/tugboat:hispeed'),
      ],
      sources=globs('*.java'),
    )

Default targets are more convenient to reference on the command line and less
verbose as build dependencies. For example, consider the following names for the
same target::

    src/java/com/twitter/tugboat/BUILD:tugboat  # absolute target name
    src/java/com/twitter/tugboat/BUILD          # references default target "tugboat"
    src/java/com/twitter/tugboat   # references default build file "BUILD" and default target "tugboat"
    src/java/com/twitter/tugboat/  # trailing slashes are ignored - useful for command-line completion

By providing a target with the default name, you simplify interacting with your target from the
command-line. This gives users a better experience using your library.
In BUILD files, dependencies are less verbose, which improves readability.

.. _usage-avoid-rglobs:

Avoid rglobs
************

Many pants targets have `sources`, a list of filenames owned by the target.
It's common pattern to specify source files with `globs`; it's a common
*anti-pattern*, especially in targets hastily converted from Maven poms,
to specify source files with `rglobs`, the recursive version of `globs`.

While valid, `rglobs` increases the chances of multiple targets
claiming the same sources. Consider the following refactor adding a
subpackage::

    # 'maint' subpackage has been added.
    src/java/com/twitter/tugboat/BUILD
    src/java/com/twitter/tugboat/Tugboat.java
    src/java/com/twitter/tugboat/maint/BUILD
    src/java/com/twitter/tugboat/maint/MaintenanceLog.java

    # target src/java/com/twitter/tugboat
    # Existing target now untentionally claims the 'maint' package.
    java_library(name='tugboat',
      sources=rglobs('*.java'),
    )

    # target src/java/com/twitter/tugboat/maint
    # Sources are claimed by multiple targets.
    java_library(name='maint',
      sources=globs('*.java'),
    )

Existing tugboat users now depend on tugboat's `maint` package, even though the dependency was
never intended. **Avoiding rglobs helps avoid surprises.**

Using ``rglobs`` also makes it easy to fall into making circular dependencies. You want to avoid
circular dependencies. If you later want to factor your big target into a few
focused-purpose targets, you'll have to untangle those circular dependencies.

When a target should claim files in subpackages, it's both easy and recommended to explicitly list
which subpackages should be claimed. ::

    # target src/java/com/twitter/tugboat
    # Intentionally claims the 'maint' package.
    java_library(name='tugboat',
      sources=globs(
        '*.java',
        'maint/*.java',
      ),
    )

Define Separate Targets for Interface and Implementation
********************************************************

If your code defines an API to be used by other modules, define a target
that builds just that interface.

Many programs provide a plugin interface so users can provide their own functionality. For example,
a tool might define a `DataImporter` interface and let users provide
plugins for each data source.

The simple approach of providing a single BUILD target for both interface and implementations has a
significant drawback: anyone wishing to implement the interface must depend on all dependencies
for all implementations co-published with the interface. The classpath bloats.
The risk of dependency conflicts increases greatly. For example::

    # Less than ideal layout - interface and implementations together.
    src/java/com/twitter/etl/from/BUILD
    src/java/com/twitter/etl/from/DataImporter.java
    src/java/com/twitter/etl/from/FileDataImporter.java
    src/java/com/twitter/etl/from/HBaseDataImporter.java

    # DO NOT bundle interface and implementations - forces extra dependencies.
    java_library(name='from',
      dependencies=[
        pants('3rdparty/jvm/org/apache/hbase'),
      ],
      sources=globs('*.java'),
    )

An improved code organization uses separate packages when many fellow travelers are introduced. For
example, if ``FileDataImporter.java`` only uses standard library classes its entirely appropriate to
package it with the interface. HBase, however, its quite large itself, has many transitive
dependencies, and is only required by jobs that actually read from HBase. **Implementations with
many fellow travelers should be published as separate pants targets.** ::

    # Ideal repo layout - hbase as a subpackage and separate target.
    src/java/com/twitter/etl/from/BUILD
    src/java/com/twitter/etl/from/DataImporter.java
    src/java/com/twitter/etl/from/FileDataImporter.java
    src/java/com/twitter/etl/from/hbase/BUILD
    src/java/com/twitter/etl/from/hbase/HBaseDataImporter.java

    # pants target src/java/com/twitter/etl/from
    # Including FileDataImporter is appropriate because it has no additional dependencies.
    java_library(name='from',
      dependencies=[], # no extra dependencies
      sources=globs('*.java'),
    )

    # pants target src/java/com/twitter/etl/from/hbase
    java_library(name='hbase',
      dependencies=[
        pants('3rdparty/jvm/org/apache/hbase'),
      ],
      sources=globs('*.java'),
    )

Existing code using a package for both an interface and implementations should still expose the interface separately. ::

    # Less than ideal layout - interface and implementations together.
    src/java/com/twitter/etl/from/BUILD
    src/java/com/twitter/etl/from/DataImporter.java
    src/java/com/twitter/etl/from/FileDataImporter.java
    src/java/com/twitter/etl/from/HBaseDataImporter.java

    # Default target contains interface and lightweight implementation.
    java_library(name='from',
      sources=[
        'DataImporter.java',
        'FileDataImporter.java',
      ],
    )

    # Implementation with heavyweight dependencies exposed separately.
    java_library(name='hbase',
      dependencies=[
        pants('3rdparty/jvm/org/apache/hbase'),
      ],
      sources=['HBaseDataImporter.java'],
    )

Depend on API in Library Targets, Implementation in Binary Targets
******************************************************************

Some projects helpfully publish their API separately from implementation, especially if multiple
implementations are available. SLF4J is a widely-used example.

Consider the following library target that depends on both `slf4j-api` and the specific implementation `slf4j-jdk14`. ::

    # Incorrect - forces a logging implementation on all library users.
    scala_library(name='mylib',
      dependencies=[
        pants('3rdparty:slf4j-api'),
        pants('3rdparty:slf4j-jdk14'),
      ],
    )
    
    jvm_binary(name='mybin',
      dependencies=[pants(':mylib')],
    )

Structure these dependencies to only depending on the API in library code.
Allow binary targets to specify the logging implementation of their choosing. ::

    # Better approach - only depend on API in a library target.
    scala_library(name='mylib',
      dependencies=[
        pants('3rdparty:slf4j-api'),
      ],
    )
    
    # Bring your own API implementation in the binary.
    jvm_binary(name='mybin',
      dependencies=[
        pants('3rdparty:slf4j-jdk14'),
        pants(':mylib'),
      ],
    )


Which ``BUILD`` Files are "Executed"? (and how?)
************************************************

``BUILD`` files are little Python scripts. When you
notice a target in one ``BUILD`` file can depend on a target in another
``BUILD`` file, you might think those little Python scripts are linked
together into one big Python program, but that's not exactly what's going on.
If one ``BUILD`` file has a Python variable ``x = "Hello world"`` and another
``BUILD`` file says ``print(x)``, you'll get an error: ``x`` is not defined.

Pants executes ``BUILD`` files separately. Commands in ``BUILD`` files define
targets and register those targets in a Pants data structure.

Though your repo might contain many ``BUILD`` files, Pants might not execute all
of them. If you invoke::

    ./pants goal test tests/java/com/twitter/common/examples/pingpong:pingpong

Pants executes the source tree's top-level ``BUILD`` file (executed on every Pants run) and
``tests/java/com/twitter/common/examples/pingpong/BUILD``. The ``pingpong`` target
depends on targets from other ``BUILD`` files, so Pants executes those ``BUILD``
files, too; it iterates over the dependency tree, executing ``BUILD`` files as it
goes. It does *not* execute ``BUILD`` files that don't contain targets in that
dependency tree.

If there's some ``BUILD`` code that should be executed on every run, put it in
the source tree's top-level ``BUILD`` file; that gets executed on every Pants run.


BUILD.* files
*************

We call them "``BUILD`` files" because they're usually named ``BUILD``, but
they can also be named ``BUILD.something``, where *something* is typically
a short nickname for an organization, e.g., ``BUILD.twitter``. This can be
handy if your organization has some internal definitions that you need to
combine with code that you open-source, perhaps a ``credentials`` definition
that only makes sense behind your organization's firewall.

A build target defined in ``BUILD.foo`` can't have the same ``name`` as
a build target defined in the same directory's ``BUILD`` file; they share
a namespace.
