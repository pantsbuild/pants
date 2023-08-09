---
title: "Release process"
slug: "release-process"
excerpt: "How to release a new version of `pantsbuild.pants` and its plugins."
hidden: false
createdAt: "2020-05-16T22:36:48.334Z"
---
This page covers the nitty-gritty of executing a release, and is probably only interesting for maintainers. If you're interested in when and why Pants is released, please see the [Release strategy](doc:release-strategy) page.

Prerequisites
-------------

You only need to set these up once.

### Create a PGP signing key

If you already have one, you can reuse it.

You likely want to use the gpg implementation of pgp. On macOS, you can `brew install gpg`. Once gpg is installed, generate a new key: <https://docs.github.com/en/github/authenticating-to-github/generating-a-new-gpg-key>.

Please use a password for your key!

### Add your PGP key to GitHub.

See <https://docs.github.com/en/github/authenticating-to-github/adding-a-new-gpg-key-to-your-github-account>.

### Configure Git to use your PGP key.

See <https://docs.github.com/en/github/authenticating-to-github/telling-git-about-your-signing-key>.

Note: the last step is required on macOS.

### Authenticate with the Github API

Ensure that you have a [personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token) for your Github account in your `.netrc` file.

```
machine api.github.com
    login <username>
    password <token>
```

Step 0: Preliminaries
---------------------

### `dev` - Check for any deprecations
If this is a dev release, ensure that deprecations set to expire in the released version have been removed. To check for this, search the code for the version you're releasing. For example, `git grep 2.9.0.dev0`.

If there is deprecated code that must be removed, you can either:

1. Ping the person who made the deprecation to ask them to remove it.
2. Remove it yourself, in a precursor PR.
3. Bump the deprecation removal target back by one dev release.

