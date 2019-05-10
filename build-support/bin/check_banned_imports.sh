#!/bin/bash -u

# NB: this assumes that there are no spaces in the filenames. For a more robust way to
# store the result of `find` in a Bash array, see https://stackoverflow.com/a/23357277.
PYTHON_FILES=("$(find src tests pants-plugins examples contrib -name '*.py')")
RUST_FILES=("$(find src/rust/engine -name '*.rs')")

bad_files="$(echo "${PYTHON_FILES}" | xargs grep -l "^import subprocess$")"
if [ -n "${bad_files}" ]; then
    echo >&2 "Found forbidden imports. Instead of \`import subprocess\` you should use \`from pants.util.process_handler import subprocess\`. Bad files:"
    echo >&2 "${bad_files}"
    exit 1
fi

bad_files="$(echo "${PYTHON_FILES}" | xargs grep -l "^import future.moves.collections\|^from future.moves.collections import\|^from future.moves import .*collections")"
if [ -n "${bad_files}" ]; then
    echo >&2 "Found forbidden imports. \`future.moves.collections\` does not work as intended. Instead, you should use \`import collections\` or \`from pants.util.collections_abc_backport\`. Bad files:"
    echo >&2 "${bad_files}"
    exit 1
fi

bad_files="$(echo "${RUST_FILES}" | xargs egrep -l "^use std::sync::.*(Mutex|RwLock)")"
if [ -n "${bad_files}" ]; then
    echo >&2 "Found forbidden imports. Instead of \`std::sync::(Mutex|RwLock)\` you should use \`parking_lot::(Mutex|RwLock)\`. Bad files:"
    echo >&2 "${bad_files}"
    exit 1
fi
