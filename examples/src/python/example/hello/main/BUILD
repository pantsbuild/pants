# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello world, but built with Pants.

python_binary(
  dependencies=[
    'examples/src/python/example/hello/greet:greet',
  ],
  sources=['main.py'],
)

# An "app" is a binary plus other loose files bundled together in
# an archive (e.g.: tar.gz, zip). In this example, the archive includes
# both `main.pex` and `BUILD`.
python_app(
  name='hello-app',
  binary=':main',
  bundles=[
    bundle(fileset=['BUILD']),
  ],
)
