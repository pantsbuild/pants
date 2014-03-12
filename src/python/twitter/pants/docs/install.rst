################
Installing Pants
################

This page documents how to install pants. Three installation methods are
described, each with different tradeoffs, allowing you can choose the
right method for your particular needs.

************************
System-wide Installation
************************

The simplest installation method is installing for all users on your system. ::

   pip install twitter.pants

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
   $ pip install twitter.pants \
     --allow-external elementtree \
     --allow-unverified elementtree
   $ pants

To simplify a virtualenv-based installation, consider adding a wrapper script
to your repo. See https://github.com/twitter/commons/blob/master/pants for an
example.


**********************
PEX-based Installation
**********************

To support hermetic builds and not depend on a local pants installation
(e.g.: CI machines may prohibit software installation), some sites fetch
a pre-build `pants.pex` whose version is checked-into `pants.ini`. If your site
uses such an installation, please ask around for details.

.. TODO(travis): Should we provide an example fetcher script?
