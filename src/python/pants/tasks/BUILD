# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'common',
  sources = ['__init__.py'],
  dependencies = [
    ':task',
    'src/python/pants/base:exceptions',
  ]
)

python_library(
  name = 'antlr_gen',
  sources = ['antlr_gen.py'],
  dependencies = [
    pants(':code_gen'),
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
    pants('src/python/pants/jvm:nailgun_task'),
    pants('src/python/pants/targets:java'),
  ],
)

python_library(
  name = 'benchmark_run',
  sources = ['benchmark_run.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
  ],
)

python_library(
  name = 'binary_create',
  sources = ['binary_create.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_binary_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/fs'),
    pants('src/python/pants/java:jar'),
  ],
)

python_library(
  name = 'build_lint',
  sources = ['build_lint.py'],
  dependencies = [
    pants(':common'),
  ],
)

python_library(
  name = 'builddictionary',
  sources = ['builddictionary.py'],
  resources = globs('templates/builddictionary/*.mustache'),
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:generator'),
    pants('src/python/pants/goal:option_helpers'),
    pants('src/python/pants/goal:phase'),
    pants('3rdparty/python:setuptools'),
  ],
)

python_library(
  name = 'bundle_create',
  sources = ['bundle_create.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_binary_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/fs'),
    pants('src/python/pants/targets:jvm'),
    pants('src/python/pants/jvm:jar_task'),
  ],
)

python_library(
  name = 'check_exclusives',
  sources = ['check_exclusives.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:common'),
  ],
)

python_library(
  name = 'check_published_deps',
  sources = ['check_published_deps.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants(':jar_publish'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:jvm'),
  ],
)

python_library(
  name = 'checkstyle',
  sources = ['checkstyle.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
    pants('src/python/pants/jvm:nailgun_task'),
    pants('src/python/pants/process'),
  ],
)

python_library(
  name = 'clean',
  sources = ['clean.py'],
  dependencies = [
    pants(':console_task'),
    pants('3rdparty/python:python-daemon'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:config'),
  ],
)

python_library(
  name = 'code_gen',
  sources = ['code_gen.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/base:build_environment'),
  ],
)

python_library(
  name = 'confluence_publish',
  sources = ['confluence_publish.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.confluence'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants:binary_util'),
  ],
)

python_library(
  name = 'console_task',
  sources = ['console_task.py'],
  dependencies = [
    pants(':common'),
  ],
)

python_library(
  name = 'dependees',
  sources = ['dependees.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:common'),
  ],
)

python_library(
  name = 'dependencies',
  sources = ['dependencies.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('src/python/pants/targets:jvm'),
    pants('src/python/pants/targets:python'),
  ],
)

python_library(
  name = 'depmap',
  sources = ['depmap.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('src/python/pants/targets:jvm'),
  ],
)

python_library(
  name = 'detect_duplicates',
  sources = ['detect_duplicates.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_binary_task'),
    pants('src/python/pants/java:jar'),
  ],
)

