# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

python_library(
  name = 'base-test',
  sources = ['test_base.py'],
  dependencies = [
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/commands:goal'),
    pants('src/python/twitter/pants/goal'),
    pants('src/python/twitter/pants/tasks:console_task'),
    pants('src/python/twitter/pants/tasks:task'),
    pants('tests/python/twitter/pants/base:base-test'),
    pants('tests/python/twitter/pants:base-test'),
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
    pants(':jar_create'),
    pants(':jar_library_with_empty_dependencies'),
    pants(':listtargets'),
    pants(':minimal_cover'),
    pants(':protobuf_gen'),
    pants(':roots'),
    pants(':scrooge_gen'),
    pants(':sorttargets'),
    pants(':what_changed'),
  ],
)

python_tests(
  name = 'binary_create',
  sources = ['test_binary_create.py'],
  dependencies = [
    pants('tests/python/twitter/pants/base:base-test'),
    pants('src/python/twitter/pants/tasks:binary_create'),
  ]
)

python_tests(
  name = 'builddict',
  sources = ['test_builddict.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/tasks:builddictionary'),
  ]
)

python_tests(
  name = 'bundle_create',
  sources = ['test_bundle_create.py'],
  dependencies = [
    pants('tests/python/twitter/pants/base:base-test'),
    pants('src/python/twitter/pants/tasks:bundle_create'),
  ]
)

python_tests(
  name = 'cache_manager',
  sources = ['test_cache_manager.py'],
  dependencies = [
    pants('tests/python/twitter/pants/testutils'),
    pants('src/python/twitter/pants/base:build_invalidator'),
    pants('src/python/twitter/pants/tasks:cache_manager'),
  ]
)

python_tests(
  name = 'check_exclusives',
  sources = ['test_check_exclusives.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/goal:context'),
    pants('src/python/twitter/pants/tasks:check_exclusives'),
    pants('src/python/twitter/pants/tasks:task_error'),
    pants('tests/python/twitter/pants/testutils'),
  ]
)

python_tests(
  name = 'check_published_deps',
  sources = ['test_check_published_deps.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/tasks:check_published_deps'),
  ]
)

# XXX Uh shouldn't this be in base?
python_tests(
  name = 'config',
  sources = ['test_config.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/pants/base:config'),
  ]
)

python_tests(
  name = 'console_task',
  sources = ['test_console_task.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/tasks:console_task'),
  ]
)

# XXX this should be in goal
python_tests(
  name = 'context',
  sources = ['test_context.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/goal:context'),
    pants('tests/python/twitter/pants/testutils'),
  ]
)

python_tests(
  name = 'dependees',
  sources = ['test_dependees.py'],
  dependencies = [
    pants('3rdparty/python:mox'),
    pants(':base-test'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/targets:python'),
    pants('src/python/twitter/pants/targets:common'),
    pants('src/python/twitter/pants/tasks:task_error'),
    pants('src/python/twitter/pants/tasks:dependees'),
  ]
)

python_tests(
  name = 'dependencies',
  sources = ['test_dependencies.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/tasks:task_error'),
    pants('src/python/twitter/pants/tasks:dependencies'),
  ]
)

python_tests(
  name = 'depmap',
  sources = ['test_depmap.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/tasks:task_error'),
    pants('src/python/twitter/pants/tasks:depmap'),
  ]
)

python_tests(
  name = 'detect_duplicates',
  sources = ['test_detect_duplicates.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/tasks:detect_duplicates'),
    pants('src/python/twitter/pants/tasks:task_error'),
    pants('tests/python/twitter/pants/base:base-test'),
  ],
)

python_tests(
  name = 'filemap',
  sources = ['test_filemap.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/tasks:filemap'),
  ],
)

python_tests(
  name = 'filter',
  sources = ['test_filter.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/targets:java'),
    pants('src/python/twitter/pants/targets:python'),
    pants('src/python/twitter/pants/tasks:filter'),
  ],
)

python_tests(
  name = 'jar_create',
  sources = ['test_jar_create.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/java:jar'),
    pants('src/python/twitter/pants/targets:common'),
    pants('src/python/twitter/pants/targets:java'),
    pants('src/python/twitter/pants/targets:scala'),
    pants('src/python/twitter/pants/goal:products'),
    pants('src/python/twitter/pants/tasks:jar_create'),
    pants('tests/python/twitter/pants/base:base-test'),
    pants('tests/python/twitter/pants:base-test'),
  ],
)

# XXX this should be in targets?
python_tests(
  name = 'jar_library_with_empty_dependencies',
  sources = ['test_jar_library_with_empty_dependencies.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:jvm'),
  ],
)

python_tests(
  name = 'listtargets',
  sources = ['test_listtargets.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/tasks:listtargets'),
  ],
)

python_tests(
  name = 'minimal_cover',
  sources = ['test_minimal_cover.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/tasks:minimal_cover'),
  ],
)

python_tests(
  name = 'protobuf_gen',
  sources = ['test_protobuf_gen.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/pants/tasks:protobuf_gen'),
  ],
)

python_tests(
  name = 'roots',
  sources = ['test_roots.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:common'),
    pants('src/python/twitter/pants/tasks:roots'),
  ],
)

python_tests(
  name = 'scrooge_gen',
  sources = ['test_scrooge_gen.py'],
  dependencies = [
    pants('tests/python/twitter/pants:base-test'),
    pants('src/python/twitter/pants/tasks:task_error'),
    pants('src/python/twitter/pants/tasks:scrooge_gen'),
  ],
)

python_tests(
  name = 'sorttargets',
  sources = ['test_sorttargets.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/tasks:sorttargets'),
  ],
)

python_tests(
  name = 'targets_help',
  sources = ['test_targets_help.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:common'),
    pants('src/python/twitter/pants/tasks:targets_help'),
  ],
)

python_tests(
  name = 'what_changed',
  sources = ['test_what_changed.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/tasks:what_changed'),
  ],
)

