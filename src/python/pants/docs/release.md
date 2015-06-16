Release Process
===============

This page describes how to make a versioned release of Pants and and
other related packages to PyPi.  If you need to release pants jvm tools
(jars), see the
[[JVM Artifact Release Process|pants('src/python/pants/docs:release_jvm')]]
page.

At a high level, releasing pants involves:

-   Deciding what/when to release. At present this is ad-hoc, typically
    when a change has been made and the author wants to use a version
    incorporating that change. Things are likely to remain this way pre
    1.0.0.
-   Preparing the release.
-   (optional) Perform a release dry run.
-   Publishing the release to PyPi.
-   Announce the release on pants-devel.

The current list of packages that are part of this release process:

-   pantsbuild.pants
-   pantsbuild.pants.backend.android
-   pantsbuild.pants.contrib.buildgen
-   pantsbuild.pants.contrib.scrooge
-   pantsbuild.pants.contrib.spindle
-   pantsbuild.pants.testinfra

Prepare Release
---------------

Pants and the common libraries are published to the [Python Package
Index](https://pypi.python.org/pypi) per the Python community
convention.

Although the build and publish are automated, the version bumping and
CHANGELOG  and CONTRIBUTORS management are not.

You'll need to edit the version number in
[src/python/pants/version.py](https://github.com/pantsbuild/pants/tree/master/src/python/pants/version.py)
and add an entry in the CHANGELOG at
[src/python/pants/CHANGELOG.rst](https://github.com/pantsbuild/pants/tree/master/src/python/pants/CHANGELOG.rst).
You can run `./build-support/bin/release-changelog-helper.sh` to get a
head-start on the CHANGELOG entry.

To bring the CONTRIBUTORS roster in
[CONTRIBUTORS.md](https://github.com/pantsbuild/pants/tree/master/CONTRIBUTORS.md)
up to date you just run `build-support/bin/contributors.sh`.

Finally, send these three changes out for review.

Dry Run
-------

In order to publish the prepared release you'll need to be a
pantsbuild.pants package owner; otherwise you'll need to hand off to
someone who is. The list is on the [pantsbuild.pants package index
page](https://pypi.python.org/pypi/pantsbuild.pants) in the
Package Index Owner field:

    :::bash
    $ curl -s "https://pypi.python.org`(curl -s https://pypi.python.org/pypi/pantsbuild.pants | grep -oE  "/pypi/pantsbuild.pants/[0-9]*\.[0-9]*\.[0-9]*" | head -n1)`" | grep -A1 "Owner"
    <strong>Package Index Owner:</strong>
    <span>john.sirois, benjyw, traviscrawford, ericzundel, ity</span>

All the other packages that are part of this simultaneous release
process must have the same owner list or the release script would break.

Releases should only be published from master, so get on master and
ensure your version number commit is present. After confirming this,
publish locally and verify the release.

    :::bash
    $ ./build-support/bin/release.sh -n

This will perform a dry run local build of the pantsbuild.pants sdist
and other related package sdists, install them in a virtualenv and then
smoke test basic operations.

Note that the release publish flow also performs a mandatory dry run so
executing a dry run separately is not required.

Publish to PyPi
---------------

Now that we've smoke-tested this release, we can publish to PyPi:

    :::bash
    $ ./build-support/bin/release.sh

This also performs a dry run and then proceeds to upload the smoke
tested sdists to PyPi.

Announce
--------

Check PyPi to ensure everything looks good. The [pantsbuild.pants
package index page](https://pypi.python.org/pypi/pantsbuild.pants)
should display the package version you just uploaded. The same check
applies to other related package PyPi pages.

To test the packages are installable:

    :::bash
    $ ./build-support/bin/release.sh -t

This will attempt to install the just-published packages from pypi and
then smoke test them.

Finally, announce the release to pants-devel.

