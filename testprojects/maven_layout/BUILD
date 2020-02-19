# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':junit_resource_collision_directory',
    ':maven_and_pants_directory',
    ':protolib-external-test_directory',
    ':protolib-test_directory',
    ':provided_patching_directory',
    ':resource_collision_directory',
  ],
)

files(
  name = 'junit_resource_collision_directory',
  sources = ['junit_resource_collision/**/*'],
)

files(
  name = 'maven_and_pants_directory',
  sources = ['maven_and_pants/**/*'],
)

files(
  name = 'protolib-external-test_directory',
  sources = ['protolib-external-test/**/*'],
)

files(
  name = 'protolib-test_directory',
  sources = ['protolib-test/**/*'],
)

files(
  name = 'provided_patching_directory',
  sources = ['provided_patching/**/*'],
)

files(
  name = 'resource_collision_directory',
  sources = ['resource_collision/**/*'],
)
