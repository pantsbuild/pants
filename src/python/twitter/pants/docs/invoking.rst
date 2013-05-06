Invoking Pants Build
====================

This page discusses some advanced features of invoking the Pants build tool on the command
line. We assume you already know the :doc:`basic command-line structure <first_tutorial>`,
something like ::

    ./pants goal test bundle path/to/target path/to/another/target

For a full description of specifying target addresses, see **TODO**

rc files
--------

If there's a command line flag that you always (or nearly always) use,
you might set up a configuration file to ease this. A typical Pants
installation looks for machine-specific settings in ``/etc/pantsrc`` and
personal settings in ``~/.pants.new.rc``, with personal settings overriding
machine-specific settings.

For example, suppose that every time you invoke Pants to compile Java code, you
pass flags ``--compile-javac-args=-source --compile-javac-args=7
--compile-javac-args=-target --compile-javac-args=7``.
Instead of passing them on the command line each time, you could set up a
``~/.pants.new.rc`` \file::

    [javac]
    options:
      --compile-javac-args=-source --compile-javac-args=7
      --compile-javac-args=-target --compile-javac-args=7

With this configuration, Pants will have these flags on by
default.

``--compile-javac-*`` flags go in the ``[javac]`` section;
generally, ``--compile``-*foo*\-* flags go in the ``[foo]`` section.
``--test-junit-*`` flags go in the ``[junit]`` section;
generally, ``--test``-*bar*\-* flags go in the ``[bar]`` section.
``--idea-*`` flags go in the ``[idea]`` section.

If you know the Pants internals well enough to know the name of a
``Task`` class, you can use that class' name as a category to set
command-line options affecting it::

    [twitter.pants.tasks.nailgun_task.NailgunTask]
    # Don't spawn compilation daemons on this shared build server
    options: --no-ng-daemons

Although ``/etc/pantsrc`` and ``~/.pants.new.rc`` are the typical places for
this configuration, you can check :ref:`pants.ini <setup-pants-ini>`
to find out what your source tree uses. ::

    # excerpt from pants.ini
    [DEFAULT]
    # Look for these rcfiles - they need not exist on the system
    rcfiles: ['/etc/pantsrc', '~/.pants.new.rc']

In this list, later files override earlier ones.

These files are formatted as
`Python config files <http://docs.python.org/install/index.html#inst-config-syntax>`_,
parsed by `ConfigParser <http://docs.python.org/library/configparser.html>`_.

