#!/bin/bash -u

PYTHON_FILES="$(find src tests pants-plugins examples contrib -name '*.py')"
RUST_FILES="$(find src/rust/engine -name '*.rs')"

bad_files="$(echo ${PYTHON_FILES} | xargs grep -l "^import subprocess")"
if [ -n "${bad_files}" ]; then
    echo >&2 "Found forbidden imports. Instead of \`import subprocess\` you should \`from pants.util.process_handler import subprocess\`. Bad files:"
    echo >&2 "${bad_files}"
    exit 1
fi

bad_files="$(echo ${PYTHON_FILES} | xargs grep -l "^import collections\|^from collections import")"
if [ -n "${bad_files}" ]; then
    echo >&2 "Found forbidden imports. Instead of \`import collections\` you should \`from pants.util import collections_backport\`. Bad files:"
    echo >&2 "${bad_files}"
    exit 1
fi

bad_files="$(echo ${RUST_FILES} | xargs egrep -l "^use std::sync::.*(Mutex|RwLock)")"
if [ -n "${bad_files}" ]; then
    echo >&2 "Found forbidden imports. Instead of \`std::sync::(Mutex|RwLock)\` you should use \`parking_lot::(Mutex|RwLock)\`. Bad files:"
    echo >&2 "${bad_files}"
    exit 1
fi
