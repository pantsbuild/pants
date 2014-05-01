# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'goal',
  sources = ['__init__.py'],
  dependencies = [
    pants(':error'),
    pants(':context'),
    pants(':group'),
    pants(':phase'),
    pants(':run_tracker'),
    pants('src/python/pants/base:build_manual'),
    pants('src/python/pants/tasks:task'),
  ],
)

python_library(
  name = 'aggregated_timings',
  sources = ['aggregated_timings.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
  ]
)

# why is this in goal?
python_library(
  name = 'artifact_cache_stats',
  sources = ['artifact_cache_stats.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
  ]
)

python_library(
  name = 'context',
  sources = ['context.py'],
  dependencies = [
    pants(':products'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.process'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/java:distribution'),  # XXX(fixme)
    pants('src/python/pants/reporting'),
    pants('src/python/pants/targets:all'),  # XXX(fixme)
  ],
)

python_library(
  name = 'error',
  sources = ['error.py'],
)

python_library(
  name = 'help',
  sources = ['help.py'],
  dependencies = [
    ':option_helpers',
    ':phase',
    'src/python/pants/version',
  ],
)

python_library(
  name = 'group',
  sources = ['group.py'],
)

python_library(
  name = 'initialize_reporting',  # XXX shouldn't this be in reporting?!
  sources = ['initialize_reporting.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/reporting'),
  ],
)

python_library(
  name = 'option_helpers',
  sources = ['option_helpers.py'],
  dependencies = [
    pants('src/python/pants/base:config'),
  ],
)

python_library(
  name = 'phase',
  sources = ['phase.py'],
  dependencies = [
    pants(':error'),
    pants(':option_helpers'),
    pants('src/python/pants/base:build_manual'),
  ],
)

python_library(
  name = 'products',
  sources = ['products.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
  ],
)

python_library(
  name = 'run_tracker',
  sources = ['run_tracker.py'],
  dependencies = [
    pants(':aggregated_timings'),
    pants(':artifact_cache_stats'),
    pants('src/python/pants/base:run_info'),
    pants('src/python/pants/base:worker_pool'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/reporting'),
    pants('src/python/pants/base:config'),
  ],
)

python_library(
  name = 'register',
  sources = ['register.py'],
  dependencies = [
    ':goal',
    'src/python/pants/targets:java',
    'src/python/pants/tasks:antlr_gen',
    'src/python/pants/tasks:apache_thrift_gen',
    'src/python/pants/tasks:benchmark_run',
    'src/python/pants/tasks:binary_create',
    'src/python/pants/tasks:bootstrap_jvm_tools',
    'src/python/pants/tasks:build_lint',
    'src/python/pants/tasks:builddictionary',
    'src/python/pants/tasks:bundle_create',
    'src/python/pants/tasks:check_exclusives',
    'src/python/pants/tasks:check_published_deps',
    'src/python/pants/tasks:checkstyle',
    'src/python/pants/tasks:clean',
    'src/python/pants/tasks:dependees',
    'src/python/pants/tasks:dependencies',
    'src/python/pants/tasks:depmap',
    'src/python/pants/tasks:detect_duplicates',
    'src/python/pants/tasks:eclipse_gen',
    'src/python/pants/tasks:filedeps',
    'src/python/pants/tasks:filemap',
    'src/python/pants/tasks:filter',
    'src/python/pants/tasks:idea_gen',
    'src/python/pants/tasks:ivy_resolve',
    'src/python/pants/tasks:jar_create',
    'src/python/pants/tasks:jar_publish',
    'src/python/pants/tasks:javadoc_gen',
    'src/python/pants/tasks:junit_run',
    'src/python/pants/tasks:jvm_run',
    'src/python/pants/tasks:list_goals',
    'src/python/pants/tasks:listtargets',
    'src/python/pants/tasks:markdown_to_html',
    'src/python/pants/tasks:minimal_cover',
    'src/python/pants/tasks:nailgun_task',
    'src/python/pants/tasks:pathdeps',
    'src/python/pants/tasks:paths',
    'src/python/pants/tasks:prepare_resources',
    'src/python/pants/tasks:protobuf_gen',
    'src/python/pants/tasks:provides',
    'src/python/pants/tasks:reporting_server',
    'src/python/pants/tasks:roots',
    'src/python/pants/tasks:scala_repl',
    'src/python/pants/tasks:scaladoc_gen',
    'src/python/pants/tasks:scrooge_gen',
    'src/python/pants/tasks:sorttargets',
    'src/python/pants/tasks:specs_run',
    'src/python/pants/tasks:targets_help',
    'src/python/pants/tasks/jvm_compile:java',
    'src/python/pants/tasks/jvm_compile:scala',
    'src/python/pants/tasks/python',
  ],
)
