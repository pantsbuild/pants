Installing Pants
================

There are a few ways to get a runnable version of Pants set up for your workspace. Before
beginning, make sure your machine fits the requirements. At a minimum, Pants requires the following to run properly:

* Linux or macOS.
* Python 2.7 or 3.6.
* A C compiler, system headers, Python headers (to compile native Python modules) and the libffi
  library and headers (to compile and link modules that use CFFI to access native code).
* OpenJDK or Oracle JDK 7 or greater.
* Internet access (so that pants can fully bootstrap itself)

After you have pants installed, you'll need to
[[Set up your code workspace to work with Pants|pants('src/docs:setup_repo')]].

Recommended Installation
------------------------

To set up Pants in your repo, we recommend installing our self-contained `pants` bash script
in the root (i.e. the "buildroot") of your repo:

    :::bash
    curl -L -O https://pantsbuild.github.io/setup/pants && chmod +x pants

Start by running the below command to auto-generate a `pants.ini` config file with sensible defaults.

    :::bash
    ./pants generate-pants-ini

Running `./pants` for the first time will install the latest version of Pants, using virtualenv and first trying to use Python 3.6 and then falling back to Python 2.7. (Note that Pants 1.16.0 will be the last version to support Python 2.7.)

This command also pins the `pants_version`. When you'd like to upgrade Pants, just edit the version in `pants.ini` and `./pants` will self-update on the next run.

The script stores the various virtual environments you use centrally in
`~/.cache/pants/setup`. When you switch back and forth between different Pants versions
and different runtime Python versions, Pants will select the correct virtual environment
from your local cache and use that.

To use Pants plugins published to PyPi, add them to a `plugins` list, like so:

    :::ini
    [GLOBAL]
    pants_version: 1.15.0

    plugins: [
        'pantsbuild.pants.contrib.go==%(pants_version)s',
        'pantsbuild.pants.contrib.scrooge==%(pants_version)s',
      ]

Pants will notice you changed your plugins and will install them the next time you run `./pants`.

Note that the formatting of the plugins list is important; all lines below the `plugins:` line must be
indented by at least one white space to form logical continuation lines. This is standard for Python
ini files. See [[Options|pants('src/docs:options')]] for a guide on modifying your `pants.ini`.

The ./pants Runner Script
-------------------------

We highly recommend invoking pants via a checked-in runner script named `pants` in the
root of your workspace, as demonstrated above.  Pants uses the presence of such a file, in the
current working directory or in any of its ancestors, to detect the buildroot, e.g., when
invoked in a subdirectory.

If, for whatever reason, you don't want to run pants that way, you can also just check in an
empty file named `pants` to act as a sentinel for the buildroot.

Note that you can create whatever symlinks or extra wrapper scripts you like.  There's no absolute
requirement that pants be invoked directly via `./pants`.  All pants cares about is the existence
of a file named `pants` in the buildroot, and that file might as well be the runner script!

PEX-based Installation
----------------------
The virtualenv-based method is the recommended way of installing Pants.
However in cases where you can't depend on a local pants installation (e.g., your machines
prohibit software installation), some sites fetch a pre-built executable `pants.pex` using
the `pants_version` defined in `pants.ini`.  To upgrade pants, they generate a `pants.pex`
and upload it to a file server at a location computable  from the version number.
They then write their own `./pants` script that checks the `pants_version` in
`pants.ini` and download the appropriate pex from the file server to the correct spot.

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
