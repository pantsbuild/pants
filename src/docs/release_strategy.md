# Release Strategy

This page describes the "who", "what", and "when" of Pants releases. If you're interested
in learning "how" to release, see the [[Release Process|pants('src/docs:release')]] page.

## Release Responsibilities
There is one release manager per week, decided via a shared calendar (to volunteer to be added
to the calendar, see [[How to Contribute|pants('src/docs:howto_contribute')]]).

The release manager is responsible for:

* Creating `stable` branches
* Creating and gathering feedback on release candidates
* Cutting `pre` and `stable` releases

These release types and responsibilities are described below.

## Release Cadence
The release manager for a particular week decides whether to cut `stable` or `pre` releases (or
both!) based on the following criteria:

1. Decide whether to create a _new_ `stable` branch:
    * If it has been approximately [[three months|pants('src/docs:deprecation_policy')]] since the
previous `stable` branch, the release manager should inspect changes that have landed in master
since the previous `stable` branch was created, and decide whether the changes justify a new
`stable` branch (this is intentionally left open for discussion). If a new `stable` branch is
justified, it will be either a `major` or `minor` branch (described below).
    * If a new `stable` branch is _not_ created (because of insufficient time/change to justify the
stable vetting process), the release manager must cut a `pre` release from master instead.
2. In addition to any `pre` release or newly-created `stable` branches, the release manager should
determine whether any existing `stable` branches need new release candidates by inspecting the
[Pants Backport Proposals](https://docs.google.com/spreadsheets/d/12rsaVVhmSXrMVlZV6PUu5uzsKNNcceP9Lpf7rpju_IE/edit#gid=0)
sheet. If there are requests "sufficient" to justify `patch` releases for existing `stable` branches, the
release manager should cut release candidates for those branches.

In other words, for a given week: _one of either_ a `pre` release or a new `stable` branch are
created, and additionally, `patch` releases for existing `stable` branches _might_ be created.

## Release Types

### `pre` releases
`pre` releases are releases that occur directly from master, without the additional vetting that
is applied to `stable` releases. They help to ensure a steady release cadence from master by filling
in the gaps between the (generally more time consuming) `stable` releases.

### `stable` releases
`stable` release candidates generally happen every two weeks, provided that there are enough user
facing changes to warrant a new `stable` release. Of those two weeks, five business days are allocated
to bugfixing and testing by pants contributors on a release candidate announcement thread (described
below).

#### `major` and `minor` stable branches
The decision to create a `major` or a `minor` stable branch is based on consensus on
[[pants-devel@|pants('src/docs:howto_contribute')]] as to the impact of the changes.
`major` releases signify large or breaking changes. `minor` releases however should be compatible
with the last two `minor` releases. In other words if a feature is deprecated in version `1.2.x`
you should be able to continue using that feature at least through version `1.4.0`.

#### `patch` stable Releases
In order to allow us to react quickly to bugs, `patch` fixes are released for `stable` branches as
needed and should always consist of fixes or small backwards-compatible features backported from
master. These releases update the patch version number, (ie, from `1.0.x` to `1.0.y`) and should
only include commits from the Pants Backport Proposals that are deemed to be
[[backwards compatible|pants('src/docs:deprecation_policy')]].

## Naming conventions

### `stable` naming
Leading up to a `stable` release, development work should be done on a branch named with the
following format: `n.n.x` where n.n are the `major`/`minor` version numbers and "`x`" is a literal
character placeholder for the `patch` version. Release candidates of an upcoming `stable` release
are suffixed with `-rcN`. For instance: "the `1.1.x` `stable` branch",
"the `1.1.1-rc0` release candidate", and "the `1.1.1` `stable` release".


### `pre` naming
`pre` releases occur between `stable` branches, and are differentiated by a `-preN` suffix. The pattern
to follow is `N.N.0-preN`, where `N.N` are the _next_ `major`/`minor` branch that will be created
and N is the next sequential number starting from `0`. For instance: "the `1.1.0-pre0` `pre` release".

## Examples

* Leading up to the release of `2.0.0` the release manager would create a `stable` branch with
the literal name "`2.0.x`". They would cut release candidates named `2.0.0-rc0` (and so on), and
afterwards, they'd finalize the `2.0.0` release in that `2.0.x` branch by tagging the
commit with the release version: `v2.0.0`.

* If a release manager had a bugfix from master that they needed to backport to the `1.1.x` `stable`
branch, they would cherry-pick the commit to the `1.1.x` branch, run a series of release candidates
(ie, `1.1.1-rc0`, etc), and finally tag the validated commit with a new patch version (ie `v1.1.1`).

* If `pre` releases were required after having created the `1.0.x` branch, but before having created
the `1.1.x` branch, then they would start with `1.1.0-pre0`, and continue weekly to `1.1.0-preN`
until the `1.1.x` branch had been created.

## `stable` Release Candidates
In order to make a `stable` release, the release manager needs to create a release candidate for
contributors to test. Once a release candidate has been created and announced according to the
[[Release Process|pants('src/docs:release')]], the release manager should allow five business days
for contributors to raise concerns on the release candidate announcement thread. During those five
days the release manager might need to perform multiple release candidates, until finally, when no
more blockers are raised against a particular release candidate, the final version of that release
can be cut.
