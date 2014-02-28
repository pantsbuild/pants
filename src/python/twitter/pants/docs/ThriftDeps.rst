####################################
Using Pants with Thrift Dependencies
####################################

`Apache Thrift <http://thrift.apache.org/>`_ is a popular framework for working with
data types and service interfaces. It uses an Interface Definition Language (IDL) to
define these types and interfaces. There are tools to generate code in "real" programming
languages from Thrift IDL files. Two programs, perhaps in different
programming languages, should be able to communicate over Thrift interfaces by using
this generated code.

Pants knows Thrift. For each Thrift file you use, your codebase has some ``BUILD`` targets
that represent "real" code generated from IDL code. You can write code in your favorite
language that imports the generated code. To make the import work, your code's
``BUILD`` target depends on the appropriate Thrift ``BUILD`` target.

***************
Generating Code
***************

You have some Thrift; you want to use it from your "regular" programming
language. Normally, to make, e.g., Java code usable, you set up a
``java_library`` target with sources ``*.java`` and then depend
on that target; Thrift works similarly, but you use a different target
type that generates Java code from ``*.thrift``.
You can define Java, Python, or Scala library targets whose code is
Thrift-generated
by setting up *lang*\_thrift_library targets. (Scala is tricky; you
use a ``java_thrift_library`` with carefully-chosen parameters.)
Other targets can depend
on a *lang*\_thrift_library and their code can then import the generated code.

Target Example
==============

This example sets up a ``java_thrift_library`` target; its source
is Thrift; it generates Java. ::

    # Target defined in src/thrift/com/twitter/mybird/BUILD:
    java_thrift_library(name='mybird',
      # Specify dependencies for thrift IDL file includes.
      dependencies=[
        pants('src/thrift/com/twitter/otherbird'),
      ],
      sources=globs('*.thrift')
    )

Pants knows that before it compiles such a target, it must first generate Java
code from the Thrift IDL files. Users can
depend on this target like any other internal target. In this case, users would
add a dependency on ``pants('src/thrift/com/twitter/mybird')``.

One *lang*\_thrift_library can depend on another; use this if one of your
Thrift files ``include``\s a Thrift file that lives in another target.

Configuring
===========

Here are some popular ``*_thrift_library`` configurations:

**Java**

Use Apache Thrift compiler (the default)::

    java_thrift_library(...)

...or Scrooge::

    java_thrift_library(
      compiler='scrooge')

**Python** ::

    python_thrift_library(...)

**Scala** ::

    java_thrift_library(  # Yes, a "java" library to generate Scala
      compiler='scrooge', # default compiler does not gen Scala; Scrooge does
      language='scala',
      # maybe set an rpc_style
    )


******************************
Thrift Client & Server Example
******************************

Enough theoretical mumbo jumbo - let's build a thrift client & server with
pants! While the example is written in Java these same concepts apply to
other languages.

Thrift IDL
==========

Since we're writing a thrift service, let's start by defining the service
interface. As pants is our build tool we'll also define a ``BUILD`` file
with a target owning the sources. We define our thrift service in
``src/thrift/com/twitter/common/examples/pingpong/pingpong.thrift``.

.. include:: ../../../../../src/thrift/com/twitter/common/examples/pingpong/pingpong.thrift
  :code:

And a target owning the sources in
``src/thrift/com/twitter/common/examples/pingpong/BUILD``.

.. include:: ../../../../../src/thrift/com/twitter/common/examples/pingpong/BUILD
  :code:

Notice the target type is :ref:`bdict_java_thrift_library`, and this target
staked its claim to our pingpong thrift IDL file. JVM library targets
(e.g.: :ref:`bdict_java_library`, :ref:`bdict_scala_library`) that depend on
this target will simply see generated code from the IDL. Since no additional
options are specified we use the defaults; however, if we need more
control over how code is generated we control that through arguments provided
by :ref:`bdict_java_thrift_library`.

.. NOTE::
   While the name ``java_thrift_library`` might make you think it generates
   Java, it can also generate other target languages via
   the ``language`` parameter (scala for example). For Python code, however,
   use :ref:`bdict_python_thrift_library`.

.. TODO(travis): How to specify the repo thrift gen defaults?
.. TODO(travis): Maybe we should show generating Java and Scala code?

So we can focus on the build itself, bare-bones thrift client & server code
are provided for this example. For details about writing thrift services,
see the `Apache Thrift site <http://thrift.apache.org/>`_.

Thrift Server
=============

Let's examine ``src/java/com/twitter/common/examples/pingpong_thrift/server/BUILD``
to understand how the server consumes thrift.

.. include:: ../../../../../src/java/com/twitter/common/examples/pingpong_thrift/server/BUILD
  :code:

Notice how two targets are defined for this server.
A :ref:`bdict_java_library` has been defined to own the server source code.
Since the server has dependencies those are defined too. Notice how the server
depends on both java and thrift. As a consumer we simply depend on targets
that provide things we need and pants figures out the rest.

A :ref:`bdict_jvm_binary` has also been defined, turning our library into
something runnable. For example, a ``server-bin`` bundle would contain a
jar with a manifest file specifying the main class and dependency classpath.
We can simply start the server locally with: ::

    ./pants goal run src/java/com/twitter/common/examples/pingpong_thrift/server:server-bin

If you find this interesting but really just care about implementing thrift
server in Scala or Python, very little changes. For Scala, your
:ref:`bdict_scala_library` would simply depend on the target that owns
your thrift IDL sources. Same with Python, but using
:ref:`bdict_python_library`. The key thing to remember is depending on thrift
is the same as any other dependency. By the time the thrift dependency is
used the IDL has already been converted into plain old source code.

Thrift Client
=============

Now that we have the server, let's build the client. The client lives in a
separate package with its own BUILD file
``src/java/com/twitter/common/examples/pingpong_thrift/client/BUILD``.

.. include:: ../../../../../src/java/com/twitter/common/examples/pingpong_thrift/client/BUILD
  :code:

Again we see two targets, a :ref:`bdict_java_library` that owns sources and
defines dependencies, and a :ref:`bdict_jvm_binary` to simplify running the
client. We can run the client locally with: ::

    ./pants goal run src/java/com/twitter/common/examples/pingpong_thrift/client:client-bin

.. _thriftdeps_publish:

**********
Publishing
**********

Publishing a *lang*\_thrift_library is like
:doc:`publishing a "regular" library <publish>`.
The targets use ``provides`` parameters. It might look something like::

  java_thrift_library(name='eureka-java',
    sources=['eureka.thrift'],
    dependencies=[
      pants('src/thrift/org/archimedes/volume:volume-java'),
    ],
    language='java',
    provides=artifact(
      org='org.archimedes',
      name='eureka-java',
      repo=pants('BUILD.archimedes:jar-public'),
  ))

  java_thrift_library(name='eureka-scala',
    sources=['eureka.thrift'],
    dependencies=[
      pants('src/thrift/org/archimedes/volume:volume-scala'),
    ],
    compiler='scrooge',
    language='scala',
    provides=artifact(
      org='org.archimedes',
      name='eureka-scala',
      repo=pants('BUILD.archimedes:jar-public'),
    ))
