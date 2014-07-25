###############
Release Process
###############

This page describes how to make a versioned release of Pants.

At a high level, releasing pants involves:

* Deciding what/when to release. At present this is ad-hoc, typically when
  a change has been made and the author wants to use a version incorporating
  that change. Things are likely to remain this way pre 1.0.0.
* Preparing the release.
* (optional) Perform a release dry run.
* Publishing the release to PyPi.
* Announce the release on `pants-devel`.

***************
Prepare Release
***************

Pants and the common libraries are published to the
`Python Package Index <https://pypi.python.org/pypi>`_ per the Python
community convention.

Although the build and publish are automated, the version bumping and CHANGELOG management are not.
You'll need to edit the version number in `src/python/pants/version.py
<https://github.com/pantsbuild/pants/tree/master/src/python/pants/version.py>`_ and add an entry in
the CHANGELOG at `src/python/pants/CHANGELOG.rst
<https://github.com/pantsbuild/pants/tree/master/src/python/pants/CHANGELOG.rst>`_ then send this
out for review.

*******
Dry Run
*******

In order to publish the prepared release you'll need to be a pantsbuild.pants package owner;
otherwise you'll need to hand off to someone who is.  The list is on the
`pantsbuild.pants package index page <https://pypi.python.org/pypi/pantsbuild.pants>`_ in the
`Package Index Owner` field::

   curl -s https://pypi.python.org/pypi/pantsbuild.pants | grep -A1 "Owner"
   <strong>Package Index Owner:</strong>
   <span>john.sirois, benjyw, traviscrawford, ericzundel</span>

Releases should only be published from master, so get on master and ensure your version number
commit is present. After confirming this, publish locally and verify the release. ::

   ./build-support/bin/release.sh -n

This will perform a dry run local build of the pantsbuild.pants sdist, install it in a virtualenv
and then smoke test basic operation.

Note that the release publish flow also performs a mandatory dry run so executing a dry run
separately is not required.

***************
Publish to PyPi
***************

Now that we've smoke-tested this release, we can publish to PyPi::

   ./build-support/bin/release.sh

This also performs a dry run and then proceeds to upload the smoke tested sdist to PyPi.

********
Announce
********

Check PyPi to ensure everything looks good. The `pantsbuild.pants package index page
<https://pypi.python.org/pypi/pantsbuild.pants>`_ should display the package version you just
uploaded. To test the package is installable::

  ./build-support/bin/release.sh -t

This will attempt to install the just-published package from pypi and then smoke test it.

Finally, announce the release to `pants-devel`.
