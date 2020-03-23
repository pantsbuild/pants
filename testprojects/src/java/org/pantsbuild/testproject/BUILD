# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':aliases_directory',
    ':annotation_directory',
    ':bench_directory',
    ':bundle_directory',
    ':compilation_warnings_directory',
    ':coverage_directory',
    ':cwdexample_directory',
    ':cycle1_directory',
    ':cycle2_directory',
    ':deployexcludes_directory',
    ':depman_directory',
    ':dummies_directory',
    ':exclude_directory',
    ':extra_jvm_options_directory',
    ':ideacodeandresources_directory',
    ':idearesourcesonly_directory',
    ':inccompile_directory',
    ':intransitive_directory',
    ':jarversionincompatibility_directory',
    ':javadepsonscala_directory',
    ':javadepsonscalatransitive_directory',
    ':javasources_directory',
    ':junit_directory',
    ':jvmprepcommand_directory',
    ':manifest_directory',
    ':missing_sources_directory',
    ':missingdepswhitelist_directory',
    ':missingdepswhitelist2_directory',
    ':missingdirectdepswhitelist_directory',
    ':missingdirectdepswhitelist2_directory',
    ':missingjardepswhitelist_directory',
    ':missingjardepswhitelist2_directory',
    ':nocache_directory',
    ':packageinfo_directory',
    ':page_directory',
    ':phrases_directory',
    ':printversion_directory',
    ':proto-ordering_directory',
    ':provided_directory',
    ':publish_directory',
    ':resdependency_directory',
    ':runner_directory',
    ':runtime_directory',
    ':shading_directory',
    ':shadingdep_directory',
    ':thriftdeptest_directory',
    ':typeparameters_directory',
    ':unicode_directory',
    ':utf8proto_directory',
    # NB: See `:javasources_directory` for why this must be declared here.
    'testprojects/src/scala/org/pantsbuild/testproject:javasources_directory',
  ],
)

files(
  name = 'aliases_directory',
  sources = ['aliases/**/*'],
)

files(
  name = 'annotation_directory',
  sources = ['annotation/**/*'],
  dependencies = [
    'testprojects/3rdparty:com_directory',
  ],
)

files(
  name = 'bench_directory',
  sources = ['bench/**/*'],
)

files(
  name = 'bundle_directory',
  sources = ['bundle/**/*'],
  dependencies = [
    'testprojects/src/resources/org/pantsbuild/testproject:bundleresources_directory',
    'testprojects/tests/resources/org/pantsbuild/testproject:bundleresources_directory',
  ],
)

files(
  name = 'compilation_warnings_directory',
  sources = ['compilation_warnings/**/*'],
)

files(
  name = 'coverage_directory',
  sources = ['coverage/**/*'],
)

files(
  name = 'cwdexample_directory',
  sources = ['cwdexample/**/*'],
  dependencies = [
    'testprojects/3rdparty:checkstyle_directory',
  ],
)

files(
  name = 'cycle1_directory',
  sources = ['cycle1/**/*'],
)

files(
  name = 'cycle2_directory',
  sources = ['cycle2/**/*'],
)

files(
  name = 'deployexcludes_directory',
  sources = ['deployexcludes/**/*'],
)

files(
  name = 'depman_directory',
  sources = ['depman/**/*'],
)

files(
  name = 'dummies_directory',
  sources = ['dummies/**/*'],
)

files(
  name = 'exclude_directory',
  sources = ['exclude/**/*'],
)

files(
  name = 'extra_jvm_options_directory',
  sources = ['extra_jvm_options/**/*'],
)

files(
  name = 'ideacodeandresources_directory',
  sources = ['ideacodeandresources/**/*'],
  dependencies = [
    'testprojects/src/resources/org/pantsbuild/testproject:ideacodeandresources_directory',
  ],
)

files(
  name = 'idearesourcesonly_directory',
  sources = ['idearesourcesonly/**/*'],
  dependencies = [
    'testprojects/src/resources/org/pantsbuild/testproject:idearesourcesonly_directory',
  ],
)

files(
  name = 'inccompile_directory',
  sources = ['inccompile/**/*'],
  dependencies = [
    'testprojects/3rdparty:jetty_directory',
  ],
)

files(
  name = 'intransitive_directory',
  sources = ['intransitive/**/*'],
)

files(
  name = 'jarversionincompatibility_directory',
  sources = ['jarversionincompatibility/**/*'],
)

