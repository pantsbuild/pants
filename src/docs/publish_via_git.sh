#!/bin/bash

set -eo pipefail

# Usage:
#
#   in practice, you probably want
#       `./build-support/bin/publish_docs.sh`
#   ...which invokes this.
#
#   sh publish_via_git.sh git@github.com:pantsbuild/pantsbuild.github.io.git
#
#   or, to publish to a subdir under there:
#
#   sh publish_via_git.sh git@github.com:pantsbuild/pantsbuild.github.io.git subdir
#
# Assuming you've already generated web content in _build/html/ ,
# "publish" that content to a git repo. This is meant to work with
# github pages: put web content into a git repo, push to origin,
# a while later that content is served up on the web.
#
# We don't clear out old site contents. We just pile our stuff on top.
# If a file "went away", this won't remove it.

root=$(
  cd $(dirname $0)
  /bin/pwd
)

repo_url=$1
path_within_url=$2
out=/tmp/pantsdoc.$$

# When done, clean up tmp dir:
trap "rm -fr $out" 0 1 2

mkdir -p $out
cd $out
git clone $repo_url
cd `ls`
mkdir -p ./$path_within_url && cp -R $root/../../dist/docsite/* ./$path_within_url
git add .
git commit -am "publish by $USER"
git push origin master
