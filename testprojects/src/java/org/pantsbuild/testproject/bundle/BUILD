# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_app(name='bundle',
  basename = 'bundle-example',
  binary=':bundle-bin',
  bundles=[
    bundle(fileset=globs('data/*')),
  ]
)

# The binary, the "runnable" part:

jvm_binary(name = 'bundle-bin',
  source = 'BundleMain.java',
  main = 'org.pantsbuild.testproject.bundle.BundleMain',
  basename = 'bundle-example-bin',
  resources = [
    'testprojects/src/resources/org/pantsbuild/testproject/bundleresources:resources',
  ],
  dependencies = [
    '3rdparty:guava',
  ]
)

# This should fail because the relpath is wrong
jvm_app(name='missing-files',
  basename = 'bundle-example',
  binary=':bundle-bin',
  bundles=[
    bundle(fileset=['data/no-such-file']),
  ]
)
