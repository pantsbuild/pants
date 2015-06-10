# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_wire_library(name='roots',
  sources=[
    'foo.proto',
    'bar.proto',
    'foobar.proto',
  ],
  dependencies=[],
  roots = [
    'org.pantsbuild.example.roots.Bar',
    'org.pantsbuild.example.roots.Foobar',
    'org.pantsbuild.example.roots.Fooboo',
  ],
)
