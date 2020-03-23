#!/bin/bash -eu

if [[ "$(uname)" == "Darwin" ]]; then
  if (( $(find /cores -maxdepth 1 ! -name "$(basename /cores)" | wc -l) > 0 )); then
    echo >&2 "Core files detected; trying to get backtraces"
    sudo pip install six
    for core in /cores/*; do
      lldb --core "${core}" --batch --one-line "bt"
    done
  fi
fi
