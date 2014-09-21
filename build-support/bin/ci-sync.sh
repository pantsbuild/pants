#!/usr/bin/env bash

cp .travis.osx.yml .travis.yml && \
GIT_AUTHOR_NAME="${GH_USER}" GIT_AUTHOR_EMAIL=${GH_EMAIL} git commit -am "Prepare pants OSX mirror for CI." && \
git config credential.helper "store --file=.git/credentials" && \
echo "https://${GH_TOKEN}:@github.com" > .git/credentials
git push -f https://github.com/pantsbuild/pants-for-travis-osx-ci.git HEAD:master
