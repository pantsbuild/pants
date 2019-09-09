# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
  name = 'aliases_directory',
  sources = rglobs('aliases/*'),
)

files(
  name = 'annotation_directory',
  sources = rglobs('annotation/*'),
  dependencies = [
    'testprojects/3rdparty:com_directory',
  ],
)

files(
  name = 'bench_directory',
  sources = rglobs('bench/*'),
)

files(
  name = 'compilation_warnings_directory',
  sources = rglobs('compilation_warnings/*'),
)

files(
  name = 'coverage_directory',
  sources = rglobs('coverage/*'),
)

files(
  name = 'cwdexample_directory',
  sources = rglobs('cwdexample/*'),
  dependencies = [
    'testprojects/3rdparty:checkstyle_directory',
  ],
)

files(
  name = 'cycle1_directory',
  sources = rglobs('cycle1/*'),
)

files(
  name = 'cycle2_directory',
  sources = rglobs('cycle2/*'),
)

files(
  name = 'deployexcludes_directory',
  sources = rglobs('deployexcludes/*'),
)

files(
  name = 'depman_directory',
  sources = rglobs('depman/*'),
)

files(
  name = 'dummies_directory',
  sources = rglobs('dummies/*'),
)

files(
  name = 'exclude_directory',
  sources = rglobs('exclude/*'),
)

files(
  name = 'extra_jvm_options_directory',
  sources = rglobs('extra_jvm_options/*'),
)

files(
  name = 'intransitive_directory',
  sources = rglobs('intransitive/*'),
)

files(
  name = 'jarversionincompatibility_directory',
  sources = rglobs('jarversionincompatibility/*'),
)

files(
  name = 'javasources_directory',
  sources = rglobs('javasources/*'),
)

files(
  name = 'junit_directory',
  sources = rglobs('junit/*'),
)

files(
  name = 'jvmprepcommand_directory',
  sources = rglobs('jvmprepcommand/*'),
)

files(
  name = 'manifest_directory',
  sources = rglobs('manifest/*'),
)

files(
  name = 'missingdirectdepswhitelist_directory',
  sources = rglobs('missingdirectdepswhitelist/*'),
  dependencies = [
    ':missingdirectdepswhitelist2_directory',
  ],
)

files(
  name = 'missingdirectdepswhitelist2_directory',
  sources = rglobs('missingdirectdepswhitelist2/*'),
  dependencies = [
    ':publish_directory',
  ],
)

files(
  name = 'missingjardepswhitelist_directory',
  sources = rglobs('missingjardepswhitelist/*'),
  dependencies = [
    ':missingjardepswhitelist2_directory',
  ],
)

files(
  name = 'missingjardepswhitelist2_directory',
  sources = rglobs('missingjardepswhitelist2/*'),
)

files(
  name = 'nocache_directory',
  sources = rglobs('nocache/*'),
)

files(
  name = 'page_directory',
  sources = rglobs('page/*'),
  dependencies = [
    'examples/src/java/org/pantsbuild/example:hello_directory',
  ],
)

files(
  name = 'phrases_directory',
  sources = rglobs('phrases/*'),
)

files(
  name = 'printversion_directory',
  sources = rglobs('printversion/*'),
)

files(
  name = 'provided_directory',
  sources = rglobs('provided/*'),
)

files(
  name = 'publish_directory',
  sources = rglobs('publish/*'),
  dependencies = [
    'testprojects/src/protobuf/org/pantsbuild/testproject:distance_directory',
  ],
)

files(
  name = 'resdependency_directory',
  sources = rglobs('resdependency/*'),
)

files(
  name = 'runtime_directory',
  sources = rglobs('runtime/*'),
)

files(
  name = 'shading_directory',
  sources = rglobs('shading/*'),
  dependencies = [
    ':shadingdep_directory',
  ],
)

files(
  name = 'shadingdep_directory',
  sources = rglobs('shadingdep/*'),
)

files(
  name = 'unicode_directory',
  sources = rglobs('unicode/*'),
  dependencies = [
    'testprojects/src/scala/org/pantsbuild/testproject:unicode_directory',
  ],
)
