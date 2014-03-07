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
  is entirely jar-based; that is, its entirely class files and resources
  packaged inside the jars themselves. If you application requires
  "extra stuff" (e.g.: start scripts, config files) use a ``jvm_app``
  which allows you to include files in the bundle directory that are
  supplemental to the binary jar and its dependencies.
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

  ``java_library`` BUILD targets make Java source code ``import``\able. The
  rule of thumb is that each directory of ``.java`` files has a ``BUILD`` file
  with a ``java_library`` target. A JVM target that has a ``java_library`` in
  its ``dependencies`` can import its code. ``scala_library`` targets are
  similar, but compiled with Scala.

  To use pre-built ``.jar``\s, a JVM target can depend on a ``jar``, a
  reference to published code; these ``jar``\s normally live in a
  :doc:`directory called 3rdparty <3rdparty>`.

  Pants can ``publish`` a JVM library so code in other repos can use it;
  if the ``*_library`` target has a ``provides`` parameter, that specifies
  the repo/address at which to publish.

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
  Java code from protobuffer source.

*************************
BUILD for a Simple Binary
*************************

The `Twitter Commons Java pingpong sample
<https://github.com/twitter/commons/tree/master/src/java/com/twitter/common/examples/pingpong>`_
code shows the BUILD file for a simple Java binary (in the ``main/`` directory):

.. literalinclude:: ../../../../java/com/twitter/common/examples/pingpong/main/BUILD
   :start-after: under the License.

This small program has just one library, a `java_library`.
The rule of thumb is that
each directory of ``.java`` or ``.scala`` files has a library target. If you
find
yourself thinking "we should move some of this code to another directory,"
you probably also want to set up a ``BUILD` file with a ``java_library``
(or ``scala_library``) target.

.. literalinclude:: ../../../../java/com/twitter/common/examples/pingpong/handler/BUILD
   :start-after: java_library:

This library depends on other build targets and jars; if your code imports
something, that implies a ``BUILD`` dependency.
Some of the depended-upon targets come from the same repository; for example
``.../common/application``. If we peeked at that ``BUILD`` target, we'd see it
was another ``java_library``.
Some of these dependencies are ``jar``\ s built elsewhere.

Depending on a Jar
==================

The `pingpong-lib` example depends on some jars. Instead of compiling
from source, Pants invokes `ivy` to fetch these jars. To reduce danger
of version conflicts, we use the :doc:`3rdparty` idiom: we keep references
to these "third-party" jars together in ``BUILD`` files under the
``3rdparty/jvm/`` directory. Thus, ``pingpong-lib`` has some dependencies like:

.. literalinclude:: ../../../../java/com/twitter/common/examples/pingpong/handler/BUILD
   :start-after: java_library:
   :end-before: src/java

The ``BUILD`` files in ``3rdparty/jvm/``, e.g.,
``3rdparty/jvm/com/sun/jersey/BUILD``, have targets like:

.. literalinclude:: ../../../../../3rdparty/jvm/com/sun/jersey/BUILD
   :lines: 3-4

Those :ref:`jar() things <bdict_jar>` are references to public jars.

***********************
The Usual Commands: JVM
***********************

**Make sure code compiles and tests pass:**
  Use the ``test`` goal with the targets you're interested in. If they are
  test targets, Pants runs the tests. If they aren't test targets, Pants will
  still compile them since it knows it must compile before it can test.

  ``pants goal test src/java/com/myorg/myproject tests/java/com/myorg/myproject``

  **Run just those two troublesome tests:** (assuming they're JUnit tests; other
  frameworks use other flags)

  ``pants goal test tests/java/com/myorg/myproject --test-junit-test=com.myorg.myproject.HarshTest --test-junit-test=com.myorg.myproject.HarsherTest``

**Packaging Binaries**
  To create a jar containing just the code built by a JVM target, use the
  `jar` goal::

      pants goal jar src/java/com/myorg/myproject

  To create "bundle" (a runnable thing and its dependencies)::

      ./pants goal bundle src/main/java/yourproject --bundle-archive=zip -v

  If your bundle is JVM, it's a zipfile which can run by means of an
  ``unzip`` and seting your ``CLASSPATH`` to ``$BASEDIR/my_service.jar``
  (where ``$BASEDIR is`` the directory you've just unzipped).

**Get Help**
  Get the list of goals::

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
directory tree of ``.jar`` and helper files. If your ``jvm_app`` has
a ``bundles`` paramater, it can specify trees of files to include in the tree.

**Generating a Bundle**

Invoke ``./pants goal bundle`` on a JVM app or JVM binary target.

**Contents of a Bundle**

A bundle is basically a directory tree containing ``.jar``\s. The
``.jar`` in the top-level directory has a manifest so you can run
it with ``java -jar``::

    $ find .
    pingpong.jar
    libs/
    libs/org.scala-lang-scala-library-2.9.2.jar
    libs/org.sonatype.sisu.inject-cglib-2.2.1-v20090111.jar
    libs/pingpong.jar
    libs/src.java.com.twitter.common.examples.pingpong.pingpong-lib.jar
    libs/...

If your ``jvm_app`` has a ``bundles`` parameter, this might specify
directories of files to copy into the generated bundle. E.g., your
``jvm_app``` might have a ``bundles`` like ::

    bundles = [ bundle().add(rglobs('tools/config/*')), ]

In this case, you'd expect files from this directory to show up in
the bundle::

    tools/config/
    tools/config/launcher.scala
    tools/config/...

**Deploying a Bundle**

Instead of just creating a directory tree, you can pass
``--bundle-archive`` to ``.pants goal bundle`` to generate
an archive file (a zipped tarfile or some other format) instead.
You can copy the archive somewhere, then unpack it on
the destination machine. If there are some "standard jars" that are
already on the destination machine, you might want to exclude them
from the archive.

.. toctree::
   :maxdepth: 1

   from_maven

