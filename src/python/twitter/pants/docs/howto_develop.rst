######################
Pants Developers Guide
######################

This page describes the developer workflow when changing Pants itself. (If you
wanted instructions for using Pants to develop other programs, please see
:doc:`first_tutorial`.)

.. Getting the source code section.


********************
Running from sources
********************

As pants is implemented in python it can be run directly from sources.
Use the ``pants.bootstrap`` script. ::

   $ PANTS_DEV=1 ./pants.bootstrap goal goals
   *** running pants in dev mode from ./src/python/twitter/pants/bin/pants_exe.py ***
   <remainder of output omitted for brevity>

Notice this invocation specifies the ``PANTS_DEV`` environment variable.
By defining ``PANTS_DEV`` pants will be run from sources.


********************
Building a Pants PEX
********************

While you can build a Pants PEX in the usual Python way, ``pants.bootstrap``
is a nice wrapper. If you call it without the ``PANTS_DEV=1``
environment described above, it

   * Checks the source tree's top directory for a ``pants.pex`` and runs it
     if it exists. Otherwise ``pants.bootstrap``...
   * Builds a new ``pants.pex``, moves it to the source tree's top
     directory, and runs that.

It looks something like::

   $ rm pants.pex
   $ ./pants.bootstrap goal my-new-feature
   Build operating on targets: OrderedSet([PythonBinary(src/python/twitter/pants/BUILD:pants)])
   Building PythonBinary PythonBinary(src/python/twitter/pants/BUILD:pants):
   Wrote /Users/travis/src/science/dist/pants.pex
   AMAZING NEW FEATURE PRINTS HERE
   $ ls pants.pex # gets moved here, though originally "Wrote" to ./dist/
   pants.pex
   $ ./pants.bootstrap goal my-new-feature
   AMAZING NEW FEATURE PRINTS HERE

Using ``./pants.bootstrap`` to launch Pants thus
gives a handy workflow: generate ``pants.pex``. Go back and forth
between trying the generated ``pants.pex`` and fixing source code
as inspired by its misbehaviors. When the fixed source code is in a
consistent state, remove ``pants.pex`` so that it will get replaced
on the next ``pants.bootstrap`` run.

(The ``./pants`` launcher, like ``./pants.bootstrap``, checks for a
``pants.pex`` in the source tree's top directory and uses that ``pants.pex``
if found.)

*******
Testing
*******

Running Tests
=============

Pants has many tests. There are BUILD targets to run those tests.
To make sure a change passes *all* of Pants' tests, use the
``tests/python/twitter/pants:all`` target:

   ./pants tests/python/twitter/pants:all

Before :doc:`contributing a change <howto_contribute>` to Pants,
make sure it passes all tests.

For convenience, some other test targets enable more granular test running.
Please see the BUILD files for details.

.. Writing Tests section
.. Documenting section
