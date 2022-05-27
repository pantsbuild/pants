# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Note: This target must be kept in sync with the requirements in `generate_java_parser_lockfile_request`.
jvm_artifact(
    name="jackson-databind",
    group="com.fasterxml.jackson.core",
    artifact="jackson-databind",
    # NB: Keep in sync with all other `3rdparty/jvm/com/fasterxml/jackson` libraries.
    # See https://github.com/pantsbuild/pants/issues/13767 for how this might be deduped.
    version="2.12.4",
    resolve="java_parser_dev",
)
