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

python_library(name='base-test',
  sources=['base_build_root_test.py'],
  dependencies=[
    pants('src/python/twitter/pants:pants-lib'),
    pants('src/python/twitter/pants:pants-deps'),
  ]
)

python_tests(name='utils',
  sources=globs('test_*.py'),
  dependencies=[
    pants(':base-test'),
    pants('src/python/twitter/pants:pants-lib'),
    pants('src/python/twitter/pants:pants-deps'),
  ]
)

python_test_suite(name='all',
  dependencies=[
    pants(':utils'),
    pants('tests/python/twitter/pants/base'),
    pants('tests/python/twitter/pants/cache'),
    pants('tests/python/twitter/pants/commands'),
    pants('tests/python/twitter/pants/engine'),
    pants('tests/python/twitter/pants/fs'),
    pants('tests/python/twitter/pants/java'),
    pants('tests/python/twitter/pants/java/distribution'),
    pants('tests/python/twitter/pants/net/http'),
    pants('tests/python/twitter/pants/process'),
    pants('tests/python/twitter/pants/python:all'),
    pants('tests/python/twitter/pants/reporting'),
    pants('tests/python/twitter/pants/scm'),
    pants('tests/python/twitter/pants/targets'),
    pants('tests/python/twitter/pants/tasks'),
  ]
)
