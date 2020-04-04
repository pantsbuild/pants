# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_app(
  basename = 'bundle-example',
  binary=':bundle-bin',
  bundles=[
    bundle(fileset=['data/*']),
  ]
)

jvm_app(
  name='mapper',
  binary=':bundle-bin',
  bundles=[
    bundle(
      mapper=DirectoryReMapper('testprojects/src/java/org/pantsbuild/testproject/bundle/a/b', 'bundle_files'),
      fileset=['a/b/*']),
  ]
)

jvm_app(
  name='relative_to',
  binary=':bundle-bin',
  bundles=[
    bundle(
      relative_to='a',
      fileset=['a/b/*']),
  ]
)

jvm_app(
  name='rel_path',
  binary=':bundle-bin',
  bundles=[
    bundle(
      rel_path='testprojects/src/java/org/pantsbuild/testproject/bundle/a',
      fileset=['b/file1.txt'],
    )
  ]
)

jvm_app(
  name='directory',
  binary=':bundle-bin',
  bundles=[
    bundle(
      fileset=['a/b'],
    ),
  ]
)

jvm_app(
  name='explicit_recursion',
  binary=':bundle-bin',
  bundles=[
    bundle(
      fileset=['a/**/*'],
    ),
  ]
)

# The binary, the "runnable" part:

jvm_binary(
  name = 'bundle-bin',
  sources = ['BundleMain.java'],
  main = 'org.pantsbuild.testproject.bundle.BundleMain',
  basename = 'bundle-example-bin',
  dependencies = [
    '3rdparty:guava',
    'testprojects/src/resources/org/pantsbuild/testproject/bundleresources:resources',
  ]
)

# Tests resources ordering via integration test.
jvm_binary(
  name='bundle-resource-ordering',
  sources=['BundleMain.java'],
  main='org.pantsbuild.testproject.bundle.BundleMain',
  dependencies=[
    '3rdparty:guava',
    'testprojects/src/resources/org/pantsbuild/testproject/bundleresources:resources',
    'testprojects/tests/resources/org/pantsbuild/testproject/bundleresources:resources',
  ]
)