### `rc` - Check for cherry-picks
If this is a release candidate, ensure that pending cherry-picks have been applied in the release branch. Cherry-picks are usually applied automatically, but this may not always succeed, so [check for any pending cherry-picks](https://github.com/pantsbuild/pants/pulls?q=is%3Apr+label%3Aneeds-cherrypick+is%3Aclosed), and find the relevant ones by looking at the milestone: for instance, if doing a release for 2.16, the relevant cherry-picks are those for milestone `2.16.x` or earlier.

The process may fail in one of two ways:

- The cherry-picking process failed, and tagged the PR with `auto-cherry-picking-failed`: follow the instructions in the comment on the pull request. (This likely means there are merge conflicts that require manual resolution.)
- the cherry-pick hasn't (yet) run: trigger the automation manually by going to [the GitHub Action](https://github.com/pantsbuild/pants/actions/workflows/auto-cherry-picker.yaml), clicking on the "Run workflow" button, and providing the PR number.

Step 1: Create the release commit
---------------------------------

The release commit is the commit that bumps the VERSION string. For `dev`/`a0` releases this happens in the `main` branch, in the same commit that updates the release notes and the `CONTRIBUTORS.md` file. For `rc` and stable releases, this happens in the relevant stable branch (while the release notes are still updated on `main`).

### `dev0` - set up the new release series

If this is the first dev release in a new series:

1. Create a new file in ` src/python/pants/notes`, e.g. create  `src/python/pants/notes/2.9.x.md`.
   1. Copy the title and template over from the prior release, e.g. `2.8.x.md`.
2. Add the new file to `pants.toml` in the `release_notes` section.

### Generate the release notes
From the `main` branch, run `pants run src/python/pants_release/start_release.py -- --new 2.9.0.dev1 --release-manager your_github_username --publish` with the relevant version and your own GitHub username.

This will create a pull request that:

1. updates release notes (remember to check over the changes and follow the instructions in the PR to make any updates)
2. updates `CONTRIBUTORS.md`
3. bumps the `VERSION` on `main`, if appropriate

> 🚧 Reminder: always do this against the `main` branch
>
> Even if you are preparing notes for a release candidate, always prepare the notes in a branch based on `main` and, later, target your PR to merge with `main`.

### Merge the pull request

Post the PR to the `#development` channel in Slack. Merge once approved and green.

> 🚧 Watch out for any recently landed PRs
>
> From the time you put up your release prep until you hit "merge", be careful that no one merges any commits into main.
>
> If they do—and you're doing a `dev` or `a0` release—you should merge `main` into your PR and update the changelog with their changes. It's okay if the changes were internal only, but any public changes must be added to the changelog.
>
> Once you click "merge", it is safe for people to merge changes again.

### `a0` - create a new Git branch

If you're releasing an `a0` release, you must create the stable branch for that version.

For example, if you're releasing `2.9.0a0`, create the branch `2.9.x` by running the command below. Make sure you are on your release commit before doing this.

```bash
$ git checkout -b 2.9.x
$ git push upstream 2.9.x
```

### Release candidates - cherry-pick and bump the VERSION

If you're releasing a release candidate, your release notes PR above did not bump the VERSION on main. You must bump it in the release branch.

1. Checkout from `main` into the release branch, e.g. `2.9.x`.
2. Cherry-pick the release notes prep into the release branch using `git cherry-pick <sha>`.
3. Bump the `VERSION` in `src/python/pants/VERSION`, e.g. to `2.9.0rc1`. Push this as a new commit directly to the release branch - you do not need to open a pull request.

Step 2: Update this docs site
-----------------------------

Note that this step can currently only be performed by a subset of maintainers due to a paid maximum number of seats. If you do not have a readme.com account, contact someone in the `#maintainers-confidential` channel in Slack to help out.

### `dev0` - set up the new version

Go to the [documentation dashboard](https://dash.readme.com/). In the top left dropdown, where it says the current version, click "Manage versions". Click "Add new version" and use a "v" with the minor release number, e.g. "v2.9". Fork from the prior release. Mark this new version as public by clicking on "Is public?"

### Sync the `docs/` content

See the `docs/NOTES.md` for instructions setting up the necessary Node tooling your first time.
You'll need to 1st login as outlined there via some variant of `npx rdme login --2fa --project pants ...`.
On the relevant release branch, run `npx rdme docs docs/markdown --version v<pants major>.<pants minor>`; e.g: `npx rdme docs docs/markdown --version v2.8`.

### Regenerate the references

Still on the relevant release branch, run `./pants run build-support/bin/generate_docs.py -- --sync --api-key <key>` with your key from <https://dash.readme.com/project/pants/v2.8/api-key>.

### `stable` releases - Update the default docsite

The first stable release of a branch should update the "default" version of the docsite. For example: when releasing the stable `2.9.0`, the docsite would be changed to pointing from `v2.8` to pointing to `v2.9` by default.

Also, update the [Changelog](doc:changelog)'s "highlights" column with a link to the blog summarizing the release. See the section "Announce the release" below for more info on the blog.

> 🚧 Don't have edit access?
> 
> Ping someone in the `#maintainers-confidential` channel in Slack to be added. Alternatively, you can "Suggest edits" in the top right corner.

Step 3: Tag the release to trigger publishing
---------------------------------------------

Once you have merged the `VERSION` bump — which will be on `main` for `dev` and `a0` releases, and on the release branch for release candidates — tag the release commit to trigger wheel building and publishing.

First, ensure that you are on your release branch at your version bump commit.

> 📘 Tip: if new commits have landed after your release commit
> 
> You can reset to your release commit by running `git reset --hard <sha>`.

Then, run:

```bash
./pants run src/python/pants_release/release.py -- tag-release
```

This will tag the release with your PGP key, and push the tag to origin, which will kick off a [`Release` job](https://github.com/pantsbuild/pants/actions/workflows/release.yaml) to build the wheels and publish them to PyPI.

Step 4: Test the release
------------------------

Run this script as a basic smoke test:

```bash
./pants run src/python/pants_release/release.py -- test-release
```

You should also [check PyPI](https://pypi.org/pypi/pantsbuild.pants) to ensure everything looks good. Click "Release history" to find the version you released, then click it and confirm the changelog is correct on the "Project description" page and that the `macOS` and `manylinux` wheels show up in the "Download files" page. 

Step 5: Run release testing on public repositories
--------------------------------------------------

Manually trigger a run of the [public repositories testing workflow](https://github.com/pantsbuild/pants/actions/workflows/public_repos.yaml), specifying the version just published as the "Pants version".

This workflow checks out various open-source repositories that use Pants and runs the given version of Pants against them, to try to validate if they can upgrade smoothly or if there's any (obvious) bugs. The workflow runs the repositories in two configurations: first with the repo's default configuration as a baseline, and then with the specified Pants version (and any additional options).

Once the workflow finishes, look through any failures and determine if there's any interesting/unknown problems, ensuring there's issues filed (and tagged with the appropriate milestone) for them. For instance, a custom plugin that is broken by a plugin API change is okay, but other sorts of breakage might not be.  If there's a failure during the baseline, a similar failure during the real (non-baseline) test can be ignored, as it likely means the repository in question is broken.

Alternatively, after starting the workflow, post the link to the in-progress run in `#development` in Slack, so that someone can come back to it when it does finish.

When Things Go Wrong
--------------------

From time to time, a release will fail. It's a complex process. The first thing to do after you've
exhausted your knowledge and debugging skills or patience is to contact others. You might reach out
to the development or maintainers channels on Pantbuild Slack in the absence of other ideas about
whom to ask for help.
