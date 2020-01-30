# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':compilation_failure_directory',
    ':compilation_warnings_directory',
    ':custom_scala_platform_directory',
    ':emptyscala_directory',
    ':exclude_direct_dep_directory',
    ':javadepsonscala_directory',
    ':javadepsonscalatransitive_directory',
    ':javasources_directory',
    ':mutual_directory',
    ':procedure_syntax_directory',
    ':public_inference_directory',
    ':publish_directory',
    ':rsc_compat_directory',
    ':scaladepsonboth_directory',
    ':sharedsources_directory',
    ':thriftdeptest_directory',
    ':unicode_directory',
  ],
)

files(
  name = 'compilation_failure_directory',
  sources = ['compilation_failure/**/*'],
)

files(
  name = 'compilation_warnings_directory',
  sources = ['compilation_warnings/**/*'],
)

files(
  name = 'custom_scala_platform_directory',
  sources = ['custom_scala_platform/**/*'],
)

files(
  name = 'emptyscala_directory',
  sources = ['emptyscala/**/*'],
)

files(
  name = 'exclude_direct_dep_directory',
  sources = ['exclude_direct_dep/**/*'],
)

files(
  name = 'javadepsonscala_directory',
  sources = ['javadepsonscala/**/*'],
)

files(
  name = 'javadepsonscalatransitive_directory',
  sources = ['javadepsonscalatransitive/**/*'],
)

files(
  name = 'javasources_directory',
  sources = ['javasources/**/*'],
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject:javasources_directory',
    'testprojects/src/java/org/pantsbuild/testproject:publish_directory'
  ],
)

files(
  name = 'mutual_directory',
  sources = ['mutual/**/*'],
)

files(
  name = 'procedure_syntax_directory',
  sources = ['procedure_syntax/**/*'],
)

files(
  name = 'public_inference_directory',
  sources = ['public_inference/**/*'],
)

files(
  name = 'publish_directory',
  sources = ['publish/**/*'],
  dependencies = [
    'testprojects/src/java/org/pantsbuild/testproject:publish_directory'
  ],
)

files(
  name = 'rsc_compat_directory',
  sources = ['rsc_compat/**/*'],
)

files(
  name = 'scaladepsonboth_directory',
  sources = ['scaladepsonboth/**/*'],
  dependencies = [
    'testprojects/src/scala/org/pantsbuild/testproject:javasources_directory',
  ],
)

files(
  name = 'sharedsources_directory',
  sources = ['sharedsources/**/*'],
)

files(
  name = 'thriftdeptest_directory',
  sources = ['thriftdeptest/**/*'],
  dependencies = [
    'testprojects/src/thrift/org/pantsbuild:testproject_directory',
  ],
)

files(
  name = 'unicode_directory',
  sources = ['unicode/**/*'],
)
