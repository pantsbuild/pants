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
  sources = rglobs('junit_resource_collision/*'),
)

files(
  name = 'maven_and_pants_directory',
  sources = rglobs('maven_and_pants/*'),
)

files(
  name = 'protolib-external-test_directory',
  sources = rglobs('protolib-external-test/*'),
)

files(
  name = 'protolib-test_directory',
  sources = rglobs('protolib-test/*'),
)

files(
  name = 'provided_patching_directory',
  sources = rglobs('provided_patching/*'),
)

files(
  name = 'resource_collision_directory',
  sources = rglobs('resource_collision/*'),
)
