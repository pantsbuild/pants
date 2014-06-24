#######################
JVM Projects with Pants
#######################

Assuming you know the :doc:`basic Pants concepts <first_concepts>` and have
gone through the :doc:`first_tutorial`, you've made a great start towards
using Pants to work with Java and Scala code. This page goes into some of
the details.

If you are accustomed to the Maven tool and contemplating moving to Pants,
you are not alone; :doc:`from_maven` has some advice.

**************************
Relevant Goals and Targets
**************************

When working with JVM languages, the following goals and targets are
especially relevant.

**Deployable Bundle** *Runnable Binary, optionally with non-JVM files*

  Deployable bundles are directories, optionally archived, that contain
  all files necessary to run the application. The ``bundle`` goal is
  used to create these deployable bundles from either ``jvm_binary``
  or ``jvm_app`` targets.

  Bundling a ``jvm_binary`` target is appropriate when your application
  is entirely jar-based; that is, it's entirely class files and resources
  packaged inside the jars themselves. If your application requires
  "extra stuff" (e.g.: start scripts, config files) use a ``jvm_app``
  which allows you to include files in the bundle directory that
  supplement the binary jar and its dependencies.
  You can learn :ref:`more about bundles <jvm_bundles>`.

**Runnable Binary**

  On its own, a ``jvm_binary`` BUILD target describes an executable ``.jar``
  (something you can run with ``java -jar``). The jar is described as
  executable because it contains a manifest file that specifies the main
  class as well as classpath for all dependencies. If your program
  contains only jars (and resources packaged in those jars), this is
  all you need to run the binary. Use ``./pants goal binary`` to
  compile its code; ``./pants goal run`` to run it "in place".

**Importable Code**

  ``java_library`` BUILD targets make Java source code ``import``\-able. The
  rule of thumb is that each directory of ``.java`` files has a ``BUILD`` file
  with a ``java_library`` target. A JVM target that has a ``java_library`` in
  its ``dependencies`` can import its code. ``scala_library`` targets are
  similar, but compiled with Scala.

  To use pre-built ``.jar``\s, a JVM target can depend on a ``jar``, a
  reference to published code; these ``jar``\s normally live in a
  :doc:`directory called 3rdparty <3rdparty>`.

  Pants can ``publish`` a JVM library so code in other repos can use it;
  if the ``*_library`` target has a ``provides`` parameter, that specifies
  the repo/address at which to :doc:`publish <publish>`.

  An ``annotation_processor`` BUILD target defines a Java library
  one containing one or more annotation processors.

**Tests**

  A ``junit_tests`` BUILD target holds source code for some JUnit tests;
  typically, it would have one or more ``java_library`` targets as dependencies
  and would import and test their code.

  A ``scala_specs`` target is similar, but has source code for Scala specs.

  The Pants ``test`` goal runs tests.

**Generated Code**

  A ``java_thrift_library`` generates Java code from ``.thrift`` source; a JVM
  target that has this target in its ``dependencies`` can ``import`` the
  generated Java code. A ``java_protobuf_library`` is similar, but generates
  Java code from protobuffer source. A ``jaxb_library`` definition generates
  code to read and write XML using an XML schema (.xsd files).

*************************
BUILD for a Simple Binary
*************************

The `Pants Build Java hello world sample
<https://github.com/pantsbuild/pants/tree/master/src/java/com/pants/examples/hello>`_
code shows the BUILD file for a simple Java binary (in the ``main/`` directory):

.. literalinclude:: ../../../java/com/pants/examples/hello/main/BUILD
   :start-after: runnable
   :end-before: README page

This small program has just two dependencies. One is a library, a
``java_library``, a compiled set of source code from this workspace.
The other is a "third party" dependency, a pre-compiled artifact
whose source lives somewhere outside the workspace.

Depending on a Library
======================

