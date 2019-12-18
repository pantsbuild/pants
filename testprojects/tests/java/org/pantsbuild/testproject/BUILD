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
  sources=rglobs('annotation/*'),
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject:annotation_directory',
  ],
)

files(
  name='buildrefactor_directory',
  sources=rglobs('buildrefactor/*'),
)

files(
  name='coverage_directory',
  sources=rglobs('coverage/*'),
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject:coverage_directory',
  ],
)

files(
  name='cucumber_directory',
  sources=rglobs('cucumber/*'),
  dependencies = [
    'testprojects/3rdparty:cucumber_directory',
    'testprojects/tests/resources/org/pantsbuild/testproject:cucumber_directory',
  ],
)

files(
  name='cwdexample_directory',
  sources=rglobs('cwdexample/*'),
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject:cwdexample_directory',
  ],
)

files(
  name='depman_directory',
  sources=rglobs('depman/*'),
)

files(
  name='dummies_directory',
  sources=rglobs('dummies/*'),
)

files(
  name='exports_directory',
  sources=rglobs('exports/*'),
)

files(
  name='fail256_directory',
  sources=rglobs('fail256/*'),
)

files(
  name='htmlreport_directory',
  sources=rglobs('htmlreport/*'),
)

files(
  name='ideacodeandresources_directory',
  sources=rglobs('ideacodeandresources/*'),
  dependencies = [
    'testprojects/src/resources/org/pantsbuild/testproject:ideacodeandresources_directory',
    'testprojects/tests/resources/org/pantsbuild/testproject:ideacodeandresources_directory',
  ],
)

files(
  name='idearesourcesonly_directory',
  sources=rglobs('idearesourcesonly/*'),
  dependencies = [
    'testprojects/tests/resources/org/pantsbuild/testproject:idearesourcesonly_directory',
  ],
)

files(
  name='ideatestsandlib_directory',
  sources=rglobs('ideatestsandlib/*'),
)

files(
  name='ivyclassifier_directory',
  sources=rglobs('ivyclassifier/*'),
  dependencies = [
    'testprojects/tests/resources/org/pantsbuild/testproject:ivyclassifier_directory',
  ]
)

files(
  name='matcher_directory',
  sources=rglobs('matcher/*'),
)

files(
  name='parallel_directory',
  sources=rglobs('parallel/*'),
)

files(
  name='parallelclassesandmethods_directory',
  sources=rglobs('parallelclassesandmethods/*'),
)

files(
  name='parallelmethods_directory',
  sources=rglobs('parallelmethods/*'),
)

files(
  name='strictdeps_directory',
  sources=rglobs('strictdeps/*'),
)

files(
  name='syntheticjar_directory',
  sources=rglobs('syntheticjar/*'),
)

files(
  name='testjvms_directory',
  sources=rglobs('testjvms/*'),
)

files(
  name='timeout_directory',
  sources=rglobs('timeout/*'),
)

files(
  name='unicode_directory',
  sources=rglobs('unicode/*'),
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject:unicode_directory',
  ],
)

files(
  name='workdirs_directory',
  sources=rglobs('workdirs/*'),
)

