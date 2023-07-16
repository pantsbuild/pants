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

### 1. Create a PGP signing key

If you already have one, you can reuse it.

You likely want to use the gpg implementation of pgp. On macOS, you can `brew install gpg`. Once gpg is installed, generate a new key: <https://docs.github.com/en/github/authenticating-to-github/generating-a-new-gpg-key>.

Please use a password for your key!

### 2. Add your PGP key to GitHub.

See <https://docs.github.com/en/github/authenticating-to-github/adding-a-new-gpg-key-to-your-github-account>.

### 3. Configure Git to use your PGP key.

See <https://docs.github.com/en/github/authenticating-to-github/telling-git-about-your-signing-key>.

Note: the last step is required on macOS.

### 4. Authenticate with the Github API

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

### 0c. Release candidates - Check for cherry-picks

There's many instances of landing a change in `main` and then wanting it to also apply to older releases. This is indicated by the `needs-cherrypick` label on a pull request. There's automation that attempts to automatically cherry-pick those changes back to the relevant branches.

This automation may not always succeed, so [check for any pending cherry-picks](https://github.com/pantsbuild/pants/pulls?q=is%3Apr+label%3Aneeds-cherrypick+is%3Aclosed), and find the relevant ones by looking at the milestone: for instance, if doing a release for 2.16, the relevant cherry-picks are those for milestone `2.16.x` or earlier.

The process may fail in two ways:

- The cherry-picking process failed, and tagged the PR with `auto-cherry-picking-failed`: follow the instructions in the comment on the pull request. (This likely means there's merge conflicts that require manual resolution.)
- the cherry-pick didn't (yet) run: trigger the automation manually by going to [the GitHub Action](https://github.com/pantsbuild/pants/actions/workflows/auto-cherry-picker.yaml), clicking on the "Run workflow" button, and providing the PR number.

### 1. Start the release

From the `main` branch, run `pants run src/python/pants_release/start_release.py -- --new 2.9.0.dev1 --release-manager your_github_username --publish` with the relevant version and your own GitHub username.

This will create a pull request that:

1. updates release notes (remember to check over the changes and follow the instructions in the PR to make any updates)
2. updates contributors
3. bumps the `VERSION` on `main`, if appropriate

> 🚧 Reminder: always do this against the `main` branch
>
> Even if you are preparing notes for a release candidate, always prepare the notes in a branch based on `main` and, later, target your PR to merge with `main`.


### 2. Merge the pull request

Post the PR to the `#development` in Slack. Merge once approved and green.

> 🚧 Watch out for any recently landed PRs
>
> From the time you put up your release prep until you hit "merge", be careful that no one merges any commits into main.
>
> If they do—and you're doing a `dev` or `a0` release—you should merge `main` into your PR and update the changelog with their changes. It's okay if the changes were internal only, but any public changes must be added to the changelog.
>
> Once you click "merge", it is safe for people to merge changes again.

### 3a. `a0` - create a new Git branch

For example, if you're releasing `2.9.0a0`, create the branch `2.9.x` by running the below. Make sure you are on your release commit before doing this.

```bash
$ git checkout -b 2.9.x
$ git push upstream 2.9.x
```

### 3b. release candidates - cherry-pick and bump the VERSION

1. Checkout from `main` into the release branch, e.g. `2.9.x`.
2. Cherry-pick the release prep using `git cherry-pick <sha>`.
3. Bump the `VERSION` in `src/python/pants/VERSION`, e.g. to `2.9.0rc1`. Push this as a new commit directly to the release branch - you do not need to open a pull request.

Step 2: Update this docs site
-----------------------------

Note that this step can currently only be performed by a subset of maintainers due to a paid maximum number of seats. If you do not have a readme.com account, contact someone in the `#maintainers-confidential` channel in Slack to help out.

### `dev0` - set up the new version

Go to the [documentation dashboard](https://dash.readme.com/). In the top left dropdown, where it says the current version, click "Manage versions". Click "Add new version" and use a "v" with the minor release number, e.g. "v2.9". Fork from the prior release. Mark this new version as public by clicking on "Is public?"

### Sync the `docs/` content

See the `docs/NOTES.md` for instructions setting up the the necessary Node tooling your first time.
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

Step 3: Tag the release to build wheels
---------------------------------------

Once you have merged the `VERSION` bump — which will be on `main` for `dev` and `a0` releases and the release branch for release candidates — you should tag the release commit to trigger wheel building and PyPI publishing.

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

Step 5: Announce the change
---------------------------

Announce the release to:

1. the [pants-devel](https://groups.google.com/forum/#!forum/pants-devel) list
2. the `#announce` channel in Slack

### Sample emails for `pants-devel`

You can get a contributor list by running the following, where `<tag>` is the tag for the prior release (eg: `release_2.9.0.dev0`):

```bash
pants run ./build-support/bin/contributors.py -- -s <tag>
```

> ❗️ Update the links in these templates!
> 
> When copy-pasting these templates, please always check that all versions match the relevant release. When adding a link, use "Test this link" to ensure that it loads properly.

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

Step 7: Run release testing on public repositories
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

Some issues are well known or well understood, and they are documented here.

#### https://binaries.pantsbuild.com outage / missing wheels

The https://binaries.pantsbuild.com site is an S3 bucket that houses Pantsbuild wheels generated in
CI and used as part of the release process. If there are missing wheels or the wheels can't be
fetched due to connectivity issues or an S3 outage, you'll learn about this through the release
script erroring out. The script is idempotent; so you can just run it again, potentially waiting
longer for wheels to be built in CI or outages to clear.

When the release script finishes, it creates and pushes a release tag. This will trigger a [release
GitHub workflow](https://github.com/pantsbuild/pants/blob/main/.github/workflows/release.yaml) that
could ~silently error later if there were to be an S3 outage. This job currently is responsible for
pushing a file mapping the release tag to the commit it tags out to
`https://binaries.pantsbuild.com/tags/pantsbuild.pants/<tag>`. If the tag is missing, it should be
fixed by running the following in an environment where you have both `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY` of an account that has permissions to push to the Pantsbuild S3 bucket:
```
pants run src/python/pants_release/backfill_s3_release_tag_mappings.py -- \
   --aws-cli-symlink-path $HOME/bin
```
If this sounds mysterious or new to you, you probably don't have such an account and should ask for
help from other maintainers. You may want to adjust the `--aws-cli-symlink-path` to your liking as
well, consult `--help` for more information.
