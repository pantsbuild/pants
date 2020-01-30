# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':annotation_directory',
    ':buildrefactor_directory',
    ':coverage_directory',
    ':cucumber_directory',
    ':cwdexample_directory',
    ':depman_directory',
    ':dummies_directory',
    ':exports_directory',
    ':fail256_directory',
    ':htmlreport_directory',
    ':ideacodeandresources_directory',
    ':idearesourcesonly_directory',
    ':ideatestsandlib_directory',
    ':ivyclassifier_directory',
    ':matcher_directory',
    ':parallel_directory',
    ':parallelclassesandmethods_directory',
    ':parallelmethods_directory',
    ':strictdeps_directory',
    ':syntheticjar_directory',
    ':testjvms_directory',
    ':timeout_directory',
    ':unicode_directory',
    ':workdirs_directory',
  ],
)


files(
  name='annotation_directory',
  sources=['annotation/**/*'],
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject:annotation_directory',
  ],
)

files(
  name='buildrefactor_directory',
  sources=['buildrefactor/**/*'],
)

files(
  name='coverage_directory',
  sources=['coverage/**/*'],
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject:coverage_directory',
  ],
)

files(
  name='cucumber_directory',
  sources=['cucumber/**/*'],
  dependencies = [
    'testprojects/3rdparty:cucumber_directory',
    'testprojects/tests/resources/org/pantsbuild/testproject:cucumber_directory',
  ],
)

files(
  name='cwdexample_directory',
  sources=['cwdexample/**/*'],
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject:cwdexample_directory',
  ],
)

files(
  name='depman_directory',
  sources=['depman/**/*'],
)

files(
  name='dummies_directory',
  sources=['dummies/**/*'],
)

files(
  name='exports_directory',
  sources=['exports/**/*'],
)

files(
  name='fail256_directory',
  sources=['fail256/**/*'],
)

files(
  name='htmlreport_directory',
  sources=['htmlreport/**/*'],
)

files(
  name='ideacodeandresources_directory',
  sources=['ideacodeandresources/**/*'],
  dependencies = [
    'testprojects/src/resources/org/pantsbuild/testproject:ideacodeandresources_directory',
    'testprojects/tests/resources/org/pantsbuild/testproject:ideacodeandresources_directory',
  ],
)

files(
  name='idearesourcesonly_directory',
  sources=['idearesourcesonly/**/*'],
  dependencies = [
    'testprojects/tests/resources/org/pantsbuild/testproject:idearesourcesonly_directory',
  ],
)

files(
  name='ideatestsandlib_directory',
  sources=['ideatestsandlib/**/*'],
)

files(
  name='ivyclassifier_directory',
  sources=['ivyclassifier/**/*'],
  dependencies = [
    'testprojects/tests/resources/org/pantsbuild/testproject:ivyclassifier_directory',
  ]
)

files(
  name='matcher_directory',
  sources=['matcher/**/*'],
)

files(
  name='parallel_directory',
  sources=['parallel/**/*'],
)

files(
  name='parallelclassesandmethods_directory',
  sources=['parallelclassesandmethods/**/*'],
)

files(
  name='parallelmethods_directory',
  sources=['parallelmethods/**/*'],
)

files(
  name='strictdeps_directory',
  sources=['strictdeps/**/*'],
)

files(
  name='syntheticjar_directory',
  sources=['syntheticjar/**/*'],
)

files(
  name='testjvms_directory',
  sources=['testjvms/**/*'],
)

files(
  name='timeout_directory',
  sources=['timeout/**/*'],
)

files(
  name='unicode_directory',
  sources=['unicode/**/*'],
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject:unicode_directory',
  ],
)

files(
  name='workdirs_directory',
  sources=['workdirs/**/*'],
)

