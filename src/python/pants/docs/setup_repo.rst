#################################
Set up Your Source Tree for Pants
#################################

.. Removing this warning? Also remove warning from install.rst.

**As of September 2014, this is only possible for Pants experts.**
**The Pants community is actively working to improve it.**
If you're setting up the Pants build tool to work in your source tree, you
need to configure Pants' behavior.  (Once it's set up, most
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
`base/config.py <https://github.com/pantsbuild/pants/blob/master/src/python/pants/base/config.py>`_.

.. TODO update base/config.py link if/when source code moves

.. _setup_source_root:

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

**************************************
Integrate New Tools via a Pants Plugin
**************************************

Pants knows how to build many things, but maybe you need it to learn a new tool.
Maybe your organization has a custom linter, a custom code generator,
or some other custom tool. Maybe your organization uses a tool that, while
not custom, has not yet been integrated with Pants.

* If your organization has some custom tools to integrate,
  set up a :doc:`Pants plugin <howto_plugin>`.
* If you want to integrate with a not-custom tool, you
  still want to set up a Pants plugin (or perhaps add abilities
  to an existing plugin), but it might make sense to
  :doc:`get your changes in upstream <howto_contribute>`.

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
      'bar:all',
      'baz:all',
      'garply:all',
    ],)

If you don't want to make this test definition available to the public (lest
they complain about how long it takes), you might put this in a `BUILD.foo`
file and hold back this file when mirroring for the public repository.

.. _setup_publish:

**********************
Enabling Pants Publish
**********************

Pants can :doc:`ease "publishing" <publish>`:
uploading versioned compiled artifacts.
There are some special things to set up to enable and customize publishing.

Tell Pants about your Artifact Repository
=========================================

To tell Pants which artifact repsitory to publish to,

Create a :doc:`plugin <howto_plugin>` if you haven't already.
Register it with Pants.

In the plugin, define and register a ``Repository`` in a BUILD file
alias as shown in
`src/python/internal_backend/repositories/register.py <https://github.com/pantsbuild/pants/blob/master/src/python/internal_backend/repositories/register.py>`_\.


``BUILD`` targets can use this Repository's alias as the
``repo`` parameter to an :ref:`artifact <bdict_artifact>`.
For example, the ``src/java/com/pants/examples/hello/greet/BUILD``
refers to the ``public`` repostiory defined above.
(Notice it's a Python object, not a string.) ::

    provides = artifact(org='com.pants.examples',
                        name='hello-greet',
                        repo=public,)

If you get an error that the repo name (here, ``public``) isn't defined,
your plugin didn't register with Pants successfully. Make sure you bootstrap
Pants in a way that loads your ``register.py``.

.. ivysettings.xml mentioned here, but w/out details TODO

In your config file (usually ``pants.ini``), set up a
``[jar-publish]`` section. In that section, create a ``dict`` called ``repos``.
It should contain a section for each Repository::

    repos: {
      'public': {  # must match the alias above
        'resolver': 'maven.twttr.com', # must match URL above and <url> name
                                       # in ivysettings.xml
        'confs': ['default', 'sources', 'docs', 'changelog'],
        # 'auth': 'build-support:netrc',
        # 'help': 'Configure your ~/.netrc for artifactory access.
      },
      'testing': { # this key must match the alias name above
        'resolver': 'maven.twttr.com',
        'confs': ['default', 'sources', 'docs', 'changelog'],
        # 'auth': 'build-support:netrc',
        # 'help': 'Configure your ~/.netrc for artifactory access.
      },
    }


.. _setup_publish_restrict_branch:

Restricting Publish to "Release Branch"
=======================================

Your organization might have a notion of a special "release branch": you want
:doc:`artifact publishing <publish>`
to happen on this source control branch, which you maintain
extra-carefully.
You can set this branch using the restrict_push_branches option
of the ``[jar-publish]`` section of your config file (usually ``pants.ini``).

Task to Publish "Extra" Artifacts
=================================

Pants supports "publish plugins", which allow end-users to add additional,
arbitrary files to be published along with the primary artifact. For example,
let's say that along with publishing your jar full of class files, you would
also like to publish a companion file that contains some metadata -- code
coverage info, source git repository, java version that created the jar, etc.
By developing a :doc:`task <dev_tasks>` in a :doc:`plugin <howto_plugin>`,
you give Pants a new ability. See
:doc:` <dev_task_publish_extras>` to find out how to develop a special
Task to include "extra" data with published artifacts.

.. toctree::
   :maxdepth: 1

   dev_tasks_publish_extras
