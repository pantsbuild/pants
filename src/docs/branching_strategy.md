# Branching Strategy

## Naming conventions
Leading up to release development work should be done on a branch in the following format:
n.n.xx where n.n is the major/minor version number and xx is the patch level version.  Once the
branch is stable and ready for release it can be pushed as branch n.n.x.  For example leading up
to the release of 1.0 we would create a branch with the literal name of '1.0.x'  and when we
finalize the release we would tag the commit with the release version of v1.0.0.  Any future
bugfix patches would be tagged in the same branch.

For example:

If you had a bugfix from '1.1.x' that you needed to backport to '1.0.x' you would cherry-pick
your changes to the '1.0.x' branch and when ready for release tag the commit with a new patch
version.

## Release Owner
Current releasers will rotate ownership of the release bi-weekly.  The release owner will be added
to the calendar for the release they will be responsible for.  The owner will be responsible for
creating a release candidate and coordinating feedback from the candidate.  If a release branch will
be cut then the release owner for that week will be responsible for creating the final branch.

## Release Criteria
In order to push a release branch the release owner needs to create a release candidate for other
parties to test.   Once the release candidate has been created we need to provide people with an
opportunity to block the release if a problem comes up.  To allow for adequate time to test the
release we will allow 5 business days for people to raise concerns.  When working on a release
the releaser would tag commits to the branch with a full version number and rc version.  For
example: 'v1.0.0-rc1'

## Release Cadence
Release candidates will happen every 2 weeks, provided there are enough user facing changes to
warrant a new release.  Of the two weeks 5 business days would be allocated to bugfixes and
testing by pants contributors.  If there are not enough changes in the release cycle or a blocking
problem is found then that release candidate then the release will happen in the next release
window.

During a particular release cycle, it's likely that releases for multiple stable branches
will be needed. As an example: release candidates for a patch release `1.0.1` might be outstanding
at the same time as release candidates for a minor release `1.1.0`.

### Major and Minor Releases
The decision to do a major or a minor release will be based on the impact of the changes.
Major releases signify larger more breaking changes.  Minor releases however should be compatible
with the last two minor releases.  In other words if a feature is deprecated in version 1.2.x you
should be able to continue using that feature at least through version 1.4.0.

### Patch Releases
In order to allow us to react quickly to bugs, patch fixes will be released as needed and may
include backporting fixes from newer release versions.  These releases would update the patch
version number and should be [[backwards compatible|pants('src/docs:deprecation_policy')]].

Patch releases will be tagged with
full version and rc number similar to normal releases.  For example: 'v1.0.2-rc3'


