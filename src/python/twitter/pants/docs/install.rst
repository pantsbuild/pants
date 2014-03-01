Installing
==========

**As of January 2014, alas, Pants is not an install-able thing.**
You can use it in a repo in which some Pants expert has set it up;
you can use it to build things *in* that repo, but nothing else.

We hope to fix this situation soon, but we're not there yet.
If you're reading this in open-source-land and want to try out Pants,
https://github.com/twitter/commons uses it. If you're reading this in
an organization that already uses Pants, ask your neighbor where
your source code is.


Requirements
------------

Most of Pants was developed against CPython 2.6.
Things mostly work with CPython 2.7 and recent efforts have been made to improve
CPython 3.x and PyPy compatibility.  We've explicitly ignored anything prior to
CPython 2.6 and generally discourage use against anything less than
CPython 2.6.5 as there are known bugs that we're unwilling to fix.  We've never
even tried running against Jython or IronPython so if that's your environment,
you're on your own.

If none of this made any sense to you, run `python -V`.  If it says `Python
2.6.x` or `Python 2.7.x` you're probably fine.

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

Almost any problem can be solved by fully clearing out all caches,
rebuilding Pants,
and killing all lingering nailgun (JVM build implementation) processes::

    $ build-support/python/clean.sh
    $ ./pants.bootstrap
    $ ./pants goal ng-killall --ng-killall-everywhere

Did you change your `PYTHONPATH` recently? Pants is implemented in Python, so
`PYTHONPATH` can cause spooky changes.

Prefix your pants command with some verbosity-setting environment vars::

    PEX_VERBOSE=1 PANTS_VERBOSE=1 PYTHON_VERBOSE=1 ./pants ...

It won't fix the problem, but it might clarify the problem.
