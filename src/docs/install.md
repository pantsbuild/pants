Installing Pants
================

There are a few ways to get a runnable version of pants set up for your workspace. Before
beginning, make sure your machine fits the requirements. At a minimum, pants requires the following to run properly:

* Linux or Mac OS X
* Python 2.7.x (the latest stable version of 2.7 is recommended)
* A C compiler, system headers, Python headers (to compile native Python modules)
* OpenJDK 7 or greater, Oracle JDK 6 or greater
* Internet access (so that pants can fully bootstrap itself)

After you have pants installed, you'll need to
[[Set up your code workspace to work with Pants|pants('src/docs:setup_repo')]].

Recommended Installation
------------------------

To set up pants in your repo, we recommend installing our self-contained `pants` bash script
in the root (ie, "buildroot") of your repo:

      :::bash
      curl -L -O https://pantsbuild.github.io/setup/pants && chmod +x pants && touch pants.ini

The first time you run the new `./pants` script it will install the latest version of pants (using
virtualenv) and then run it.  It's recommended though, that you pin the version of pants.  To do
this, first find out the version of pants you just installed:

      :::bash
      ./pants -V
      1.0.0

Then add an entry like so to `pants.ini` with that version:

      :::ini
      [GLOBAL]
      pants_version: 1.0.0

When you'd like to upgrade pants, just edit the version in `pants.ini` and pants will self-update on
the next run.  This script stores the various pants versions you use centrally in
`~/.cache/pants/setup`.  When you switch back and forth between branches pants will select the
correct version from your local cache and use that.

If you use pants plugins published to pypi you can configure them by adding a `plugins` list as
follows:

      :::ini
      [GLOBAL]
      pants_version: 1.0.0

      plugins: [
          'pantsbuild.pants.contrib.go==%(pants_version)s',
          'pantsbuild.pants.contrib.scrooge==%(pants_version)s',
        ]

Pants notices you changed your plugins and it installs them.
NB: The formatting of the plugins list is important; all lines below the `plugins:` line must be
indented by at least one white space to form logical continuation lines. This is standard for python
ini files, see [[Options|pants('src/docs:options')]].

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
virtualenv, and that install failed due to a compiler issue. On Mac OS X, we recommend running
`xcode-select --install` to make sure you have the latest compiler infrastructure installed, and
unset any compiler-related environment variables (i.e. run `unset CC`).
