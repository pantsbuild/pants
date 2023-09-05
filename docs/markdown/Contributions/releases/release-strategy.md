---
title: "Release strategy"
slug: "release-strategy"
excerpt: "Our approach to semantic versioning + time-based releases."
hidden: false
createdAt: "2020-05-17T03:02:12.315Z"
---
Pants release cycles flow through:

1. `dev` releases from the `main` branch,
2. an `a` (alpha) release, which is the first on a stable branch,
3. `rc` releases, which have begun to stabilize on a stable branch, and will become a stable release
4. stable releases, which are our most trusted.

Pants follows semantic versioning, along with using regular time-based dev releases. We follow a strict [Deprecation policy](doc:deprecation-policy).

> 📘 Tip: join the mailing group for release announcements
> 
> See [Community](doc:the-pants-community).
> 
> Also see [Upgrade tips](doc:upgrade-tips) for suggestions on how to effectively upgrade Pants versions.

Stable releases
---------------

Stable releases occur roughly every six weeks. They have been vetted through at least one alpha and one release candidate.

Stable releases are named with the major, minor, and patch version (with no suffix). For example, `2.1.0` or `2.2.1`.

Any new patch versions will only include:

- Backward-compatible bug fixes
- Backward-compatible feature backports, as long as they:
  1. Are requested by users
  2. Are deemed low-risk and are easy to backport
  3. Do not introduce new deprecations 

Patch versions after `*.0` (i.e.: `2.2.1`) must have also had at least one release candidate, but no alpha releases are required.

> 🚧 Stable releases may still have bugs
> 
> We try our best to write bug-free code, but, like everyone, we sometimes make mistakes.
> 
> If you encounter a bug, please gently let us know by opening a GitHub issue or messaging us on Slack. See [Community](doc:the-pants-community).

Release candidates
------------------

`rc` releases are on track to being stable, but may still have some issues.

Release candidates are named with the major, minor, and patch version, and end in `rc` and a number. For example, `2.1.0rc0` or `2.1.0rc1`.

Release candidates are subject to the constraints on cherry-picks mentioned in the Stable releases section.

> 📘 When is a release "stable" enough?
> 
> A stable release should not be created until at least five business days have passed since the first `rc0` release. Typically, during this time, there will be multiple release candidates to fix any issues discovered.
> 
> A stable release can be created two business days after the most recent release candidate if there are no more blockers.

> 👍 Help wanted: testing out release candidates
> 
> We greatly appreciate when users test out release candidates. While we do our best to have comprehensive CI—and we "dogfood" release candidates—we are not able to test all the ways Pants is used in the wild.
> 
> If you encounter a bug, please gently let us know by opening a GitHub issue or messaging us on Slack. See [Community](doc:the-pants-community).

Alpha releases
--------------

Alpha (`a`) releases are the first releases on a stable branch (after `dev` releases, and before `rc`s), and although they have not received any testing beyond what a `dev` release may have received, they are a particular focus for testing, because they represent code which will eventually become an `rc`.

Alpha releases are named with the major, minor, and patch version, and end in `a` and a number.  For example, `2.1.0a0`.

Except in extenuating circumstances, there will usually only be a single alpha release per series.

Dev releases
------------

`dev` releases are weekly releases that occur directly from the `main` branch, without the additional vetting that is applied to stable releases, alpha releases, or release candidates. Usually, these are released on Friday or Monday.

Dev releases help to ensure a steady release cadence from `main` by filling in the gaps between the more time consuming stable releases.

Dev releases are named with the major, minor, and patch version, and end in `.dev` and a number. For example, `2.1.0.dev0` or `2.1.0.dev1`.

Dev releases can include any changes, so long as they comply with the [Deprecation policy](doc:deprecation-policy).

> 📘 How many dev releases until starting a release candidate?
> 
> Usually, we release 3-4 dev releases before switching to the alpha release `a0`. This means we usually release `dev0`, `dev1`, `dev2`, sometimes `dev3`, and then `a0`.
> 
> We try to limit the number of changes in each stable release to make it easier for users to upgrade. If the dev releases have been particularly disruptive, such as making major deprecations, we may start a release candidate sooner, such as after `dev1`.
