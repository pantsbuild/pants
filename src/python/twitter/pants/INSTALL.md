# Installing / troubleshooting pants #

# Requirements #

Most of the commons python environment has been developed against CPython
2.6.  Things mostly work with CPython 2.7 and recent efforts have been made
to improve CPython 3.x and PyPy compatibility.  We've explicitly ignored
anything prior to CPython 2.6 and in fact generally discourage use against
anything less than CPython 2.6.5 as there are known bugs that we're
unwilling to fix.  We've never even tried running against Jython or
IronPython so if that's your environment, you're on your own.

If none of this made any sense to you, run `python -V`.  If it says `Python
2.6.x` or `Python 2.7.x` you're probably fine.

# TL;DR #

    $ git clone git://github.com/twitter/commons && cd commons
    $ ./pants


# Troubleshooting #

## `TypeError: unpack_http_url() takes exactly 4 arguments (3 given)` ##

If you see this error, it means that your installation is attempting to use a cached
version of pip 1.0.2 instead of pip 1.1.

Solution:

    $ rm -rf .python
    $ rm -f pants.pex
    $ ./pants

## `TypeError: __init__() got an unexpected keyword argument 'platforms'`

If you see this error, you're running an old pants.pex against a new BUILD file.

Solution:

    $ rm -f pants.pex
    $ ./pants


## `AttributeError: 'NoneType' object has no attribute 'rfind'` ##

If you see this error, you're running an old pants.pex against a new BUILD file.

Solution:

    $ rm -f pants.pex
    $ ./pants

## `OSError: [Errno 2] No such file or directory: '/path/to/science/build-support/profiles/foobar.libs'` ##

You've somehow lost or removed required libraries (e.g. jars for `nailgun`, `jmake`) which support
various pants goals.

Solution:

    $ git clean -fdx build-support/profiles
    $ ./pants goal clean-all

## Almost any problem ##

Almost any problem can be solved by fully clearing out all caches and rebuilding pants:

    $ build-support/python/clean.sh
    $ ./science-tools/check_environment.sh
    $ ./pants
