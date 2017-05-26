# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_app(
  basename = 'bundle-example',
  binary=':bundle-bin',
  bundles=[
    bundle(fileset=globs('data/*')),
  ]
)

jvm_app(name='mapper',
  binary=':bundle-bin',
  bundles=[
    bundle(
      mapper=DirectoryReMapper('testprojects/src/java/org/pantsbuild/testproject/bundle/a/b', 'bundle_files'),
      fileset=globs('a/b/*')),
  ]
)

jvm_app(name='relative_to',
  binary=':bundle-bin',
  bundles=[
    bundle(
      relative_to='a',
      fileset=globs('a/b/*')),
  ]
)

jvm_app(name='rel_path',
  binary=':bundle-bin',
  bundles=[
    bundle(
      rel_path='testprojects/src/java/org/pantsbuild/testproject/bundle/a',
      fileset=['b/file1.txt']
    )
  ]
)

# The binary, the "runnable" part:

jvm_binary(name = 'bundle-bin',
  source = 'BundleMain.java',
  main = 'org.pantsbuild.testproject.bundle.BundleMain',
  basename = 'bundle-example-bin',
  dependencies = [
    '3rdparty:guava',
    'testprojects/src/resources/org/pantsbuild/testproject/bundleresources:resources',
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

# Tests resources ordering via integration test.
jvm_binary(
  name='bundle-resource-ordering',
  source='BundleMain.java',
  main='org.pantsbuild.testproject.bundle.BundleMain',
  dependencies=[
    '3rdparty:guava',
    'testprojects/src/resources/org/pantsbuild/testproject/bundleresources:resources',
    'testprojects/tests/resources/org/pantsbuild/testproject/bundleresources:resources',
  ]
)
