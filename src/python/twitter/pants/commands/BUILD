python_library(
  name = 'command',
  sources = ['__init__.py'],
  dependencies = [
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/pants/base:build_file'),
    pants('src/python/twitter/pants/base:target'),
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
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/pants/base:address'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:common'),
    pants('src/python/twitter/pants/python:python_builder'),
    pants('src/python/twitter/pants/python:interpreter_cache'),
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
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/pants/base:address'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/python:python_chroot'),
    pants('src/python/twitter/pants/python:interpreter_cache'),
    pants('src/python/twitter/pants/targets:python'),
  ]
)

python_library(
  name = 'setup_py',
  sources = ['setup_py.py'],
  dependencies = [
    pants(':command'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/pants/base:address'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/python:antlr_builder'),
    pants('src/python/twitter/pants/python:thrift_builder'),
    pants('src/python/twitter/pants/targets:python'),
  ]
)

python_library(
  name = 'goal',
  sources = ['goal.py'],
  dependencies = [
    pants(':command'),
    pants('3rdparty/python:python_daemon'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/common/log'),
    pants('src/python/twitter/common/log'),
    pants('src/python/twitter/pants/base:address'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/base:build_file'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:rcfile'),
    pants('src/python/twitter/pants/base:run_info'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/base:workunit'),
    pants('src/python/twitter/pants/engine'),
    pants('src/python/twitter/pants/goal'),
    pants('src/python/twitter/pants/goal:initialize_reporting'),
    pants('src/python/twitter/pants/reporting'),
    pants('src/python/twitter/pants/targets:common'),
    pants('src/python/twitter/pants/targets:java'),
    pants('src/python/twitter/pants/targets:jvm'),
    pants('src/python/twitter/pants/targets:scala'),
    pants('src/python/twitter/pants/tasks/jvm_compile:java'),
    pants('src/python/twitter/pants/tasks/jvm_compile:scala'),
    pants('src/python/twitter/pants/tasks/python'),
    pants('src/python/twitter/pants/tasks:antlr_gen'),
    pants('src/python/twitter/pants/tasks:benchmark_run'),
    pants('src/python/twitter/pants/tasks:binary_create'),
    pants('src/python/twitter/pants/tasks:bootstrap_jvm_tools'),
    pants('src/python/twitter/pants/tasks:builddictionary'),
    pants('src/python/twitter/pants/tasks:build_lint'),
    pants('src/python/twitter/pants/tasks:bundle_create'),
    pants('src/python/twitter/pants/tasks:check_exclusives'),
    pants('src/python/twitter/pants/tasks:check_published_deps'),
    pants('src/python/twitter/pants/tasks:checkstyle'),
    pants('src/python/twitter/pants/tasks:common'),
    pants('src/python/twitter/pants/tasks:console_task'),
    pants('src/python/twitter/pants/tasks:dependees'),
    pants('src/python/twitter/pants/tasks:dependencies'),
    pants('src/python/twitter/pants/tasks:depmap'),
    pants('src/python/twitter/pants/tasks:detect_duplicates'),
    pants('src/python/twitter/pants/tasks:eclipse_gen'),
    pants('src/python/twitter/pants/tasks:filedeps'),
    pants('src/python/twitter/pants/tasks:filemap'),
    pants('src/python/twitter/pants/tasks:filter'),
    pants('src/python/twitter/pants/tasks:idea_gen'),
    pants('src/python/twitter/pants/tasks:ivy_resolve'),
    pants('src/python/twitter/pants/tasks:jar_create'),
    pants('src/python/twitter/pants/tasks:javadoc_gen'),
    pants('src/python/twitter/pants/tasks:junit_run'),
    pants('src/python/twitter/pants/tasks:jvm_run'),
    pants('src/python/twitter/pants/tasks:list_goals'),
    pants('src/python/twitter/pants/tasks:listtargets'),
    pants('src/python/twitter/pants/tasks:markdown_to_html'),
    pants('src/python/twitter/pants/tasks:minimal_cover'),
    pants('src/python/twitter/pants/tasks:nailgun_task'),
    pants('src/python/twitter/pants/tasks:pathdeps'),
    pants('src/python/twitter/pants/tasks:paths'),
    pants('src/python/twitter/pants/tasks:prepare_resources'),
    pants('src/python/twitter/pants/tasks:protobuf_gen'),
    pants('src/python/twitter/pants/tasks:provides'),
    pants('src/python/twitter/pants/tasks:roots'),
    pants('src/python/twitter/pants/tasks:scala_repl'),
    pants('src/python/twitter/pants/tasks:scaladoc_gen'),
    pants('src/python/twitter/pants/tasks:scrooge_gen'),
    pants('src/python/twitter/pants/tasks:sorttargets'),
    pants('src/python/twitter/pants/tasks:specs_run'),
    pants('src/python/twitter/pants/tasks:targets_help'),
    pants('src/python/twitter/pants/tasks:thrift_gen'),
    pants('src/python/twitter/pants:binary_util'),
  ],
)
