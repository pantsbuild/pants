Welcome to the Pants build system.
==================================

Pants is a build system for software projects in a variety of
languages. It works particularly well for a source code repository
that contains many distinct projects.

Getting started using Pants
---------------------------

Tutorials and basic concepts. How to use Pants to build things.
How to configure build-able things in BUILD files.

.. toctree::
   :maxdepth: 1

   first_concepts
   first_tutorial
   target_addresses
   JVMProjects
   python-readme
   page
   build_files
   invoking
   tshoot

Troubleshooting
---------------

* Something that usually works just failed? See :doc:`tshoot`.

* Publishing can fail in more ways. See :doc:`publish`.

Pants Patterns
--------------

Common Pants build idioms.

.. toctree::
   :maxdepth: 1

   3rdparty
   ThriftDeps
   publish

Using Pants With...
-------------------

.. toctree::
   :maxdepth: 1

   with_emacs
   with_intellij

News
----

.. toctree::
   :hidden:

   announce_201409

*  `2014-09-16 Announcement <announce_201409.html>`_ "Hello Pants Build"

Advanced Documentation
----------------------

.. toctree::
   :maxdepth: 1

   setup_repo
   install


Pants Reference Documentation
-----------------------------

.. toctree::
   :maxdepth: 1

   build_dictionary
   goals_reference


Contributing to Pants
---------------------

How to develop Pants itself and contribute your changes.

.. toctree::
   :maxdepth: 1

   dev
