################
Installing Pants
################

**As of September 2014, alas, Pants is not something you can just install and use.**
To be precise: you can install it, but unless you've also
:doc:`Set up your code workspace to work with Pants <setup_repo>`,
it won't work.
You can use it in a workspace in which some Pants expert has set it up.

We're fixing this problem, but we're not done yet.

If want to try out Pants and no Pants expert has set it up for you,
you might try https://github.com/twitter/commons\.
(https://github.com/pantsbuild/pants also uses Pants to build, but there tends
to be a lot of "churn".)

If you're reading this in an organization that already uses Pants,
ask your neighbor where your source code is.

There are a few ways to get a runnable version of Pants into a developer's
workspace.

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

To simplify a virtualenv-based installation, add a wrapper script
to your repo. For an example, see the ``twitter/commons`` script ``./pants``,
https://github.com/twitter/commons/blob/master/pants\, and its
helper scripts.

************************
System-wide Installation
************************

To install pants for all users on your system::

    pip install pantsbuild.pants

This installs pants (and its dependencies) into your Python distribution
site-packages, making it available to all users on your system. This
installation method requires root access and may cause dependency conflicts
with other pip-installed applications.


**********************
PEX-based Installation
**********************

To support hermetic builds and not depend on a local pants installation
(e.g.: CI machines may prohibit software installation), some sites fetch
a pre-build `pants.pex` whose version is checked-into `pants.ini`. If your site
uses such an installation, please ask around for details.


