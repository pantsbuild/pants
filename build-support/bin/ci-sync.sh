#!/usr/bin/env bash

# This script acts to push all changes that hit pantsbuild/pants master
# to a ~mirror at pantsbuild/pants-for-travis-osx-ci.  Only the active
# .travis.yml is changed.  This is all done to support CI runs against OSX.
# Although Travis-CI has support for an os list in the main .travis.yml,
# 'osx' is currently at capacity and not accepting new users.
# CIs can be run against OSX still, but for this the .travis.yml must specify
# a language of objective-c.  Since there can be only 1 .travis.yml per
# repo, we're forced to maintain a mirror repo.
#
# See .travis.osx.yml at the root of this repo for more information.

cp .travis.osx.yml .travis.yml && \
git config --local user.email "${GH_EMAIL}" && \
git config --local user.name "${GH_USER}" && \
git commit -am "Prepare pants OSX mirror for CI." && \
git config --local credential.helper "store --file=.git/credentials" && \
echo "https://${GH_TOKEN}:@github.com" > .git/credentials && \
git push -f https://github.com/pantsbuild/pants-for-travis-osx-ci.git HEAD:master
