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

    $ ./pants goal list examples/src/com/pants/examples/hello/greet
    examples/src/com/pants/examples/hello/greet:greet

``list ::`` List **every** target to find out:
Did a change in one ``BUILD`` file break others? ::

    $ ./pants goal list ::
      ...lots of output...
      File "pants/targets/internal.py", line 174, in dependencies
      File "pants/targets/internal.py", line 189, in _maybe_apply_deps
      File "pants/targets/internal.py", line 195, in update_dependencies
      File "pants/targets/pants_target.py", line 60, in resolve
    KeyError: 'Failed to find target for: src/python/pants/docs/BUILD:obsolete'
    $ # Instead of listing all targets, a strack trace. We found a problem

``depmap`` Do I pull in the dependencies I expect?
(JVM languages only) This lists dependencies from your source; it doesn't catch
dependencies pulled in from 3rdparty ``.jars``. For example, here it shows
that ``main-bin`` depends on the 3rdparty ``log4j`` jar, but not that
``log4j`` depends on ``javax.mail``::

    $ ./pants goal depmap examples/src/com/pants/examples/hello/main
    internal-src.java.com.pants.examples.hello.main.main
      internal-src.java.com.pants.examples.hello.main.main-bin
        internal-src.java.com.pants.examples.hello.greet.greet
        log4j-log4j-1.2.15

``filedeps`` What source files do I depend on? ::

    $ ./pants goal filedeps examples/src/com/pants/examples/hello/main
    ~archie/workspace/pants/examples/src/com/pants/examples/hello/greet/BUILD
    ~archie/workspace/pants/examples/src/com/pants/examples/hello/greet/Greeting.java
    ~archie/workspace/pants/examples/src/com/pants/examples/hello/main/BUILD
    ~archie/workspace/pants/examples/src/com/pants/examples/hello/main/config/log4j.properties
    ~archie/workspace/pants/examples/src/com/pants/examples/hello/main/HelloMain.java

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
        'src/java/com/twitter/tugboat',
      ],
      sources=globs('*.java'),
    )

You can tell this code uses optional functionality because it depends on a specific
non-default target::

    # depends on optional tugboat functionality
    java_library(name='hank',
      dependencies=[
        'src/java/com/twitter/tugboat:hispeed',
      ],
      sources=globs('*.java'),
    )

Default targets are more convenient to reference on the command line and less
verbose as build dependencies. For example, consider the following names for the
same target::

    src/java/com/twitter/tugboat:tugboat  # absolute target name
    src/java/com/twitter/tugboat/BUILD          # references default target "tugboat"
    src/java/com/twitter/tugboat   # references default build file "BUILD" and default target "tugboat"
    src/java/com/twitter/tugboat/  # trailing slashes are ignored - useful for command-line completion

By providing a target with the default name, you simplify interacting with your target from the
command-line. This gives users a better experience using your library.
In BUILD files, dependencies are less verbose, which improves readability.

The 1:1:1 Rule
**************

Your code's organization, including ``BUILD`` target configuration, makes
building easier or harder. Some folks summarize clear and scalable code
layout choice
with the **1:1:1** rule of thumb:

* **1 Folder**
* **1 Package**
* **1 BUILD Target**

If there's a set of code that usually goes together, it makes sense for it to
be in one folder using one package namespace.
The folder should have a ``BUILD`` file with one target to build that set of
code.

If there's a subset of code that *doesn't* usually go together with the rest
of the code in some directory/target, it makes sense to move that code out
into another folder and its own package namespace.
The new folder should have its own ``BUILD`` file containing a target to build
that code.

Code belongs at the "leaves" of your directory tree. E.g., if
``.../foo/Foo.java`` exists, you don't want to create ``.../foo/bar/Bar.java``
in a subdirectory. (Or if you do, then you want to move the other foo
code to ``../foo/justfoonotbar/Foo.java`` or somesuch.) This keeps all the code
for a package in 1 Folder, 1 BUILD target.

**1:1:1**  is a "rule of thumb", not a law.
If your code breaks this rule, it will still build.
**1:1:1** tends to make your code easier to work with.

If you're new to Pants, you might feel overwhelmed by all these ``BUILD``
files; you might think it's simpler to have fewer of them: maybe just one
``BUILD`` file in the "top folder" for a project that builds code from
several directories. But this "target coarseness" can waste your time:
you have a huge target that depends on everything that your source depends on.
If you divide your code into smaller, coherent targets, each of those targets
has only a subset of those dependencies.


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
        '3rdparty/jvm/org/apache/hbase',
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
        '3rdparty/jvm/org/apache/hbase',
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
        '3rdparty/jvm/org/apache/hbase',
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
        '3rdparty:slf4j-api',
        '3rdparty:slf4j-jdk14',
      ],
    )

    jvm_binary(name='mybin',
      dependencies=[':mylib'],
    )