python_library(
  name = 'eclipse_gen',
  sources = ['eclipse_gen.py'],
  resources = globs('templates/eclipse/*.mustache'),
  dependencies = [
    pants(':common'),
    pants(':ide_gen'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:generator'),
  ],
)

python_library(
  name = 'filedeps',
  sources = ['filedeps.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('src/python/pants/targets:jvm'),
    pants('src/python/pants/targets:common'),
  ],
)

python_library(
  name = 'filemap',
  sources = ['filemap.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'filter',
  sources = ['filter.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'ide_gen',
  sources = ['ide_gen.py'],
  dependencies = [
    pants(':checkstyle'),
    pants(':common'),
    pants(':jvm_binary_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/goal:phase'), # XXX?
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
    pants('src/python/pants/targets:jvm'),
    pants('src/python/pants:binary_util'),
  ],
)

python_library(
  name = 'idea_gen',
  sources = ['idea_gen.py'],
  resources = globs('templates/idea/*.mustache'),
  dependencies = [
    pants(':common'),
    pants(':ide_gen'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:generator'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/targets:java'),
    pants('src/python/pants/targets:scala'),
  ],
)

python_library(
  name = 'jar_create',
  sources = ['jar_create.py'],
  dependencies = [
    pants(':common'),
    pants(':javadoc_gen'),
    pants(':scaladoc_gen'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/fs'),
    pants('src/python/pants/java:jar'),
    pants('src/python/pants/targets:jvm'),
    pants('src/python/pants/jvm:jar_task'),
  ],
)

python_library(
  name = 'jar_publish',
  sources = ['jar_publish.py'],
  resources = globs('templates/jar_publish/*.mustache') +
              globs('src/python/pants/jvm/templates/ivy_resolve/*.mustache'),
  dependencies = [
    pants(':common'),
    pants(':scm_publish'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.config'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:generator'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/ivy'),
    pants('src/python/pants/targets:common'),
  ],
)

python_library(
  name = 'javadoc_gen',
  sources = ['javadoc_gen.py'],
  dependencies = [
    pants(':jvmdoc_gen'),
  ],
)

python_library(
  name = 'junit_run',
  sources = ['junit_run.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
    pants('src/python/pants/targets:java'),
  ],
)

python_library(
  name = 'jvm_binary_task',
  sources = ['jvm_binary_task.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/targets:jvm'),
    pants('src/python/pants/jvm:jar_task'),
  ],
)

python_library(
  name = 'jvm_run',
  sources = ['jvm_run.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/java:executor'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/targets:jvm'),
  ],
)

python_library(
  name = 'jvm_task',
  sources = ['jvm_task.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/base:build_environment'),
  ],
)

python_library(
  name = 'jvm_tool_bootstrapper',
  sources = ['jvm_tool_bootstrapper.py'],
  dependencies = [
    pants(':common'),
  ],
)

python_library(
  name = 'jvmdoc_gen',
  sources = ['jvmdoc_gen.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants:binary_util'),
  ],
)

python_library(
  name = 'list_goals',
  sources = ['list_goals.py'],
  dependencies = [
    pants(':console_task'),
    pants('src/python/pants/goal'),
  ],
)

python_library(
  name = 'listtargets',
  sources = ['listtargets.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'markdown_to_html',
  sources = ['markdown_to_html.py'],
  dependencies = [
    pants('3rdparty/python:Markdown'),
    pants('3rdparty/python:Pygments'),
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants:binary_util'),
  ],
)

python_library(
  name = 'minimal_cover',
  sources = ['minimal_cover.py'],
  dependencies = [
    pants(':console_task'),
  ],
)

python_library(
  name = 'pathdeps',
  sources = ['pathdeps.py'],
  dependencies = [
    pants(':console_task'),
  ],
)

python_library(
  name = 'paths',
  sources = ['paths.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'prepare_resources',
  sources = ['prepare_resources.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/goal:products'),
  ],
)

python_library(
  name = 'protobuf_gen',
  sources = ['protobuf_gen.py'],
  dependencies = [
    pants(':common'),
    pants(':code_gen'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/targets:java'),
    pants('src/python/pants/targets:python'),
  ],
)

python_library(
  name = 'provides',
  sources = ['provides.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/jvm:ivy_utils'),
    pants('src/python/pants/targets:jvm'),
  ],
)

python_library(
  name = 'reporting_server',
  sources = ['reporting_server.py'],
  dependencies = [
    pants(':console_task'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:run_info'),
    pants('src/python/pants/reporting'),
  ],
)

python_library(
  name = 'roots',
  sources = ['roots.py'],
  dependencies = [
    pants(':console_task'),
    pants('src/python/pants/targets:common'),
  ],
)

python_library(
  name = 'scala_repl',
  sources = ['scala_repl.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
  ],
)

python_library(
  name = 'scaladoc_gen',
  sources = ['scaladoc_gen.py'],
  dependencies = [
    pants(':jvmdoc_gen'),
  ],
)

python_library(
  name = 'scalastyle',
  sources = ['scalastyle.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
    pants('src/python/pants/jvm:nailgun_task'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/process'),
  ],
)

python_library(
  name = 'scm_publish',
  sources = ['scm_publish.py'],
  dependencies = [
    pants(':common'),
  ],
)

python_library(
  name = 'scrooge_gen',
  sources = ['scrooge_gen.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/targets:java'),
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
    pants('src/python/pants/jvm:nailgun_task'),
    pants('src/python/pants/targets:scala'),
    pants('src/python/pants:thrift_util'),
  ],
)

python_library(
  name = 'sorttargets',
  sources = ['sorttargets.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.util'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'specs_run',
  sources = ['specs_run.py'],
  dependencies = [
    pants(':common'),
    pants(':jvm_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
  ],
)

python_library(
  name = 'targets_help',
  sources = ['targets_help.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:common'),
  ],
)

python_library(
  name = 'task',
  sources = ['task.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:cache_manager'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:build_invalidator'),
    pants('src/python/pants/base:hash_utils'),
    pants('src/python/pants/base:worker_pool'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/cache'),
    pants('src/python/pants/ivy'),
    pants('src/python/pants/java:executor'),
    pants('src/python/pants/reporting'),
  ],
)

python_library(
  name = 'apache_thrift_gen',
  sources = ['apache_thrift_gen.py'],
  dependencies = [
    pants(':common'),
    pants(':code_gen'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/targets:java'),
    pants('src/python/pants/targets:python'),
    pants('src/python/pants:thrift_util'),
  ],
)

python_library(
  name = 'what_changed',
  sources = ['what_changed.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/scm'),
  ],
)
