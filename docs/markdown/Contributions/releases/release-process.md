---
title: "Release process"
slug: "release-process"
excerpt: "How to release a new version of `pantsbuild.pants` and its plugins."
hidden: false
createdAt: "2020-05-16T22:36:48.334Z"
updatedAt: "2022-06-08T18:06:57.112Z"
---
This page covers the nitty-gritty of executing a release, and is probably only interesting for maintainers. If you're interested in when and why Pants is released, please see the [Release strategy](doc:release-strategy) page.

Prerequisites
-------------

### 1. Create a PGP signing key

If you already have one, you can reuse it.

You likely want to use the gpg implementation of pgp. On macOS, you can `brew install gpg`. Once gpg is installed, generate a new key: <https://docs.github.com/en/github/authenticating-to-github/generating-a-new-gpg-key>.

Please use a password for your key!

### 2. Add your PGP key to GitHub.

See <https://docs.github.com/en/github/authenticating-to-github/adding-a-new-gpg-key-to-your-github-account>.

### 3. Configure Git to use your PGP key.

See <https://docs.github.com/en/github/authenticating-to-github/telling-git-about-your-signing-key>.

Note: the last step is required on macOS.

### 4. Create a PyPI account

[pypi.org/account/register](https://pypi.org/account/register).

Please enable two-factor authentication under "Account Settings".

Generate an API token under "Account Settings" for all projects. Copy the token for the last step.

### 5. Get added to pantsbuild.pants PyPI

You can ask any of the current Owners to add you as a maintainer.

### 6. Configure `~/.pypirc`

Fill in with your PyPI token by running:

```bash
$ cat << EOF > ~/.pypirc && chmod 600 ~/.pypirc
[pypi]
username: __token__
password: <fill me in>

[server-login]
username: __token__
password: <fill me in>

EOF
```

### 7. Authenticate with the Github API

Ensure that you have a [personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token) for your Github account in your `.netrc` file.

```
machine api.github.com
    login <username>
    password <token>
```

Step 1: Prepare the release
---------------------------

The release is automated, outside of these steps:

1. Removing any completed deprecations
2. Changelog preparation
3. CONTRIBUTOR.md updates
4. Version bumping

The first three steps always happen in the `main` branch, whereas the version bump happens in the relevant release branch. 

For `dev` and `a0` releases, the release branch is `main`. For all other release candidates and stable releases, the release branch is that respective version's branch, e.g. `2.8.x` or `2.9.x`.

### 0a. `dev0` - set up the release series

1. Create a new file in ` src/python/pants/notes`, e.g. create  `src/python/pants/notes/2.9.x.md`.
   1. Copy the title and template over from the prior release, e.g. `2.8.x.md`.
2. Add the new file to `pants.toml` in the `release_notes` section.

### 0b. `dev` - Check for any deprecations

Your release will fail if there are any deprecated things that should now be removed. Usually, the person who deprecated the feature should have already removed the stale code, but they may have forgotten.

To check for this, search for the version you are releasing. For example, with [ripgrep](https://github.com/BurntSushi/ripgrep), run `rg -C3 2.9.0.dev0`.

If there are things that must be removed, you can either:

1. Ping the person who made the deprecation to ask them to remove it.
2. Remove it yourself, either in the release prep or as a precursor PR.
3. Bump the removal date back by one dev release.

### 0c. Release candidates - cherry-pick relevant changes

Cherry-pick all changes labeled `needs-cherrypick` with the relevant milestone for the stable branch, e.g. the milestone `2.9.x`. 

These pull requests must have been merged into main first, so they will already be closed.

To cherry-pick, for example, from 2.9.x:

1. `git fetch https://github.com/pantsbuild/pants 2.9.x`
2. `git checkout -b <new-branch-name> FETCH_HEAD`
3. Find the commit SHA by running `git log main` or looking in GitHub: <https://github.com/pantsbuild/pants/commits/main>.
4. `git cherry-pick <sha>`, using the SHA from the previous step.
5. Open a pull request to merge into the release branch, e.g. `2.9.x`.

Do not push directly to the release branch. All changes should be added through a pull request.

After a commit has been cherry-picked, remove the `needs-cherrypick` label and remove it from the release milestone.

### 1. Prepare the changelog

Update the release page in `src/python/pants/notes` for this release series, e.g. update `src/python/pants/notes/2.9.x.md`.

Run `git fetch --all --tags` to be sure you have the latest release tags available locally.

From the `main` branch, run `./pants run build-support/bin/changelog.py -- --prior 2.9.0.dev0 --new 2.9.0.dev1` with the relevant versions. 

This will generate the sections to copy into the release notes. Delete any empty sections. Do not paste the `Internal` section into the notes file. Instead, paste into a comment on the prep PR.

You are encouraged to fix typos and tweak change descriptions for clarity to users. Ensure that there is exactly one blank line between descriptions, headers etc.

> 🚧 Reminder: always do this against the `main` branch
> 
> Even if you are preparing notes for a release candidate, always prepare the notes in a branch based on `main` and, later, target your PR to merge with `main`.

> 📘 See any weird PR titles?
> 
> Sometimes, committers accidentally use the wrong title when squashing and merging because GitHub pulls the title from the commit title when there is only one commit. 
> 
> If you see a vague or strange title like "fix bug", open the original PR to see if the PR title is more descriptive. If it is, please use the more descriptive title instead.

### 2. Update `CONTRIBUTORS.md`

Run `./pants run build-support/bin/contributors.py`

Take note of any new contributors since the last release so that you can give a shoutout in the announcement email.

If this is a stable release, then you can use `git diff` to find all new contributors since the previous stable release, to give them all a shoutout in the stable release email. E.g.,

```
git diff release_2.8.0..release_2.9.0 CONTRIBUTORS.md
```

### 3. `dev` and `a0` - bump the `VERSION`

Change `src/python/pants/VERSION` to the new release, e.g. `2.12.0.dev0`. If you encounter an `a0` version on `main`, then the next release will be for a new release series (i.e. you'll bump from `2.12.0a0` to `2.13.0.dev0`).

### 4. Post the prep to GitHub

Open a pull request on GitHub to merge into `main`. Post the PR to the `#development` in Slack.  

Merge once approved and green.

> 🚧 Watch out for any recently landed PRs
> 
> From the time you put up your release prep until you hit "merge", be careful that no one merges any commits into main. 
> 
> If they do—and you're doing a `dev` or `a0` release—you should merge `main` into your PR and update the changelog with their changes. It's okay if the changes were internal only, but any public changes must be added to the changelog.
> 
> Once you click "merge", it is safe for people to merge changes again.

### 5a. `a0` - create a new Git branch

For example, if you're releasing `2.9.0a0`, create the branch `2.9.x` by running the below. Make sure you are on your release commit before doing this.

```bash
$ git checkout -b 2.9.x
$ git push upstream 2.9.x
```

### 5b. release candidates - cherry-pick and bump the VERSION

1. Checkout from `main` into the release branch, e.g. `2.9.x`.
2. Cherry-pick the release prep using `git cherry-pick <sha>`.
3. Bump the `VERSION` in `src/python/pants/VERSION`, e.g. to `2.9.0rc1`. Push this as a new commit directly to the release branch - you do not need to open a pull request.

Step 2: Update this docs site
-----------------------------

### `dev0` - set up the new version

Go to the [documentation dashboard](https://dash.readme.com/). In the top left dropdown, where it says the current version, click "Manage versions". Click "Add new version" and use a "v" with the minor release number, e.g. "v2.9". Fork from the prior release. Mark this new version as public by clicking on "Is public?"

Also, update the [Changelog](doc:changelog) page with the new release series at the top of the table. It's okay if there are no "highlights" yet.

### Regenerate the references

On the relevant release branch, run `./pants run build-support/bin/generate_docs.py -- --sync --api-key <key>` with your key from <https://dash.readme.com/project/pants/v2.8/api-key>.

### `stable` releases - Update the default docsite

The first stable release of a branch should update the "default" version of the docsite. For example: when releasing the stable `2.9.0`, the docsite would be changed to pointing from `v2.8` to pointing to `v2.9` by default.

Also, update the [Changelog](doc:changelog)'s "highlights" column with a link to the blog summarizing the release. See the section "Announce the release" below for more info on the blog.

> 🚧 Don't have edit access?
> 
> Ping someone in the `#maintainers-confidential` channel in Slack to be added. Alternatively, you can "Suggest edits" in the top right corner.

Step 3: Wait for CI to build the wheels
---------------------------------------

Once you have merged the `VERSION` bump—which will be on `main` for `dev` and `a0` releases and the release branch for release candidates—CI will start building the wheels you need to finish the release.

Head to <https://github.com/pantsbuild/pants/actions> and find your relevant build. You need the "Build wheels and fs_util" jobs to pass.

Step 4: Run `release.sh`
------------------------

First, ensure that you are on your release branch at your version bump commit.

> 📘 Tip: if new commits have landed after your release commit
> 
> You can reset to your release commit by running `git reset --hard <sha>`.

Then, run:

```bash
./build-support/bin/release.sh publish
```

This will first download the pre-built wheels built in CI and will publish them to PyPI. About 2-3 minutes in, the script will prompt you for your PGP password.

We also release a Pants Pex via GitHub releases. Run this:

```bash
PANTS_PEX_RELEASE=STABLE ./build-support/bin/release.sh build-universal-pex
```

Then go to <https://github.com/pantsbuild/pants/tags>, find your release's tag, click `Edit tag`, and upload the PEX located at `dist/pex.pants.<version>.pex`.

Step 5: Test the release
------------------------

Run this script as a basic smoke test:

```bash
./build-support/bin/release.sh test-release
```

You should also [check PyPI](https://pypi.org/pypi/pantsbuild.pants) to ensure everything looks good. Click "Release history" to find the version you released, then click it and confirm the changelog is correct on the "Project description" page and that the `macOS` and `manylinux` wheels show up in the "Download files" page. 

Step 6: Announce the change
---------------------------

Announce the release to:

1. the [pants-devel](https://groups.google.com/forum/#!forum/pants-devel) list
2. the `#announce` channel in Slack

### Sample emails for `pants-devel`

You can get a contributor list by running the following, where `<tag>` is the tag for the prior release (eg: `release_2.9.0.dev0`):

```bash
./pants run ./build-support/bin/contributors.py -- -s <tag>
```

> ❗️ Update the links in these templates!
> 
> When copy pasting these templates, please always check that all versions match the relevant release. When adding a link, use "Test this link" to ensure that it loads properly.

#### Dev release

If the release series' `.dev0` has already been released, reply to that email thread for the rest of the `dev` releases.

> Subject: [dev release] pantsbuild.pants 2.9.0.dev0
>
> The first weekly dev release for the `2.9` series is now available [on PyPI](https://pypi.org/project/pantsbuild.pants/2.9.0.dev0/)! Please visit the release page to see the changelog.
>
> Thank you to this week's contributors:
>
>  Eustolia Palledino
>  Ahmad Wensel
>  Rae Efird
>  Niki Fitch
>
> And a special shout-out to first-time contributor Niki Fitch, with the PR [`Upgrade Rust to 1.63 (#9441)`](https://github.com/pantsbuild/pants/pull/9441). Thank you for your contribution!
>
> _(For more information on how Pants is released, please see the [release strategy](https://www.pantsbuild.org/docs/release-strategy) page.)_

#### Alpha release

Reply to the email thread for the series' `dev` releases.

> Subject: [alpha release] pantsbuild.pants 2.9.0a0
>
> The first alpha release for `2.9.0` is now available [on PyPI](https://pypi.org/project/pantsbuild.pants/2.9.0a0/)! Please visit the release page to see the changelog.
>
> Although alpha releases have not received any vetting beyond what a `dev` release receives, they are the first release for their stable branch, and are worth trying out to help report bugs before we start release candidates.
>
> Thank you to everyone who contributed patches in this cycle!
>
>  Niki Fitch
>  Mario Rozell
>
> _(For more information on how Pants is released, please see the [release strategy](https://www.pantsbuild.org/docs/release-strategy) page.)_

#### Release candidate

Create a new email thread for `rc0`. For other `rc`s, reply to the email thread for the rest of the patch's release candidates. That is, bundle `2.9.0` release candidates together, and `2.8.1` candidates together, etc.

> Subject: [release candidate] pantsbuild.pants 2.9.0rc1
>
> The second release candidate for `2.9.0` is now available [on PyPI](https://pypi.org/project/pantsbuild.pants/2.9.0rc1/)! Please visit the release page to see the changelog.
>
> Thank you to everyone who tested the previous release, and thank you to the folks who contributed patches!
>
>  Niki Fitch
>  Mario Rozell
>
> _(For more information on how Pants is released, please see the [release strategy](https://www.pantsbuild.org/v2.11/docs/release-strategy) page.)_

#### Stable release

For the first stable release in the series, first, write a blog post to summarize the series using <https://pants.ghost.io/ghost/#/site>. Please coordinate by posting to #development in Slack. If writing is not your thing, you can ask in `#maintainers` or `#development` if another Pants contributor would be willing to write the blog.

> Subject: [stable release] pantsbuild.pants 2.9.0
>
> The first stable release of the `2.9` series is now available [on PyPI](https://pypi.org/project/pantsbuild.pants/2.9.0/)!
>
> See our [blog post](https://blog.pantsbuild.org/introducing-pants-build-2-9-0/) summarizing the release series, or the more detailed changelog on the release page.
>
> Thanks to all of the contributors to the 2.9 series!
>
> Eustolia Palledino
> Ahmad Wensel
> Rae Efird
> Niki Fitch
> Mario Rozell
>
> _(For more information on how Pants is released, please see the [release strategy](https://www.pantsbuild.org/docs/release-strategy) page.)_
