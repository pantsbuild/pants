#!/usr/bin/env zsh

set -euxo pipefail

find initial-fuzz-inputs/ -name '*.tar' -exec rm -v {} '+'

pushd fuzz-inputs-untarred/

# TODO: ensure all the inputs can be invoked with the same pants command (currently
# `./pants run src:idk`)!
for dir in *; do
  pushd "$dir"
  tar cvf "../../initial-fuzz-inputs/${dir}.tar" ./
  popd
done

popd

pushd do-the-fuzz-here/

rm -rf *

touch pants{,.ini}

# TODO: make a runner script that unpacks things into a temporary dir so we don't pollute
# do-the-fuzz-here/!
# TODO: make this a heck of a lot faster with v2!
py-afl-fuzz -t 1000 -m 500 -i ../initial-fuzz-inputs -o ../fuzzing-results -- \
            ../pants -ldebug --print-exception-stacktrace --afl-fuzz-untar-stdin run src:idk

popd