Structure these dependencies to only depending on the API in library code.
Allow binary targets to specify the logging implementation of their choosing. ::

    # Better approach - only depend on API in a library target.
    scala_library(name='mylib',
      dependencies=[
        '3rdparty:slf4j-api',
      ],
    )

    # Bring your own API implementation in the binary.
    jvm_binary(name='mybin',
      dependencies=[
        '3rdparty:slf4j-jdk14',
        ':mylib',
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

    ./pants goal test examples/tests/java/com/pants/examples/hello/greet:greet

Pants executes the source tree's top-level ``BUILD`` file (executed on every Pants run) and
``examples/tests/java/com/pants/examples/hello/greet/BUILD``. The ``greet`` target
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

.. _howto_check_exclusives:

Tag Incompatibilities with exclusives
*************************************

A big code workspace might contain some parts that aren't compatible
with each other. To make sure that no target tries to use targets
that don't work together, you can tag those targets with ``exclusives``.

For example, suppose that we had two java targets, jliba and jlibb. jliba uses
``slf4j``, which includes in its jar package an implementation of ``log4j``. jlibb uses
``log4j`` directly. But the version of log4j that's packaged inside of ``slf4j`` is
different from the version used by jlibb. ::

   java_library(name='jliba',
     dependencies = ['3rdparty/jvm/org/slf4j:slf4j-with-log4j-2.4'])
   java_library(name='jlibb',
     dependencies=['3rdparty/jvm/log4j:log4j-1.9'])
   java_binary(name='javabin', dependencies=[':jliba', ':jlibb'])

In this case, the binary target ``javabin`` depends on both ``slf4j`` with its
packaged ``log4j`` version 2.4, and on ``log4j-1.9``.
Pants doesn't know that the slf4j and log4j ``jar_dependencies`` contain
incompatible versions of the same library, and so it can't detect the error.

With exclusives, the ``jar_library`` target for the joda libraries would declare
exclusives tags: ::

   jar_library(name='slf4j-with-log4j-2.4', exclusives={'log4j': '2.4'}, jars=[...])
   jar_library(name='joda-2.1', exclusives={'log4j': '1.9'}, jars=[...])

With the exclusives declared, pants can recognize that 'javabin' has conflicting
dependencies, and can generate an appropriate error message.

.. _usage-pants-wrapper-gone:

What happened to the pants() wrapper around targets?
****************************************************

If you have an existing project using Pants and have recently upgraded, you may encounter
this warning ::

   *** pants() wrapper is obsolete and will be removed in a future release.

or the BUILD may fail an error. ::

   NameError: name 'pants' is not defined

In pre-release versions of Pants, targets declared in the ``dependencies`` attribute had
to be wrapped in a call to the ``pants()`` method. ::

   java_library(name='foo',
       dependencies=[pants('bar')])

The ``pants()`` method has since been replaced with a noop and as of Pants 0.0.24 is
officially deprecated.  The above snippet should be re-written to use the target as a plain
string. ::

   java_library(name='foo',
       dependencies=['bar'])

You can use ``sed`` or a similar utility to quickly remove these references
from your BUILD files with a regular expression. ::

   # Run this command from the root of your repo.
   sed -i "" -e 's/pants(\([^)]*\))/\1/g' `find . -name "BUILD*"`


Using an older version of Pants?
********************************

If you are following along in these examples and are using a version of pants prior to the 2014 open source release you might see one of
the following messages:

From a ``python_*`` target dependencies attribute: ::

   AttributeError: 'str' object has no attribute 'resolve'

From a ``java_library`` dependencies attribute: ::

   The following targets could not be loaded:
     src/java/com/twitter/foo/bar/baz =>
       TargetDefinitionException: Error with src/java/com/foo/bar/baz/BUILD:baz:
          Expected elements of list to be (<class 'twitter.pants.targets.external_dependency.ExternalDependency'>, <class 'twitter.pants.targets.anonymous.AnonymousDeps'>,
            <class 'twitter.pants.base.target.Target'>), got value 3rdparty:guava of type <type 'str'>

From a ``java_library`` resources attribute: ::


   IOError: [Errno 2] No such file or directory: '/Users/pantsaddict/workspace/src/resources/com/foo/bar'

From a ``junit_tests`` resources attribute: ::

   ValueError: Expected elements of list to be <class 'twitter.pants.base.target.Target'>, got value tests/scala/foo/bar/baz/resources of type <type 'str'>

From a ``provides`` repo attribute: ::

   ValueError: repo must be Repository or Pants but was foo/bar/baz:baz

All of these errors likely mean  that you need to wrap the strings mentioned in the error message with the ``pants()`` wrapper
function in your BUILD files.  The open source Pants release deprecated the use of this wrapper and thus examples in this
documentation don't include it.  For more information, see the :ref:`pants wrapper <usage-pants-wrapper-gone>` notes above.
