# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_tests(
  name='junit',
  dependencies=[
    'tests/java/org/pantsbuild/tools/junit/lib:test-dep',
  ],
  sources=globs('*Test.java'),
  strict_deps=False,
  timeout=180,
)