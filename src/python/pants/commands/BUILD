# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'command',
  sources = ['command.py', 'register.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:target'),
  ]
)

python_library(
  name = 'pants_old',
  dependencies = [
    pants(':build'),
    pants(':help'),
    pants(':py'),
    pants(':setup_py'),
  ]
)

python_library(
  name = 'pants_new',
  dependencies = [
    pants(':goal'),
  ]
)

python_library(
  name = 'build',
  sources = ['build.py'],
  dependencies = [
    pants(':command'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/python:python_builder'),
    pants('src/python/pants/python:interpreter_cache'),
  ]
)

python_library(
  name = 'help',
  sources = ['help.py'],
  dependencies = [
    pants(':command'),
  ]
)

python_library(
  name = 'py',
  sources = ['py.py'],
  dependencies = [
    pants(':command'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/python:python_chroot'),
    pants('src/python/pants/python:interpreter_cache'),
    pants('src/python/pants/targets:python'),
  ]
)

python_library(
  name = 'setup_py',
  sources = ['setup_py.py'],
  dependencies = [
    pants(':command'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/python:antlr_builder'),
    pants('src/python/pants/python:thrift_builder'),
    pants('src/python/pants/targets:python'),
  ]
)

python_library(
  name = 'goal',
  sources = ['goal.py'],
  dependencies = [
    pants(':command'),
    pants('3rdparty/python:python-daemon'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:rcfile'),
    pants('src/python/pants/base:run_info'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/engine'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/goal:initialize_reporting'),
    pants('src/python/pants/reporting'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/targets:java'),
    pants('src/python/pants/targets:jvm'),
    pants('src/python/pants/targets:scala'),
    pants('src/python/pants/tasks/jvm_compile:java'),
    pants('src/python/pants/tasks/jvm_compile:scala'),
    pants('src/python/pants/tasks/python'),
    pants('src/python/pants/tasks:antlr_gen'),
    pants('src/python/pants/tasks:benchmark_run'),
    pants('src/python/pants/tasks:binary_create'),
    pants('src/python/pants/tasks:bootstrap_jvm_tools'),
    pants('src/python/pants/tasks:builddictionary'),
    pants('src/python/pants/tasks:build_lint'),
    pants('src/python/pants/tasks:bundle_create'),
    pants('src/python/pants/tasks:check_exclusives'),
    pants('src/python/pants/tasks:check_published_deps'),
    pants('src/python/pants/tasks:checkstyle'),
    pants('src/python/pants/tasks:common'),
    pants('src/python/pants/tasks:console_task'),
    pants('src/python/pants/tasks:dependees'),
    pants('src/python/pants/tasks:dependencies'),
    pants('src/python/pants/tasks:depmap'),
    pants('src/python/pants/tasks:detect_duplicates'),
    pants('src/python/pants/tasks:eclipse_gen'),
    pants('src/python/pants/tasks:filedeps'),
    pants('src/python/pants/tasks:filemap'),
    pants('src/python/pants/tasks:filter'),
    pants('src/python/pants/tasks:idea_gen'),
    pants('src/python/pants/tasks:ivy_resolve'),
    pants('src/python/pants/tasks:jar_create'),
    pants('src/python/pants/tasks:javadoc_gen'),
    pants('src/python/pants/tasks:junit_run'),
    pants('src/python/pants/tasks:jvm_run'),
    pants('src/python/pants/tasks:list_goals'),
    pants('src/python/pants/tasks:listtargets'),
    pants('src/python/pants/tasks:markdown_to_html'),
    pants('src/python/pants/tasks:minimal_cover'),
    pants('src/python/pants/tasks:nailgun_task'),
    pants('src/python/pants/tasks:pathdeps'),
    pants('src/python/pants/tasks:paths'),
    pants('src/python/pants/tasks:prepare_resources'),
    pants('src/python/pants/tasks:protobuf_gen'),
    pants('src/python/pants/tasks:provides'),
    pants('src/python/pants/tasks:roots'),
    pants('src/python/pants/tasks:scala_repl'),
    pants('src/python/pants/tasks:scaladoc_gen'),
    pants('src/python/pants/tasks:scrooge_gen'),
    pants('src/python/pants/tasks:sorttargets'),
    pants('src/python/pants/tasks:specs_run'),
    pants('src/python/pants/tasks:targets_help'),
    pants('src/python/pants/tasks:thrift_gen'),
    pants('src/python/pants:binary_util'),
  ],
)
