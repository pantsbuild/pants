###############
Release Process
###############

This page describes how to make a versioned release of Pants.

At a high level, releasing pants involves:

* Deciding what/when to release. At present this is ad-hoc, typically when
  a change has been made and the author wants to use a version incorporating
  that change. Things are likely to remain this way pre 1.0.0.
* Preparing the release.
* Testing the release.
* Publishing the release to PyPi.
* Announce the release on `pants-devel`.

***************
Prepare Release
***************

Pants and the common libraries are published to the
`Python Package Index <https://pypi.python.org/pypi>`_ per the Python
community convention.

Although the build and publish are automated, the version bumping is not. You'll need to edit the
version number in `src/python/pants/version.py
<https://github.com/pantsbuild/pants/tree/master/src/python/pants/version.py>`_ and then send this
out for review.

************
Test Release
************

In order to publish the prepared release you'll need to be a pantsbuild.pants package owner;
otherwise you'll need to hand off to someone who is.  The list is on the
`pantsbuild.pants package index page <https://pypi.python.org/pypi/pantsbuild.pants>`_ in the
`Package Index Owner` field::

   curl -s https://pypi.python.org/pypi/pantsbuild.pants | grep -A1 "Owner"
   <strong>Package Index Owner:</strong>
   <span>john.sirois, benjyw, traviscrawford, ericzundel</span>

Releases should only be published from master, so get on master and ensure your version number
and CHANGELOG commit is present. After confirming this, publish locally and verify the release. ::

   PANTS_DEV=1 ./pants setup_py --recursive src/python/pants:pants-packaged
   VENV_DIR=$(mktemp -d -t pants.XXXXX)
   ./build-support/virtualenv $VENV_DIR
   source $VENV_DIR/bin/activate
   pip install --find-links=file://$(pwd)/dist \
     pantsbuild.pants==$(PANTS_DEV=1 ./pants --version 2>/dev/null)
   pants goal list :: && pants --version
   deactivate

You should get a listing of targets in the repo and finally the version number you expect to be
releasing, for example::

   ...
   tests/python/pants_test/testutils:testutils
   tests/scala/com/pants/example/hello/welcome:welcome
   0.0.18

***************
Publish to PyPi
***************

Now that we've smoke-tested this release, we can publish to PyPi::

   PANTS_DEV=1 ./pants setup_py --recursive --run='sdist upload' \
     src/python/pants:pants-packaged

********
Announce
********

Check PyPi to ensure everything looks good. Finally, announce the release to `pants-devel`.
