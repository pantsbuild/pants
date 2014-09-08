#######################
Python 3rdparty Pattern
#######################

In general, we use :doc:`the 3rdparty idiom <3rdparty>` to organize
dependencies on code from outside the source tree. This document
describes how to make this work for Python code.

Your Python code can pull in code written elsewhere. Pants fetches code
via a library that uses pip-style specifications (name and version-range).

***************
3rdparty/python
***************

To keep all of your code depending on the same versions of third-party
Python artifacts, you might use the idiom of keeping them in a directory
tree under ``3rdparty/python``. If your organization has many such
dependencies, you might arrange them in several directories: this can
ease later "git detective work" when finding out who changed a version.

**pip-style requirements.txt:**

To define some third-party dependencies, use a
:ref:`python_requirements <bdict_python_requirements>`
in your ``BUILD`` file and make a pip ``requirements.txt`` file in the
same directory.

E.g, your ``3rdparty/python/BUILD`` file might look like:

.. literalinclude:: ../../../../3rdparty/python/BUILD
   :start-after: Licensed under
   :end-before: target

...with ``3rdparty/python/requirements.txt`` like:

.. literalinclude:: ../../../../3rdparty/python/requirements.txt
   :end-before: mox

``python_requirements`` defines a named target for each
line in the ``requirements.txt`` line. For example, a line like
``ansicolors==1.0.2`` in ``requirements.txt`` defines a target named
``ansicolors`` that pulls in ansicolors version 1.0.2.

**python_requirement_library and python_requirement:**

A ``BUILD`` file can also define requirements without a ``requirements.txt``
file. Set up a
:ref:`python_requirement_library <bdict_python_requirement_library>` with one
or more
:ref:`python_requirement <bdict_python_requirement>`\s like::

    python_requirement_library(
      name='beautifulsoup',
      requirements=[
        python_requirement(name='beautifulsoup',
                           requirement='BeautifulSoup==3.2.0'),
      ])

**********************
Your Code's BUILD File
**********************

In your code's ``BUILD`` file, introduce a dependency on the ``3rdparty``
target:

.. literalinclude:: ../../../../examples/src/python/example/hello/greet/BUILD
   :start-after: Like Hello


Then in your Python code, you can ``import`` from that package::

   from colors import green
