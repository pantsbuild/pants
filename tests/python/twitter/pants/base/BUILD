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
  sources = ['context_utils.py'],
  dependencies = [
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/goal'),
    pants('src/python/twitter/pants/reporting'),
  ]
)

python_test_suite(
  name = 'all',
  dependencies = [
    pants(':base'),
  ],
)

python_test_suite(
  name = 'base',
  dependencies = [
    pants(':abbreviate_target_ids'),
    pants(':address'),
    pants(':build_file'),
    pants(':build_invalidator'),
    pants(':build_root'),
    pants(':double_dag'),
    pants(':generator'),
    pants(':hash_utils'),
    pants(':parse_context'),
    pants(':revision'),
    pants(':run_info'),
  ]
)

python_tests(
  name = 'abbreviate_target_ids',
  sources = ['test_abbreviate_target_ids.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:abbreviate_target_ids'),
  ]
)

python_tests(
  name = 'address',
  sources = ['test_address.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/base:address'),
    pants('src/python/twitter/pants/base:build_environment'),
  ]
)

python_tests(
  name = 'build_file',
  sources = ['test_build_file.py'],
  dependencies = [
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/base:build_file'),
  ]
)

python_tests(
  name = 'build_invalidator',
  sources = ['test_build_invalidator.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/pants/base:build_invalidator'),
  ]
)

python_tests(
  name = 'build_root',
  sources = ['test_build_root.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/base:build_root'),
  ]
)

python_tests(
  name = 'double_dag',
  sources = ['test_double_dag.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:double_dag'),
    pants('src/python/twitter/pants/reporting'),
    pants('tests/python/twitter/pants/testutils'),
  ]
)

python_tests(
  name = 'generator',
  sources = ['test_generator.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:generator'),
  ]
)

python_tests(
  name = 'hash_utils',
  sources = ['test_hash_utils.py'],
  dependencies = [
    pants('3rdparty/python:mox'),
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/pants/base:hash_utils'),
  ]
)

python_tests(
  name = 'parse_context',
  sources = ['test_parse_context.py'],
  dependencies = [
    pants('tests/python/twitter/pants:base-test'),
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/base:address'),
    pants('src/python/twitter/pants/base:build_file'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
  ]
)

python_tests(
  name = 'revision',
  sources = ['test_revision.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:revision'),
  ]
)

python_tests(
  name = 'run_info',
  sources = ['test_run_info.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/pants/base:run_info'),
  ]
)