files(
  name = 'javadepsonscala_directory',
  sources = ['javadepsonscala/**/*'],
  dependencies = [
    'testprojects/src/scala/org/pantsbuild/testproject:javadepsonscala_directory',
  ],
)

files(
  name = 'javadepsonscalatransitive_directory',
  sources = ['javadepsonscalatransitive/**/*'],
  dependencies = [
    'testprojects/src/scala/org/pantsbuild/testproject:javadepsonscalatransitive_directory',
  ],
)

# NB: This has a circular dependency on
# 'testprojects/src/scala/org/pantsbuild/testproject:javasources_directory', which we cannot declare
# here. Instead, we declare this in `:all_targets`.
files(
  name = 'javasources_directory',
  sources = ['javasources/**/*'],
)

files(
  name = 'junit_directory',
  sources = ['junit/**/*'],
)

files(
  name = 'jvmprepcommand_directory',
  sources = ['jvmprepcommand/**/*'],
)

files(
  name = 'manifest_directory',
  sources = ['manifest/**/*'],
)

files(
  name = 'missing_sources_directory',
  sources = ['missing_sources/**/*'],
)

files(
  name = 'missingdepswhitelist_directory',
  sources = ['missingdepswhitelist/**/*'],
  dependencies = [
    ':missingdepswhitelist2_directory',
    ':publish_directory',
  ],
)

files(
  name = 'missingdepswhitelist2_directory',
  sources = ['missingdepswhitelist2/**/*'],
)

files(
  name = 'missingdirectdepswhitelist_directory',
  sources = ['missingdirectdepswhitelist/**/*'],
  dependencies = [
    ':missingdirectdepswhitelist2_directory',
  ],
)

files(
  name = 'missingdirectdepswhitelist2_directory',
  sources = ['missingdirectdepswhitelist2/**/*'],
  dependencies = [
    ':publish_directory',
  ],
)

files(
  name = 'missingjardepswhitelist_directory',
  sources = ['missingjardepswhitelist/**/*'],
  dependencies = [
    ':missingjardepswhitelist2_directory',
  ],
)

files(
  name = 'missingjardepswhitelist2_directory',
  sources = ['missingjardepswhitelist2/**/*'],
)

files(
  name = 'nocache_directory',
  sources = ['nocache/**/*'],
)

files(
  name = 'packageinfo_directory',
  sources = ['packageinfo/**/*'],
)

files(
  name = 'page_directory',
  sources = ['page/**/*'],
  dependencies = [
    'examples/src/java/org/pantsbuild/example:hello_directory',
  ],
)

files(
  name = 'phrases_directory',
  sources = ['phrases/**/*'],
)

files(
  name = 'printversion_directory',
  sources = ['printversion/**/*'],
)

files(
  name = 'proto-ordering_directory',
  sources = ['proto-ordering/**/*'],
  dependencies = [
    'testprojects/src/protobuf/org/pantsbuild/testproject:proto-ordering_directory',
  ],
)

files(
  name = 'provided_directory',
  sources = ['provided/**/*'],
)

files(
  name = 'publish_directory',
  sources = ['publish/**/*'],
  dependencies = [
    'testprojects/src/protobuf/org/pantsbuild/testproject:distance_directory',
  ],
)

files(
  name = 'resdependency_directory',
  sources = ['resdependency/**/*'],
)

files(
  name = 'runner_directory',
  sources = ['runner/**/*'],
)

files(
  name = 'runtime_directory',
  sources = ['runtime/**/*'],
)

files(
  name = 'shading_directory',
  sources = ['shading/**/*'],
  dependencies = [
    ':shadingdep_directory',
  ],
)

files(
  name = 'shadingdep_directory',
  sources = ['shadingdep/**/*'],
)

files(
  name = 'thriftdeptest_directory',
  sources = ['thriftdeptest/**/*'],
  dependencies = [
    'testprojects/src/thrift/org/pantsbuild:testproject_directory',
  ],
)

files(
  name = 'typeparameters_directory',
  sources = ['typeparameters/**/*'],
)

files(
  name = 'unicode_directory',
  sources = ['unicode/**/*'],
  dependencies = [
    'testprojects/src/scala/org/pantsbuild/testproject:unicode_directory',
  ],
)

files(
  name = 'utf8proto_directory',
  sources = ['utf8proto/**/*'],
  dependencies = [
    'testprojects/src/protobuf/org/pantsbuild/testproject:utf8proto_directory',
  ],
)
