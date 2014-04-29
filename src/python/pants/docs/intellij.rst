####################################
Pants Development with IntelliJ IDEA
####################################

This page documents how to develop pants with `IntelliJ IDEA <http://www.jetbrains.com/idea/>`_\.
(To use IntelliJ with Pants, not necessarily to develop Pants itself,
see :doc:`with_intellij`.)

**************
IntelliJ Setup
**************

As pants is a python application, the "Ultimate" (aka paid-for) edition of
IntelliJ is required, as is the Python plugin. You'll need to:

* Download "IntelliJ IDEA Ultimate Edition" from http://www.jetbrains.com/.
* Within IntelliJ, install the Python plugin.


*************
Project Setup
*************

While pants can generate IntelliJ IDEA projects for Java/Scala targets, it
cannot yet generate projects for Python targets. For this reason you must
manually create the project. This section walks you through that process using
IntelliJ IDEA 13.1.2.

First you need to bootstrap pants in developer mode.  This is generally the
way you want to run pants when iterating and it also prepares a virtual
environment suitable for IDEs:

   $ PANTS_DEV=1 ./pants

Next open IntelliJ and select "Create New Project".

.. image:: images/intellij-new-project-1.png

In the "New Project" window, select "Python".

.. image:: images/intellij-new-project-2.png

Then skip past the project templates screen and land at the Python interpreter
configuration screen. Click "Configure..." and add a "Python SDK".

.. image:: images/intellij-new-pythonsdk.png

This will be a "local" interpreter and you'll need to select the virtual
environment bootstrapped above; it's in `build-support/pants_dev_deps.venv`
(not `build-support/pants_deps.venv`).  This is **important** because the dev virtual
environment is designed to have 3rdparty deps IDEs can handle.

.. image:: images/intellij-select-venv.png

Next specify a "Project name" and "Project location".

Now open the "File -> Project Structure" window. In the "Project", specify your
the python interpreter you configured above.

.. image:: images/intellij-project-structure-project.png

In the "Modules" section, you need to mark "Sources" and "Tests". This establoshes
the loose python source roots to add to the PYTHONPATH - the parent directory of what
you'll import. Mark the `src/python` directory as sources and `tests/python`
directory as test_sources.

.. image:: images/intellij-project-structure-modules-sources.png

Finally in "File -> Settings -> Python Integrated Tools" set the default test runner
to `py.test` - which is what pants uses to drive python tests.

.. image:: images/intellij-configure-tests.png

Now your project setup is complete!


**********************************
Running Pants within IntelliJ IDEA
**********************************

In addition to editing pants code in IntelliJ, pants itself can be run/debug
from within the editor. This is particularly useful for fast iteration both
within the pants repo, and running pants from sources against a different
repo.

Open the "Run -> Edit Configurations..." dialog box.

* Add a new Python configuration.
* Set the "Script" to
  `/home/jsirois/dev-pants/src/python/pants/bin/pants_exe.py`
* Set the "Script parameters" to your pants command-line args,
  such as `goal goals`.
* Set the "Working directory" to where you want to run pants from. Note this
  could be an entirely different repo from where the pants source code lives.
  This is very useful for making a pants change and testing in the repo where
  you use pants.

.. image:: images/intellij-run.png

After creating the run configuration, simply run or debug pants from within
the editor using all the features that provides you.
