################
Installing Pants
################

**As of May 2014, alas, Pants is not an install-able thing.**
You can use it in a repo in which some Pants expert has set it up;
you can use it to build things *in* that repo, but nothing else.

We're fixing this this problem, but we're not done yet.

If want to try out Pants and no Pants expert has set it up for you,
you might try https://github.com/twitter/commons\.
(https://github.com/pantsbuild/pants also uses Pants to build, but there tends
to be a lot of "churn".)

If you're reading this in an organization that already uses Pants,
ask your neighbor where your source code is.

.. COMMENT
   ************************
   System-wide Installation
   ************************

   The simplest installation method is installing for all users on your system. ::

      pip install pantsbuild.pants

   This installs pants (and its dependencies) into your Python distribution
   site-packages, making it available to all users on your system. This
   installation method requires root access and may cause dependency conflicts
   with other pip-installed applications.


   *****************************
   Virtualenv-based Installation
   *****************************

   `Virtualenv <http://www.virtualenv.org/>`_ is a tool for creating isolated
   Python environments. This is the recommended way of installing pants locally
   as it does not modify the system Python libraries. ::

      $ virtualenv /tmp/pants
      $ source /tmp/pants/bin/activate
      $ pip install pantsbuild.pants
      $ pants

   To simplify a virtualenv-based installation, consider adding a wrapper script
   to your repo. See https://github.com/pantsbuild/pants/blob/master/pants for an
   example.


**********************
PEX-based Installation
**********************

To support hermetic builds and not depend on a local pants installation
(e.g.: CI machines may prohibit software installation), some sites fetch
a pre-build `pants.pex` whose version is checked-into `pants.ini`. If your site
uses such an installation, please ask around for details.

.. TODO(travis): Should we provide an example fetcher script?
