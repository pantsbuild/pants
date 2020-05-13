Installing Pants
================

There are a few ways to get a runnable version of Pants set up for your workspace. Before
beginning, make sure your machine fits the requirements. At a minimum, Pants requires the following to run properly:

* Linux or macOS.
* Python 3.6+.
* A C compiler, system headers, Python headers (to compile native Python modules) and the `libffi`
 library and headers (to compile and link modules that use CFFI to access native code).
* Internet access (so that Pants can fully bootstrap itself).

Additionally, if you use the JVM backend to work with Java or Scala code:

* OpenJDK or Oracle JDK version 8 or greater.

After you have Pants installed, you'll need to
[[Set up your code workspace to work with Pants|pants('src/docs:setup_repo')]].

Recommended Installation
------------------------

To set up Pants in your repo, we recommend installing our self-contained `pants` bash script
in the root (i.e. the "build root") of your repo:

    :::bash
    curl -L -O https://pantsbuild.github.io/setup/pants && chmod +x pants

To verify that Pants bootstraps correctly, run:

    :::bash
    ./pants --version

Now, run this command to create an initial `pants.toml` config file:

    :::bash
    printf "[GLOBAL]\npants_version = \"$(./pants --version)\"\n" > pants.toml

This config pins the `pants_version`. When you'd like to upgrade Pants, edit the version in `pants.toml` and `./pants` will self-update on the next run.

To use Pants plugins published to PyPI, add them to a `plugins` list, like so:

    :::toml
    [GLOBAL]
    pants_version = ...

    plugins: [
      "pantsbuild.pants.contrib.go==%(pants_version)s",
      "pantsbuild.pants.contrib.scrooge==%(pants_version)s",
    ]

Pants will notice you changed your plugins and will install them the next time you run `./pants`.

The ./pants Runner Script
-------------------------

We highly recommend invoking pants via a checked-in runner script named `pants` in the
root of your workspace, as demonstrated above. Pants uses the presence of such a file, in the
current working directory or in any of its ancestors, to detect the build root, e.g., when
invoked in a subdirectory.

If, for whatever reason, you don't want to run Pants that way, you can also just check in an
empty file named `BUILD_ROOT` to act as the sentinel for determining your project's build root.

PEX-based Installation
----------------------

The virtualenv-based method is the recommended way of installing Pants.
However in cases where you can't depend on a local pants installation (e.g., your machines
prohibit software installation), some sites fetch a pre-built executable `pants.pex` using
the `pants_version` defined in `pants.toml`.  To upgrade pants, they generate a `pants.pex`
and upload it to a file server at a location computable  from the version number.
They then write their own `./pants` script that checks the `pants_version` in
`pants.toml` and download the appropriate pex from the file server to the correct spot.

Troubleshooting
---------------

While pants is written in pure Python, some of its dependencies contain native code. Therefore,
you'll need to make sure you have the appropriate compiler infrastructure installed on the machine
where you are attempting to bootstrap pants. In particular, if you see an error similar to this:

    :::bash
    Installing setuptools, pip...done.
        Command "/Users/someuser/workspace/pants/build-support/pants_deps.venv/bin/python2.7 -c "import setuptools, tokenize;__file__='/private/var/folders/zc/0jhjvzy56s723lpq23q89f6c0000gn/T/pip-build-mZzSSA/psutil/setup.py';exec(compile(getattr(tokenize, 'open', open)(__file__).read().replace('\r\n', '\n'), __file__, 'exec'))" install --record /var/folders/zc/0jhjvzy56s723lpq23q89f6c0000gn/T/pip-iONF8p-record/install-record.txt --single-version-externally-managed --compile --install-headers /Users/someuser/workspace/pants/build-support/pants_deps.venv/bin/../include/site/python2.7/psutil" failed with error code 1 in /private/var/folders/zc/0jhjvzy56s723lpq23q89f6c0000gn/T/pip-build-mZzSSA/psutil

    Failed to install requirements from /Users/someuser/workspace/pants/3rdparty/python/requirements.txt.

This indicates that pants was attempting to `pip install` the `psutil` dependency into it's private
virtualenv, and that install failed due to a compiler issue. On macOS, we recommend running
`xcode-select --install` to make sure you have the latest compiler infrastructure installed, and
unset any compiler-related environment variables (i.e. run `unset CC`).
