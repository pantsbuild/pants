Installing
==========

As of October 2013, the way to install Pants build is to install a repo
already set up with Pants (and then invoke ``./pants`` in its root dir
to use it).

Requirements
------------

Most of the commons python environment has been developed against CPython 2.6.
Things mostly work with CPython 2.7 and recent efforts have been made to improve
CPython 3.x and PyPy compatibility.  We've explicitly ignored anything prior to
CPython 2.6 and in fact generally discourage use against anything less than
CPython 2.6.5 as there are known bugs that we're unwilling to fix.  We've never
even tried running against Jython or IronPython so if that's your environment,
you're on your own.

If none of this made any sense to you, run `python -V`.  If it says `Python
2.6.x` or `Python 2.7.x` you're probably fine.

TL;DR
-----

Nowadays, you use Pants by working in a repo for which it's already
installed. If that's not true and you're thinking "Is there some
open-source repo in which I can try pants?" then
``git clone git://github.com/twitter/commons && cd commons`` and then
``./pants``

.. _tshoot:

Troubleshooting
---------------

`TypeError: unpack_http_url() takes exactly 4 arguments (3 given)`
``````````````````````````````````````````````````````````````````

If you see this error, it means that your installation is attempting to use a cached
version of pip 1.0.2 instead of pip 1.1.

Solution::

    $ rm -rf .python
    $ rm -f pants.pex
    $ ./pants

`TypeError: __init__() got an unexpected keyword argument 'platforms'`
``````````````````````````````````````````````````````````````````````

If you see this error, you're running an old pants.pex against a new BUILD file.

Solution::

    $ rm -f pants.pex
    $ ./pants


`AttributeError: 'NoneType' object has no attribute 'rfind'`
````````````````````````````````````````````````````````````

If you see this error, you're running an old pants.pex against a new BUILD file.

Solution::

    $ rm -f pants.pex
    $ ./pants


`DistributionNotFound: pytest-cov`
``````````````````````````````````

If you encounter this error after building pants, it means that some dependent
libraries like pytest-cov which are downloaded from Internal Twitter network
has not been downloaded yet.  Make sure you are on VPN or Twitter Network so
that your dependencies may be downloaded during the build.


Almost any problem
``````````````````

Almost any problem can be solved by fully clearing out all caches and rebuilding pants::

    $ build-support/python/clean.sh
    $ ./pants

Did you change your `PYTHONPATH` recently? Pants is implemented in Python, so
`PYTHONPATH` can cause spooky changes.

Prefix your pants command with some verbosity-setting environment vars::

    PEX_VERBOSE=1 PANTS_VERBOSE=1 PYTHON_VERBOSE=1 ./pants ...

It won't fix the problem, but it might clarify the problem.
