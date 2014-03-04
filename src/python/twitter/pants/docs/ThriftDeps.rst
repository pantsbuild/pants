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


**************
Thrift Example
**************

Let's look at some sample code that puts all of this together.

* Thrift IDL code (``.thrift`` files)
* ``BUILD`` targets for the Thrift IDL code
* Java code that ``import``\s code generated from Thrift
* ``BUILD`` target dependencies that allow that ``import``


Thrift IDL
==========

Our example uses two Thrift files, one of which ``include``\s the other.
They look pretty ordinary. The include-d Thrift,
``src/thrift/com/twitter/common/examples/distance/distance.thrift``,
is regular Thrift (albeit with a ``#namespace`` comment used for Thrift
that will be compiled with both Apache Thrift and Scrooge):

.. include:: ../../../../../src/thrift/com/twitter/common/examples/distance/distance.thrift
   :code:

The include-ing Thrift,
``src/thrift/com/twitter/common/examples/precipitation/precipitation.thrift``,
also looks ordinary. (The include path is a little tricky: it's based on
source roots. Thus, if your source tree has more than one root
``foo`` and ``bar`` and has Thrift in both, code in foo can ``include``
code from ``bar`` without mentioning ``bar`` in the include path.
Since twitter/commons has just one source root, this trickiness doesn't
arise in our example.):

.. include:: ../../../../../src/thrift/com/twitter/common/examples/precipitation/precipitation.thrift
   :code:

BUILD Targets
=============

In a ``BUILD`` file, we use a ``java_thrift_library`` or
``python_thrift_library`` to generate "real" code from Thrift.
Our example just uses Java;
thus, the ``BUILD`` file for ``distance.thrift`` looks like

.. include:: ../../../../../src/thrift/com/twitter/common/examples/distance/BUILD
   :code: python
   :start-after: cd ../precipitation)

Notice the target type is :ref:`bdict_java_thrift_library`, and this target
staked its claim to our distance thrift IDL file. JVM library targets
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

As with "regular" languages, for one target's code to include another's,
a target should have the other in its ``dependencies``. Thus, to allow
``precipitation.thrift`` to depend on ``distance.thrift``, we set up
``.../precipitation/BUILD`` like so:

.. include:: ../../../../../src/thrift/com/twitter/common/examples/precipitation/BUILD
   :code: python
   :start-after: includes other thrift

Using in "Regular" Code
=======================

We want to use the Thrift-generated interface from "regular" code. In this Java
example, we want to ``import`` the generated code. In our Java, the ``import``
statements use the names from the ``.thrift`` files' ``namespace``\s:

.. include:: ../../../../../tests/java/com/twitter/common/examples/usethrift/UseThriftTest.java
   :code: java
   :start-after: from Java.

As usual, for code in one target to use code from another, one target needs to
depend on the other. Thus, our Java code's target has the ``*_thrift_library``
target whose code it uses in its dependencies:

.. include:: ../../../../../tests/java/com/twitter/common/examples/usethrift/BUILD
   :code: python
   :start-after: using Thrift from Java, though.

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
