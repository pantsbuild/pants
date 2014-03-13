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

python_test_suite(
  name = 'targets',
  dependencies = [
    pants(':artifact'),
    pants(':bundle'),
    pants(':exclusive'),
    pants(':internal'),
    pants(':jar_library'),
    pants(':pants_target'),
    pants(':python_binary'),
    pants(':python_target'),
    pants(':target'),
    pants(':util'),
  ]
)

python_tests(
  name = 'artifact',
  sources = ['test_artifact.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/targets:common'),
    pants('src/python/twitter/pants/targets:jvm'),
  ]
)

python_tests(
  name = 'bundle',
  sources = ['test_bundle.py'],
  dependencies = [
    pants('tests/python/twitter/pants:base-test'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/targets:jvm'),
  ]
)

python_tests(
  name = 'exclusive',
  sources = ['test_exclusive.py'],
  dependencies = [
    pants('tests/python/twitter/pants/testutils'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/goal:context'),
    pants('src/python/twitter/pants/tasks:check_exclusives'),
  ]
)

python_tests(
  name = 'internal',
  sources = ['test_internal.py'],
  dependencies = [
    pants('tests/python/twitter/pants/testutils'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:common'),
  ]
)

python_tests(
  name = 'jar_library',
  sources = ['test_jar_library.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:jvm'),
  ]
)

python_tests(
  name = 'pants_target',
  sources = ['test_pants_target.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:common'),
  ]
)

python_tests(
  name = 'python_binary',
  sources = ['test_python_binary.py'],
  dependencies = [
    pants('tests/python/twitter/pants:base-test'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:python'),
  ]
)

python_tests(
  name = 'target',
  sources = ['test_target.py'],
  dependencies = [
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
  ]
)

python_tests(
  name = 'python_target',
  sources = ['test_python_target.py'],
  dependencies = [
    pants('tests/python/twitter/pants:base-test'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/targets:python'),
  ]
)

python_tests(
  name = 'util',
  sources = ['test_util.py'],
  dependencies = [
    pants('src/python/twitter/pants/targets:common'),
  ]
)