The rule of thumb is that
each directory of ``.java`` or ``.scala`` files has a library target. If you
find
yourself thinking "we should move some of this code to another directory,"
you probably also want to set up a ``BUILD` file with a ``java_library``
(or ``scala_library``) target. Here we see the library target which
``main-bin`` depends on. This library target lives in ``hello/greet/BUILD``:

.. literalinclude:: ../../../java/com/pants/examples/hello/greet/BUILD
   :start-after: LICENSE

This library could depend on other build targets and artifacts;
if your code imports
something, that implies a ``BUILD`` dependency.

A Test Target
=============

The `Pants Java Hello World example tests
<https://github.com/pantsbuild/pants/tree/master/tests/java/com/pants/examples/hello>`_
are normal JUnit tests. To run them with Pants, we
need a target for them:

.. literalinclude:: ../../../../tests/java/com/pants/examples/hello/greet/BUILD
   :start-after: Test the

As with other targets, this one depends on code that it imports. Thus, a typical
test target depends on the library that it tests.

Depending on a Jar
==================

The test example depends on a jar, ``junit``. Instead of compiling
from source, Pants invokes `ivy` to fetch such jars. To reduce the danger
of version conflicts, we use the :doc:`3rdparty` idiom: we keep references
to these "third-party" jars together in ``BUILD`` files under the
``3rdparty/`` directory. Thus, the test has a ``3rdparty:`` dependency:

.. literalinclude:: ../../../../tests/java/com/pants/examples/hello/greet/BUILD
   :start-after: Test the

The ``BUILD`` files in ``3rdparty/`` have targets like::

    jar_library(name='junit',
                jars = [
                  jar(org='junit', name='junit-dep', rev='4.11').with_sources(),
                ],
                dependencies = [
                  pants(':hamcrest-core'),
                ],
               )

Those :ref:`jar() things <bdict_jar>` are references to public jars.

***********************
The Usual Commands: JVM
***********************

**Make sure code compiles and tests pass:**
  Use the ``test`` goal with the targets you're interested in. If they are
  test targets, Pants runs the tests. If they aren't test targets, Pants will
  still compile them since it knows it must compile before it can test.

  ``./pants goal test src/java/com/pants/examples/hello/:: tests/java/com/pants/examples/hello/::``

  Output from the test run is written to ``.pants.d/test/junit/``; you
  can see it on the console with ``--no-test-junit-suppress-output``.

  **Run just that one troublesome test class:** (assuming a JUnit test; other
  frameworks use other flags)

  ``./pants goal test tests/java/com/pants/examples/hello/:: --test-junit-test=com.pants.examples.hello.greet.GreetingTest``

