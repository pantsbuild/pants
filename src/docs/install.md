Installing Pants
================

**As of September 2014, alas, Pants is not something you can just
install and use.** To be precise: you can install it, but unless you've
also
[[Set up your code workspace to work with Pants|pants('src/docs:setup_repo')]],
it won't work. You can use it in a workspace in which some Pants expert has
set it up.

We're fixing this problem, but we're not done yet.

If want to try out Pants and no Pants expert has set it up for you, you
might try <https://github.com/twitter/commons>.
(<https://github.com/pantsbuild/pants> also uses Pants to build, but
there tends to be a lot of "churn".)

If you're reading this in an organization that already uses Pants, ask
your neighbor where your source code is.

There are a few ways to get a runnable version of Pants into a
developer's workspace.

Virtualenv-based Installation
-----------------------------

[Virtualenv](http://www.virtualenv.org/) is a tool for creating isolated
Python environments. This is the recommended way of installing pants
locally as it does not modify the system Python libraries.

    :::bash
    $ virtualenv /tmp/pants
    $ source /tmp/pants/bin/activate
    $ pip install pantsbuild.pants
    $ pants

To simplify a virtualenv-based installation, add a wrapper script to
your repo. For an example, see the
[`twitter/commons` script `./pants`](https://github.com/twitter/commons/blob/master/pants),
and its helper scripts.

System-wide Installation
------------------------

To install pants for all users on your system:

    :::bash
    $ pip install pantsbuild.pants

This installs pants (and its dependencies) into your Python distribution
site-packages, making it available to all users on your system. This
installation method requires root access and may cause dependency
conflicts with other pip-installed applications.

PEX-based Installation
----------------------

To support hermetic builds and not depend on a local pants installation (e.g.: CI machines may
prohibit software installation), some sites fetch a pre-build `pants.pex` whose version is
checked-into `pants.ini`. To upgrade pants, generate a `pants.pex` and upload it to a file
server at a location computable from the version number. Set up the workspace's `./pants` script
to check the `.ini` file for a version number and download from the correct spot.

Troubleshooting
---------------

While pants is written in pure Python, some of it's dependencies contain native code. Therefore,
you'll need to make sure you have the appropriate compiler infrastructure installed on the machine
where you are attempting to bootstrap pants. In particular, if you see an error similar to this:

    :::bash
    Installing setuptools, pip...done.
        Command "/Users/someuser/workspace/pants/build-support/pants_deps.venv/bin/python2.7 -c "import setuptools, tokenize;__file__='/private/var/folders/zc/0jhjvzy56s723lpq23q89f6c0000gn/T/pip-build-mZzSSA/psutil/setup.py';exec(compile(getattr(tokenize, 'open', open)(__file__).read().replace('\r\n', '\n'), __file__, 'exec'))" install --record /var/folders/zc/0jhjvzy56s723lpq23q89f6c0000gn/T/pip-iONF8p-record/install-record.txt --single-version-externally-managed --compile --install-headers /Users/someuser/workspace/pants/build-support/pants_deps.venv/bin/../include/site/python2.7/psutil" failed with error code 1 in /private/var/folders/zc/0jhjvzy56s723lpq23q89f6c0000gn/T/pip-build-mZzSSA/psutil

    Failed to install requirements from /Users/someuser/workspace/pants/3rdparty/python/requirements.txt.

This indicates that pants was attempting to `pip install` the `psutil` dependency into it's private
virtualenv, and that install failed due to a compiler issue. On Mac OS X, we recommend running
`xcode-select --install` to make sure you have the latest compiler infrastructure installed, and
unset any compiler-related environment variables (i.e. run `unset CC`).
