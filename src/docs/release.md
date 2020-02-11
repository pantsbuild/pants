Release Process
===============

This page describes how to make a versioned release of Pants and
other related packages to PyPI.  If you need to release pants jvm tools
(jars), see the
[[JVM Artifact Release Process|pants('src/docs:release_jvm')]]
page.

Deciding the "who", "what", and "when" of releasing is described on the
[[Release Strategy|pants('src/docs:release_strategy')]] page. Note that for some
lucky release managers, this may result in two or more releases in a particular week.

A release is always prepared for each pantsbuild/pants branch by a green Travis CI run; ie: master,
1.0.x, 1.1.x, etc. branches on [github.com/pantsbuild/pants](https://github.com/pantsbuild/pants) will have wheels created, tested
and deployed to [binaries.pantsbuild.org](https://binaries.pantsbuild.org) ready for use in a release.

Once you know what to release, releasing pants involves:

-   Preparing the release.
-   (optional) Perform a release dry run.
-   Publishing the release to PyPI.
-   Announce the release on pants-devel.

0. Prerequisites
----------------

There are several things that require one-time setup in order to be
able to perform pants releases.  The release script checks that all
these steps have been performed in one way or another, but you might
like to go through this list ahead of time rather than have the release
script fail:

  - **Create a pgp signing key** if you don't already have one.

    You likely want to use the [gpg implementation](https://www.gnupg.org) of pgp. On macOS, you can `brew install gpg`. Once `gpg` is installed, generate a new key: [www.gnupg.org/gph/en/manual/c14.html](https://www.gnupg.org/gph/en/manual/c14.html).
 
  - **Configure `git` to use your pgp key** for signing release tags: 
    [help.github.com/articles/telling-git-about-your-gpg-key/](https://help.github.com/articles/telling-git-about-your-gpg-key/)
    
    Note: the last step is required on macOS.

  - **Create a PyPI account** if you don't already have one: [pypi.org/account/register](https://pypi.org/account/register/).

  - **Get your PyPI account added as a `maintainer` for all pantsbuild.pants packages.** You can ask any one of the current [Owners](#owners) to do this.

  - **Configure your PyPI credentials locally in `~/.pypirc`**:

        :::bash
        cat << EOF > ~/.pypirc && chmod 600 ~/.pypirc
        [pypi]
        username: <fill me in>
        password: <fill me in>

        [server-login]
        username: <fill me in>
        password: <fill me in>
        EOF

1. Prepare Release
------------------

Pants and the common libraries are published to the [Python Package
Index](https://pypi.org/pypi) per the Python community
convention.

Although the build and publish are automated, the version bumping, changelog edits,
and CONTRIBUTORS management are not. Changelog edits and CONTRIBUTOR updates always
occur in master, while version changes generally only occur in the relevant release branch.

### Releasing from different release branches

Every week we do a release from master.  In most cases we will use the `dev` naming convention
detailed in [Release Strategy](http://www.pantsbuild.org/release_strategy.html). When we are
ready to create a new stable branch we will release under the `rc` naming convention instead of
`dev`.  For example releases in master should look similar to the following: `1.1.0.dev0`, `1.1.0.dev1`,
`1.1.0.dev2`, `1.1.0rc0`, `1.2.0.dev0`, `1.2.0.dev1`, `1.2.0rc0`, `1.3.0.dev0`. *In addition to a release
from master the release manager may also need to do a release from a stable branch.*

#### Preparing a release from the master branch

1. Edit the version number in `src/python/pants/VERSION`
2. Update `src/python/pants/notes/master.rst` to reflect the changes for this week (can use
   `build-support/bin/release-changelog-helper.sh` to get a head start).
3. If this release is also a release candidate then:
     * Create the corresponding notes file for that release, initialized with notes for all
       `dev` releases in the series. <br/>
       _For example if you were releasing `1.2.0rc0` you would need to
       create `src/python/pants/notes/1.2.x.rst` and include all `1.2.0.devX` release notes._
     * Create a new page() in `src/python/pants/notes/BUILD` corresponding to the new notes.
     * Add the file to pants.ini in the branch_notes section.
     * Add the new notes file to `src/docs/docsite.json` in a few places.
     * Check that the new notes are visible on the docsite by previewing it using
       the [docs reference](http://www.pantsbuild.org/docs#generating-the-site) instructions.
4. Bring the CONTRIBUTORS roster in
   [CONTRIBUTORS.md](https://github.com/pantsbuild/pants/tree/master/CONTRIBUTORS.md)
   up to date by running `./build-support/bin/contributors.sh`.
5. Create and land a review for changes in the master branch.
6. Execute the release as described later on this page.
7. Finally, if creating a release candidate, create the stable branch from the commit in
   master for your release. For example if you were releasing `1.2.0rc0`, create the branch
   `1.2.x` from your release commit.

#### Preparing a release from a stable branch

See [Release Strategy](http://www.pantsbuild.org/release_strategy.html) for more details about
whether a release is needed from a stable branch.

1. Cherry pick [changes labelled needs-cherrypick][needs-cherrypick]
    for the relevant milestone directly to the stable branch.  Note that these pull requests must have been merged into
    master, and therefore will already be closed.
2. In master, update the branch-specific file in `src/python/pants/notes` to reflect all patches that were
    cherry-picked (can use `build-support/bin/release-changelog-helper.sh` to get a head start).
    For example if you were releasing 1.2.0rc1 you would edit `src/python/pants/notes/1.2.x.rst`.
3. Create and land a review for the notes changes in master.
4. Cherry pick the merged notes changes from master to the release branch.
5. In your release branch: edit and commit the version number in `src/python/pants/VERSION`.
6. Manually publish the release notes pages by checking out master and running `build-support/bin/publish_docs.sh -p`.
7. Execute the release as described later on this page.
8. Remove the [needs-cherrypick][needs-cherrypick] label from the changes cherry-picked into the new release.

2. (Optional) Dry Run
---------------------

A dry run is not strictly required since CI includes one, but you might
like to try one anyway. To do so, switch to your release branch (which will either be `master` for
an unstable weekly release, or a release branch like `1.9.x` for a stable release), and ensure that
your version number commit is present. After confirming this, run:

    :::bash
    $ ./build-support/bin/release.sh -n

This will perform a dry run local build of the pantsbuild.pants wheel
and other related package wheelss, install them in a virtualenv and then
smoke test basic operations.

Note that in addition to CI checking dry runs work, the release publish
flow also performs a mandatory dry run so executing a dry run separately
is not required.

3. Publish to PyPI
------------------

Once the two "Build wheels" Travis shards have completed for your release
commit, you can publish to PyPI. First, ensure that you are on your release branch at your version
bump commit. Then, publish the release:

    :::bash
    $ ./build-support/bin/release.sh

This also performs a dry run and then proceeds to upload the smoke
tested wheels to PyPI. It may take a few minutes for the packages to be downloadable.

Note: If you are releasing from `master` and new commits have landed after your release commit, you
can reset to your commit (`git reset --hard <sha>`) before publishing.

4. Announce
-----------

Check PyPI to ensure everything looks good. The [pantsbuild.pants
package index page](https://pypi.org/pypi/pantsbuild.pants)
should display the package version you just uploaded. The same check
applies to other related package PyPI pages.

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

<a name="owners"></a>Listing Packages and Owners
------

The current list of packages can be obtained via :

    :::bash
    $ ./build-support/bin/release.sh -l

You can run the following to get a full ownership roster for each
package :

    :::bash
    $ ./build-support/bin/release.sh -o

We generally expect all packages to have the same set of owners, which you can
view [here](https://pypi.org/project/pantsbuild.pants/).

[needs-cherrypick]: https://github.com/pantsbuild/pants/pulls?q=is%3Apr+label%3Aneeds-cherrypick
