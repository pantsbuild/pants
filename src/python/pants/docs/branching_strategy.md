# Branching Strategy

## Naming conventions
Leading up to release development work should be done on a branch in the following format:
n.n.xx where n.n is the major/minor version number and xx is the patch level version.  Once the
branch is stable and ready for release it can be pushed as branch n.n.xx.  For example leading up
to the release of 1.0 we would create a branch with the literal name of '1.0.xx'  and when we
finalize the release we would tag the commit with the release version of _1.0.0.  Any future
bugfix patches would be tagged in the same branch.  We use a leading underscore to differentiate
branch and tag names.

For example:

If you had a bugfix from '1.1.xx' that you needed to backport to '1.0.xx' you would cherry-pick
your changes to the '1.0.xx' branch and when ready for release tag the commit with a new patch
version.

## Release Owner
Current committers will rotate ownership of the release bi-weekly.  The release owner will be added
to the calendar for the release they will be responsible for.  The owner will be responsible for
creating a release candidate and coordinating feedback from the candidate.  If a release branch will
be cut then the release owner for that week will be responsible to create the final branch.

## Release Criteria
In order to push a release branch the release owner needs to create a release candidate for other
parties to test.   Once the release candidate has been created we need to provide people with an
opportunity to block the release if a problem comes up.  To allow for adequate time to test the
release we will allow 5 business days for people to raise concerns.

## Release Cadence
### Major and Minor Releases
Release candidates will happen every 2 weeks, provided there are enough user facing changes to
warrant a new release.  Of the two weeks 5 business days would be allocated to bugfixes and
testing by pants contributors.  If there are not enough changes in the release cycle or a blocking
problem is found then that release candidate then the release will happen in the next release
window.  The decision to do a major or a minor release will be based on the impact of the changes.
Major releases signify larger more breaking changes.  Minor releases however should be compatible
with the last two minor releases.  In other words if a feature is deprecated in version 1.2.x you
should be able to continue using that feature at least through version 1.4.x.

### Patch Releases
In order to allow us to react quickly to bugs patch fixes will be released as needed and may
include backporting fixes from newer release versions.  These releases would update the minor
version number and should not be backwards incompatible.


