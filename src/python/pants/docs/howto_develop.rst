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

As pants is implemented in python it can be run directly from sources. ::

   $ PANTS_DEV=1 ./pants goal goals
   *** running pants in dev mode from ./src/python/pants/bin/pants_exe.py ***
   <remainder of output omitted for brevity>

Notice this invocation specifies the ``PANTS_DEV`` environment variable.
By defining ``PANTS_DEV`` pants will be run from sources.


********************
Building a Pants PEX
********************

While you can build a Pants PEX in the usual Python way, the ``./pants``
wrapper provides some extra conveniences. If you call it without the
``PANTS_DEV=1`` environment described above, it

   * Checks the source tree's top directory for a ``pants.pex`` and runs it
     if it exists. Otherwise ``./pants``...
   * Builds a new ``pants.pex``, moves it to the source tree's top
     directory, and runs that.

It looks something like::

   $ rm pants.pex
   $ ./pants goal my-new-feature
   Build operating on targets: OrderedSet([PythonBinary(src/python/pants/BUILD:pants)])
   Building PythonBinary PythonBinary(src/python/pants/BUILD:pants):
   Wrote /Users/travis/src/science/dist/pants.pex
   AMAZING NEW FEATURE PRINTS HERE
   $ ls pants.pex # gets moved here, though originally "Wrote" to ./dist/
   pants.pex
   $ ./pants goal my-new-feature
   AMAZING NEW FEATURE PRINTS HERE

Using ``./pants`` to launch Pants thus
gives a handy workflow: generate ``pants.pex``. Go back and forth
between trying the generated ``pants.pex`` and fixing source code
as inspired by its misbehaviors. When the fixed source code is in a
consistent state, remove ``pants.pex`` so that it will get replaced
on the next ``./pants`` run.


*******
Testing
*******

Running Tests
=============

Pants has many tests. There are BUILD targets to run those tests.
We try to keep them passing.
To make sure a change passes *all* of Pants' tests, use the
``tests/python/pants_test:all`` target.
*Do not* use ``PANTS_DEV=1`` when running tests at this time
as that modifies ``sys.path`` in such a way as resources will
not be discovered correctly. ::

   ./pants tests/python/pants_test:all

To bring up the ``pdb`` debugger when tests fail, pass the ``--pdb`` flag.

To try all the tests in a few configurations, you can run the same script
that our Travis CI does. This can take a while, but it's a good idea to
run it before you contribute a change or merge it to master::

   ./build-support/bin/ci.sh

Before :doc:`contributing a change <howto_contribute>` to Pants,
make sure it passes all tests.

For convenience, some other test targets enable more granular test running.
Please see the BUILD files for details.

*********
Debugging
*********

To run Pants under ``pdb`` and set a breakpoint, you can typically add ::

  import pdb; pdb.set_trace()

...where you first want to break. If the code is in a test, instead use ::

    import pytest; pytest.set_trace()

To run tests and bring up ``pdb`` for failing tests, you can
instead pass ``--pdb``::

    $ ./pants tests/python/pants_test/tasks: --pdb
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

To start an interactive Python shell that can ``import`` Pants modules,
use the usual ``./pants py`` on a ``python_library`` target that builds
(or depends on) the modules you want::

    $ ./pants py src/python/pants/backend/core/targets:common
    /Users/lhosken/workspace/pants src/python/pants/backend/core/targets:common
    Python 2.6.8 (unknown, Mar  9 2014, 22:16:00)
    [GCC 4.2.1 Compatible Apple LLVM 5.0 (clang-500.0.68)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>> from pants.backend.core.targets import repository
    >>>

.. Writing Tests section
.. Documenting section
