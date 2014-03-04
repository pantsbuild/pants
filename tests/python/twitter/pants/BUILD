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
  sources = ['base_build_root_test.py'],
  dependencies = [
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/base:address'),
    pants('src/python/twitter/pants/base:build_root'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:common'),
  ]
)

python_tests(
  name = 'test_maven_layout',
  sources = ['test_maven_layout.py'],
  dependencies = [
    pants(':base-test'),
  ]
)

python_tests(
  name = 'test_thrift_util',
  sources = ['test_thrift_util.py'],
  dependencies = [
    pants(':base-test'),
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/pants:thrift_util'),
  ]
)

python_test_suite(
  name = 'all',
  dependencies = [
    pants(':test_maven_layout'),
    pants(':test_thrift_util'),
    pants('tests/python/twitter/pants/base'),
    pants('tests/python/twitter/pants/cache'),
    pants('tests/python/twitter/pants/commands'),
    pants('tests/python/twitter/pants/engine'),
    pants('tests/python/twitter/pants/fs'),
    pants('tests/python/twitter/pants/java'),
    pants('tests/python/twitter/pants/net'),
    pants('tests/python/twitter/pants/process'),
    pants('tests/python/twitter/pants/python'),
    pants('tests/python/twitter/pants/reporting'),
    pants('tests/python/twitter/pants/scm'),
    pants('tests/python/twitter/pants/targets'),
    pants('tests/python/twitter/pants/tasks'),
  ]
)
