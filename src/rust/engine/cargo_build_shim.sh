#!/usr/bin/env bash
# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This simply exists because `shell_command` at the time of writing doesn't know how to merge `PATH`
# from the rule's env and the `extra_env_vars`.

PYTHON_PATH="${CHROOT}/3rdparty/tools/python3/python/bin"
PROTOC_PATH="${CHROOT}/3rdparty/tools/protoc/protoc/bin"
export PATH="$PATH:$PYTHON_PATH:$PROTOC_PATH"

RELTYPE_FLAG=""
[ "$MODE" == "debug" ] || RELTYPE_FLAG="--release"

cargo build $RELTYPE_FLAG "$@"
