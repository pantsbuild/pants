#!/bin/bash -u

bad_files="$(find src tests pants-plugins examples contrib -name '*.py' | xargs grep -l "^import subprocess")"
if [ -n "${bad_files}" ]; then
    echo >&2 "Found forbidden imports. Instead of \`import subprocess\` you should \`from pants.util.process_handler import subprocess\`. Bad files:"
    echo >&2 "${bad_files}"
    exit 1
fi

bad_files="$(find src/rust/engine -name '*.rs' | xargs egrep -l "^use std::sync::.*(Mutex|RwLock)")"
if [ -n "${bad_files}" ]; then
    echo >&2 "Found forbidden imports. Instead of \`std::sync::(Mutex|RwLock)\` you should use \`parking_lot::(Mutex|RwLock)\`. Bad files:"
    echo >&2 "${bad_files}"
    exit 1
fi
