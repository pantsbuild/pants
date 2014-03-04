# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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
  name = 'engine_test_base',
  sources = ['base_engine_test.py'],
  dependencies = [
    pants('src/python/twitter/pants/goal'),
  ]
)

python_test_suite(
  name = 'engine',
  dependencies = [
    pants(':test_engine'),
    pants(':test_group_engine'),
  ]
)

python_tests(
  name = 'test_engine',
  sources = ['test_engine.py'],
  dependencies = [
    pants(':engine_test_base'),
    pants('3rdparty/python:mox'),
    pants('src/python/twitter/pants/engine'),
    pants('src/python/twitter/pants/tasks:task_error'),
    pants('tests/python/twitter/pants:base-test'),
  ],
)

python_tests(
  name = 'test_group_engine',
  sources = ['test_group_engine.py'],
  dependencies = [
    pants(':engine_test_base'),
    pants('src/python/twitter/pants/engine'),
    pants('src/python/twitter/pants/goal'),
    pants('src/python/twitter/pants/tasks:check_exclusives'),
    pants('src/python/twitter/pants/tasks:common'),
    pants('tests/python/twitter/pants/base:base-test'),
    pants('tests/python/twitter/pants:base-test'),
  ],
)
