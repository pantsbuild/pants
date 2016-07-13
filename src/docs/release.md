Release Process
===============

This page describes how to make a versioned release of Pants and and
other related packages to PyPi.  If you need to release pants jvm tools
(jars), see the
[[JVM Artifact Release Process|pants('src/docs:release_jvm')]]
page.

Deciding the "who", "what", and "when" of releasing is described on the
[[Release Strategy|pants('src/docs:release_strategy')]] page. Note that for some
lucky release managers, this may result in two or more releases in a particular week.

Once you know what to release, releasing pants involves:

-   Preparing the release.
-   (optional) Perform a release dry run.
-   Publishing the release to PyPi.
-   Announce the release on pants-devel.

Prerequisites
-------------

There are several things that require one-time setup in order to be
able to perform pants releases.  The release script checks that all
these steps have been performed in one way or another, but you might
like to go through this list ahead of time rather than have the release
script fail:

  - Create a pgp signing key if you don't already have one.

    You might use the gpg implemntation of pgp and start here:
    https://www.gnupg.org/gph/en/manual/c14.html

  - Configure git to use your pgp key for signing release tags.

    A description of the configuration can be found here:
    https://git-scm.com/book/tr/v2/Git-Tools-Signing-Your-Work#GPG-Introduction

  - Create a pypi account if you don't already have one.

    You can register here: https://pypi.python.org/pypi?%3Aaction=register_form
    Don't forget to include your pgp key id even though pypi considers
    this step optional.

  - Get your pypi account added as an `owner` for all pantsbuild.pants packages.

    You can ask any one of the [Owners](#owners) listed below to do this.
    Once this is done and you've performed your 1st release, add yourself to
    the [Owners](#owners) section below.

  - Configure your pypi credentials locally in `~/.pypirc`

    For some versions of python it's necessary to use both a `server-login` and
    `pypi` section containing the same info. This will do it:

        :::bash
        cat << EOF > ~/.pypirc && chmod 600 ~/.pypirc
        [pypi]
        username: <fill me in>
        password: <fill me in>

        [server-login]
        username: <fill me in>
        password: <fill me in>
        EOF

Prepare Release
---------------

Pants and the common libraries are published to the [Python Package
Index](https://pypi.python.org/pypi) per the Python community
convention.

Although the build and publish are automated, the version bumping, changelog edits,
and CONTRIBUTORS management are not. Changelog edits and CONTRIBUTOR updates always
occur in master, while version changes generally only occur in the relevant release branch.

1. In your release branch: Edit the version number in `src/python/pants/version.py`
2. When a `stable` branch is cut update `src/python/pants/notes/*.rst` and
  `src/python/pants/notes/master.rst` on the master branch to reflect changes captured in the stable
  branch.  For `dev` releases only update master.rst.  Future `stable` changes will be cherry-picked
  to the stable branch so master and stable will diverge, only requiring the branch specific notes
  to be updated.  You can run `./build-support/bin/release-changelog-helper.sh`
  to get a head-start creating the relevant changelog entries.
3. In master and the release branch if needed: Bring the CONTRIBUTORS roster in
[CONTRIBUTORS.md](https://github.com/pantsbuild/pants/tree/master/CONTRIBUTORS.md)
up to date by running `build-support/bin/contributors.sh`.

Finally, send these three changes out for review. If you are releasing from master, this will
be one review; if you are releasing from a stable branch, it will be two reviews.

Dry Run (Optional)
------------------

A dry run is not strictly required since CI includes one, but you might
like to try one anyway; if so, releases should only be published from
master, so get on master and ensure your version number commit is present.
After confirming this, run.

    :::bash
    $ ./build-support/bin/release.sh -n

This will perform a dry run local build of the pantsbuild.pants sdist
and other related package sdists, install them in a virtualenv and then
smoke test basic operations.

Note that in addition to CI checking dry runs work, the release publish
flow also performs a mandatory dry run so executing a dry run separately
is not required.

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

Finally, announce the release to pants-devel.  You can get a
contributor list for the email by running the following where `<tag>`
if the tag for the prior release (eg: release_0.0.33)

    :::bash
    $ ./build-support/bin/contributors.sh -s <tag>

Owners
------

The following folks are set up to publish to pypi for
pantsbuild.pants sdists:

Name              | Email                       | PYPI Usename
------------------|-----------------------------|---------------
John Sirois       | john.sirois@gmail.com       | john.sirois
Benjy Weinberger  | benjyw@gmail.com            | benjyw
Eric Ayers        | ericzundel@squareup.com     | ericzundel
Ity Kaul          | itykaul@gmail.com           | ity
Stu Hood          | stuhood@gmail.com           | stuhood
Patrick Lawson    | patrick.a.lawson@gmail.com  | Patrick.Lawson
Garrett Malmquist | garrett.malmquist@gmail.com | gmalmquist
Matt Olsen        | digwanderlust@gmail.com     | digiwanderlust
Mateo Rodriguez   | mateorod9@gmail.com         | mateor

And the current list of packages that these folks can release can
be obtained via:

    :::bash
    $ ./build-support/bin/release.sh -l

Right now that's:

- pantsbuild.pants
- pantsbuild.pants.contrib.android
- pantsbuild.pants.contrib.buildgen
- pantsbuild.pants.contrib.scrooge
- pantsbuild.pants.testinfra

You can run the following to get a full ownership roster for each
package :

    :::bash
    $ ./build-support/bin/release.sh -o
