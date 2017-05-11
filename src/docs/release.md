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

  - If using gpg, ensure that the gpg-agent is running (for OS X, see
    instructions [here](https://blog.chendry.org/2015/03/13/starting-gpg-agent-in-osx.html)),
    and ensure that gpg is set up to use it (e.g., set `use-agent` in `~/.gnupg/gpg.conf`).

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
        
  - Note that the release script expects your pantsbuild/pants git remote to be named `origin`.
    If you have another name for it, you should `git remote rename othername origin` before running
    the release script, and rename it back afterwards.

Prepare Release
---------------

Pants and the common libraries are published to the [Python Package
Index](https://pypi.python.org/pypi) per the Python community
convention.

Although the build and publish are automated, the version bumping, changelog edits,
and CONTRIBUTORS management are not. Changelog edits and CONTRIBUTOR updates always
occur in master, while version changes generally only occur in the relevant release branch.

Releasing from different release branches
-----------------------------------------
Every week we do a release from master.  In most cases we will use the `dev` naming convention
detailed in [Release Strategy](http://www.pantsbuild.org/release_strategy.html). When we are
ready to create a new stable branch we will release under the `rc` naming convention instead of
`dev`.  For example releases in master should look similar to the following: 1.1.0dev0, 1.1.0dev1,
1.1.0dev2, 1.1.0rc0, 1.2.0dev0, 1.2.0dev1, 1.2.0rc0, 1.3.0dev0. *In addition to a release from master
the release manager may also need to do a release from a stable branch.*

* ###Preparation for the release from the master branch
    1. Edit the version number in `src/python/pants/version.py`
    2. Update `src/python/pants/notes/master.rst` to reflect the changes for this week (can use
       `build-support/bin/release-changelog-helper.sh` to get a head start).
    3. If this release is also a release candidate then:
         * Create the corresponding notes file for that release, initialized with notes for all
           `dev` releases in the series. <br/>
           _For example if you were releasing `1.2.0rc0` you would need to
           create `src/python/pants/notes/1.2.x.rst` and include all `1.2.0devX` release notes._
         * Add the file to pants.ini in the branch_notes section.
         * Add the new notes file to `src/docs/docsite.json`.
         * Create a new page() in `src/python/pants/notes/BUILD` corresponding to the new notes. <br/>
       For additional information on generating documentation see the
       [docs reference](http://www.pantsbuild.org/docs#generating-the-site)
    4. Bring the CONTRIBUTORS roster (from master) in
       [CONTRIBUTORS.md](https://github.com/pantsbuild/pants/tree/master/CONTRIBUTORS.md)
       up to date by running `build-support/bin/contributors.sh`.
    5. Create and land a review for changes in the master branch.
    6. Execute the release as described later on this page.
    7. Finally, if creating a release candidate, create the stable branch from the commit in
       master for your release. For example if you were releasing `1.2.0rc0`, create the branch
       `1.2.x` from your release commit.

* ###Preparation for the release from the stable branch
  See [Release Strategy](http://www.pantsbuild.org/release_strategy.html) for more details about
  whether a release is needed from a stable branch.
    1. Cherry pick [changes labelled needs-rc-cherrypick](https://github.com/pantsbuild/pants/pulls?q=is%3Apr+label%3Aneeds-rc-cherrypick)
       directly to the stable branch.  Note that these pull requests must have been merged into master, and
       therefore will be closed.
    2. In master, update `src/python/pants/notes/*.rst` to reflect all patches that were
       cherry-picked (can use `build-support/bin/release-changelog-helper.sh` to get a head start).
       For example if you were releasing 1.2.0rc1 you would edit `src/python/pants/notes/1.2.x.rst`.
    3. Create and land a review for the notes changes in master.
    4. Cherry pick the merged notes changes from master to the release branch.
    5. In your release branch: edit and commit the version number in `src/python/pants/version.py`.
    6. Execute the release as described later on this page.
    7. Remove the `needs-rc-cherrypick` label from the changes cherry-picked into the new release.

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
