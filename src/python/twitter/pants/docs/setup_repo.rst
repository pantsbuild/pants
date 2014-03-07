#################################
Set up Your Source Tree for Pants
#################################

If you're setting up the Pants build tool to work in your source tree, you
probably want to configure Pants' behavior.  (Once it's set up, most
folks should be able to use the :doc:`first_concepts`
and not worry about these things.)

.. _setup-pants-ini:

******************************
Configuring with ``pants.ini``
******************************

Pants Build is very configurable. Your source tree's top-level directory should
contain a ``pants.ini`` file that sets many, many options. You can modify a broad range of
settings here, including specific binaries to use in your toolchain,
arguments to pass to tools, etc.

These files are formatted as
`Python config files <http://docs.python.org/install/index.html#inst-config-syntax>`_,
parsed by `ConfigParser <http://docs.python.org/library/configparser.html>`_.
Thus, they look something like::

    [section]
    setting1: value1
    setting2: value2

The ``[DEFAULT]`` section is special: its values are available in other sections.
It's thus handy for defining values that will be used in several contexts, as in these
excerpts that define/use ``thrift_workdir``::

    [DEFAULT]
    thrift_workdir: %(pants_workdir)s/thrift

    [thrift-gen]
    workdir: %(thrift_workdir)s

    [java-compile]
    args: [
      '-C-Tnowarnprefixes', '-C%(thrift_workdir)s',
    ]

It's also handy for defining values that are used in several contexts, since these values
will be available in all those contexts. The code that combines DEFAULT values with
others is in Pants'
`base/config.py <https://github.com/twitter/commons/blob/master/src/python/twitter/pants/base/config.py>`_.

.. TODO update base/config.py link if/when source code moves

****************************************
Configure Code Layout with `source_root`
****************************************

Maybe someday all the world's programmers will agree on the one true directory
structure for source code. Until then, you'll want some
:ref:`bdict_source_root` rules to specify which directories hold
your code. A typical programming language has a notion of *base paths*
for imports; you configure pants to tell it those base paths.

If your project's source tree is laid out for Maven, there's a shortcut function
`maven_layout` that configures source roots for Maven's expected
source code tree structure.

Organized by Language
=====================

If your top-level ``BUILD`` file is ``top/BUILD`` and your main Java code is in
``top/src/java/com/foo/`` and your Java tests are in ``top/src/javatest/com/foo/``,
then your top-level `BUILD` file might look like::

    # top/BUILD
    source_root('src/java')
    source_root('src/javatest')
    ...

Pants can optionally enforce that only certain target types are allowed under each source root::

    # top/BUILD
    source_root('src/java', annotation_processor, doc, jvm_binary, java_library, page)
    source_root('src/javatest', doc, java_library, java_tests, page)
    ...


Organized by Project
====================

If your top-level ``BUILD`` file is ``top/BUILD`` and the Java code for your
Theodore and Hank projects live in ``top/theodore/src/java/com/foo/``,
then your top-level `BUILD` file might not contain any ``source_root`` statements.
Instead, ``theodore/BUILD`` and ``hank/BUILD`` might look like::

    # top/(project)/BUILD
    source_root('src/java')
    source_root('src/javatest')
    ...

Or::

    # top/(project)/BUILD
    source_root('src/java', annotation_processor, doc, jvm_binary, java_library, page)
    source_root('src/javatest', doc, java_library, java_tests, page)
    ...


`BUILD.*` and environment-specific config
-----------------------------------------

When we said `BUILD` files were named `BUILD`, we really meant `BUILD`
or *BUILD*\ .\ `something`. If you have some rules that make sense for folks
in one environment but not others, you might put them into a separate
BUILD file named *BUILD*\ .\ `something`.

******************************************
Top-level `BUILD.*` for tree-global config
******************************************

When you invoke ``./pants goal something src/foo:foo`` it processes
the code in `src/foo/BUILD` and the code in `./BUILD` *and* `./BUILD.*`. If you
distribute code to different organizations, and want different configuration
for them, you might put the relevant config code in `./BUILD.something`.
You can give that file to some people and not-give it to others.

For example, you might work at the Foo Corporation, which maintains a fleet
of machines to run big test jobs. You might define a new `goal` type to
express sending a test job to the fleet::

    goal(name='test_on_fleet',
         action=SendTestToFleet,
         dependencies=[]).install().with_description('Send test to Foo fleet')

If the testing fleet is only available on Foo's internal network and you
open-source this code, you don't want to expose `test_on_fleet` to the world.
You'd just get complaints about `Host testfleet.intranet.foo.com not found`
errors.

You might put this code in a `./BUILD.foo` in the top-level directory of the
internal version of the source tree; then hold back this file when mirroring for
the public version. Thus, the foo-internal-only rules will be available
inside Foo, but not to the world.

**********************************************
BUILD.* in the source tree for special targets
**********************************************

If you distribute code to different organizations, you might want to expose some
targets to one organization but not to another. You can do this by defining
those targets in a `BUILD.*` file. You can give that file to some people and
not-give it to others. This code will be processed by people invoking pants
on this directory only if they have the file.

For example, you might work at the Foo Corporation, which maintains a fleet
of machines to run big test jobs. You might define a humungous test job
as a convenient way to send many many tests to the fleet ::

    # src/javatest/com/foo/BUILD.foo
    
    # many-many test: Run this on the fleet, not your workstation
    # (unless you want to wait a few hours for results)
    junit_tests(name='many-many',
    dependencies = [
      'bar/BUILD:all',
      'baz/BUILD:all',
      'garply/BUILD:all',
    ],)

If you don't want to make this test definition available to the public (lest
they complain about how long it takes), you might put this in a `BUILD.foo`
file and hold back this file when mirroring for the public repository.

.. _setup_publish_restrict_branch:

***************************************
Restricting Publish to "Release Branch"
***************************************

Your organization might have a notion of a special "release branch": you want
:doc:`artifact publishing <publish>`
to happen on this source control branch, which you maintain
extra-carefully. To configure this, set up a ``JarPublish``
subclass in an always-used ``BUILD`` file (in most repos, this
means a ``BUILD`` file in the top directory). This ``JarPublish``
subclass should use ``restrict_push_branches``. Set up your repo's
``publish`` goal to use this class::

    # ./BUILD.myorg
    class MyorgJarPublish(JarPublish):
      def __init__(self, context):
        super(MyorgJarPublish, self).__init__(context, restrict_push_branches=['master'])

    goal(name='publish',
         action=MyorgJarPublish).install('publish').with_description('Publish one or more artifacts.')

If a user invokes ``goal publish`` from some other branch, Pants balks.