**Packaging Binaries**
  To create a jar containing just the code built by a JVM target, use the
  `jar` goal::

      ./pants goal jar src/java/com/pants/examples/hello/greet

  To create :ref:`bundle <jvm_bundles>` (a runnable thing and its
  dependencies, perhaps including helper files)::

      ./pants goal bundle src/java/com/pants/examples/hello/main --bundle-archive=zip

  If your bundle is JVM, it's a zipfile which can run by means of an
  ``unzip`` and setting your ``CLASSPATH`` to ``$BASEDIR/my_service.jar``
  (where ``$BASEDIR is`` the directory you've just unzipped).

**Get Help**

  Get basic help::

      ./pants goal help

  Get a list of goals::

      ./pants goal goals

  Get help for one goal::

      ./pants goal help onegoal

*********
Toolchain
*********

Pants uses `Ivy <http://ant.apache.org/ivy/>`_ to resolve ``jar`` dependencies.
To change how Pants resolves these, use ``--ivy-*`` command-line
parameters along with ``--resolve-*`` parameters.

Pants uses `Nailgun <https://github.com/martylamb/nailgun>`_ to speed up
compiles. It's a JVM daemon that runs in the background; this saves time
for JVM startup and class loading.

.. TODO this is a good place to mention goal ng-killall, but I don't want**
   folks doing it willy-nilly. Would be good to prefix the mention with**
   something saying symptoms when you'd want to.

Pants uses Jmake, a dependency tracking compiler facade.

**************************
Java7 vs Java6, Which Java
**************************

Pants uses the java on your ``PATH`` (not ``JAVA_HOME``).
To specify a specific java version for just one pants invocation::

    PATH=/usr/lib/jvm/java-1.7.0-openjdk7/bin:${PATH} ./pants goal ...

If you sometimes need to compile some code in Java 6 and sometimes Java 7,
you can use a command-line arg to specify Java version::

    --compile-javac-args='-target 7 -source 7'

*BUT* beware: if you switch between Java versions, Pants doesn't realize when
it needs to rebuild. If you build with version 7, change some code, then build
with version 6, java 6 will try to understand java 7-generated classfiles
and fail. Thus, if you've been building with one Java version and are switching
to another, you probably need to::

    ./pants goal clean-all

so that the next build starts from scratch.

.. _jvm_bundles:

****************************************
Bundles: Deploy-able Runnable File Trees
****************************************

You can enjoy your web service on your development machine's ``localhost``,
but to let other people enjoy it, you probably want to copy it to a server
machine. With Pants, the easiest way to do this is to create a *bundle*: a
directory tree of ``.jar`` and helper files.

Our "hello world" sample application needs a configuration file to run
correctly. (You can try to run without the configuration file, but the
program crashes immediately.) We define a ``jvm_app`` that represents
a runnable binary and "bundles" of extra files:

.. literalinclude:: ../../../java/com/pants/examples/hello/main/BUILD
   :start-after: Like Hello World
   :end-before: The binary

Here, we keep the extra files in a subdirectory, ``config/`` so that
they don't clutter up this directory. (In this simple example, there's
just one file, so there isn't actually much clutter.) By using the
:ref:`bdict_bundle`\'s ``relative_to`` parameter, we "strip off" that
subdirectory; in the generated bundle, these extra files will be in
the top directory.

(If you want to set up a tree of static files but don't need it to be runnable,
you can define a ``jvm_app`` target with bundles (and/or resources) but whose
``jvm_binary`` has no source or main; the resulting bundle will have
the files you want (along with a couple of not-so-useful stub ``.jar`` files).)

**Generating a Bundle**

Invoke ``./pants goal bundle`` on a JVM app or JVM binary target::

  ./pants goal bundle src/java/com/pants/examples/hello/main:main

**Contents of a Bundle**

The generated bundle is basically a directory tree containing ``.jar``\s and
extra files. The ``.jar`` in the top-level directory has a manifest
so you can run it with ``java -jar``::

    $ cd dist/main-bundle/
    $ java -jar main-bin.jar
    16:52:11 INFO : Hello, world!

The "bundle" is basically a tree of files::

    $ cd dist/main-bundle/
    $ find .
    .
    ./libs
    ./libs/javax.activation-activation-1.1.jar
    ./libs/javax.mail-mail-1.4.jar
    ./libs/log4j-log4j-1.2.15.jar
    ./log4j.properties
    ./main-bin.jar
    $ jar -tf main-bin.jar
    com/
    com/pants/
    com/pants/examples/
    com/pants/examples/hello/
    com/pants/examples/hello/greet/
    com/pants/examples/hello/greet/Greeting.class
    com/pants/examples/hello/main/
    com/pants/examples/hello/main/HelloMain.class
    META-INF/
    META-INF/MANIFEST.MF

That ``log4j.properties`` file came from the ``bundles=`` parameter.
The ``libs/`` directory contains 3rdparty jars.
The jar in the top directory contains code compiled for this target.

**Deploying a Bundle**

Instead of just creating a directory tree, you can pass
``--bundle-archive`` to ``./pants goal bundle`` to generate
an archive file (a zipped tarfile or some other format) instead.
You can copy the archive somewhere, then unpack it on
the destination machine. If there are some "standard jars" that are
already on the destination machine, you might want to exclude them
from the archive.

.. toctree::
   :maxdepth: 1

   from_maven
