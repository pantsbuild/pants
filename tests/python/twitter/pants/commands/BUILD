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
  name = 'all',
  dependencies = [
    pants(':commands'),
  ]
)

python_test_suite(
  name = 'commands',
  dependencies = [
    pants(':test_goal'),
    pants(':test_setup_py'),
  ]
)

python_tests(
  name = 'test_goal',
  sources = [ 'test_goal.py' ],
  dependencies = [
    pants("src/python/twitter/pants:pants-lib")
  ]
)

python_tests(
  name = 'test_setup_py',
  sources = [ 'test_setup_py.py' ],
  dependencies = [
    pants('3rdparty/python:mock'),
    pants("src/python/twitter/pants:pants-lib")
  ]
)
