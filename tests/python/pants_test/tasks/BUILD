# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base',
  sources = ['test_base.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/commands:goal'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/tasks:console_task'),
    pants('src/python/pants/tasks:task'),
    pants('tests/python/pants_test/base:context_utils'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_test_suite(
  name = 'tasks',
  dependencies = [
    pants(':binary_create'),
    pants(':builddict'),
    pants(':bundle_create'),
    pants(':cache_manager'),
    pants(':check_exclusives'),
    pants(':check_published_deps'),
    pants(':config'),
    pants(':console_task'),
    pants(':context'),
    pants(':dependees'),
    pants(':dependencies'),
    pants(':depmap'),
    pants(':filemap'),
    pants(':filter'),
    pants(':ivy_utils'),
    pants(':jar_create'),
    pants(':jar_publish'),
    pants(':listtargets'),
    pants(':minimal_cover'),
    pants(':protobuf_gen'),
    pants(':roots'),
    pants(':scrooge_gen'),
    pants(':sorttargets'),
    pants(':what_changed'),
    pants('tests/python/pants_test/tasks/jvm_compile')
  ],
)

python_tests(
  name = 'binary_create',
  sources = ['test_binary_create.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/tasks:binary_create'),
  ]
)

python_tests(
  name = 'builddict',
  sources = ['test_builddict.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/tasks:builddictionary'),
  ]
)

python_tests(
  name = 'bundle_create',
  sources = ['test_bundle_create.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/tasks:bundle_create'),
  ]
)

python_tests(
  name = 'cache_manager',
  sources = ['test_cache_manager.py'],
  dependencies = [
    pants(':base'),
    pants('tests/python/pants_test/testutils'),
    pants('src/python/pants/base:build_invalidator'),
    pants('src/python/pants/tasks:cache_manager'),
  ]
)

python_tests(
  name = 'check_exclusives',
  sources = ['test_check_exclusives.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/goal:context'),
    pants('src/python/pants/tasks:check_exclusives'),
    pants('src/python/pants/tasks:task_error'),
  ]
)

python_tests(
  name = 'check_published_deps',
  sources = ['test_check_published_deps.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/tasks:check_published_deps'),
  ]
)

# XXX Uh shouldn't this be in base?
python_tests(
  name = 'config',
  sources = ['test_config.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/base:config'),
  ]
)

python_tests(
  name = 'console_task',
  sources = ['test_console_task.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/tasks:console_task'),
  ]
)

# XXX this should be in goal
python_tests(
  name = 'context',
  sources = ['test_context.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/goal:context'),
  ]
)

python_tests(
  name = 'dependees',
  sources = ['test_dependees.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python:mox'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/targets:python'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/tasks:task_error'),
    pants('src/python/pants/tasks:dependees'),
  ]
)

python_tests(
  name = 'dependencies',
  sources = ['test_dependencies.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/tasks:task_error'),
    pants('src/python/pants/tasks:dependencies'),
  ]
)

python_tests(
  name = 'depmap',
  sources = ['test_depmap.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/tasks:task_error'),
    pants('src/python/pants/tasks:depmap'),
  ]
)

python_tests(
  name = 'detect_duplicates',
  sources = ['test_detect_duplicates.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/tasks:detect_duplicates'),
    pants('src/python/pants/tasks:task_error'),
  ],
)

python_tests(
  name = 'filemap',
  sources = ['test_filemap.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/tasks:filemap'),
  ],
)

python_tests(
  name = 'filter',
  sources = ['test_filter.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/targets:java'),
    pants('src/python/pants/targets:python'),
    pants('src/python/pants/tasks:filter'),
  ],
)

python_tests(
  name = 'jar_create',
  sources = ['test_jar_create.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/java:jar'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/targets:java'),
    pants('src/python/pants/targets:scala'),
    pants('src/python/pants/goal:products'),
    pants('src/python/pants/tasks:jar_create'),
  ],
)

python_tests(
  name = 'jar_publish',
  sources = ['test_jar_publish.py'],
  dependencies = [
    pants('3rdparty/python:mock'),
    pants(':base'),
    pants('src/python/pants/tasks:jar_publish'),
  ],
)

python_tests(
  name = 'ivy_utils',
  sources = ['test_ivy_utils.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/tasks:ivy_utils'),
  ]
)

python_tests(
  name = 'listtargets',
  sources = ['test_listtargets.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/tasks:listtargets'),
  ],
)

python_tests(
  name = 'minimal_cover',
  sources = ['test_minimal_cover.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/tasks:minimal_cover'),
  ],
)

python_tests(
  name = 'protobuf_gen',
  sources = ['test_protobuf_gen.py'],
  dependencies = [
    pants(':base'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/tasks:protobuf_gen'),
  ],
)

python_tests(
  name = 'roots',
  sources = ['test_roots.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/tasks:roots'),
  ],
)

python_tests(
  name = 'scrooge_gen',
  sources = ['test_scrooge_gen.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/targets:java'),
    pants('src/python/pants/tasks:task_error'),
    pants('src/python/pants/tasks:scrooge_gen'),
  ],
)

python_tests(
  name = 'sorttargets',
  sources = ['test_sorttargets.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/tasks:sorttargets'),
  ],
)

python_tests(
  name = 'targets_help',
  sources = ['test_targets_help.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/tasks:targets_help'),
  ],
)

python_tests(
  name = 'what_changed',
  sources = ['test_what_changed.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/tasks:what_changed'),
  ],
)
