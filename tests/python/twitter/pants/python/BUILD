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


python_test_suite(name = 'all',
  dependencies = [
    pants(':test_antlr_builder'),
    pants(':test_resolver'),
    pants(':test_thrift_builder'),
    pants(':test_thrift_namespace_packages'),
  ]
)

python_tests(name = 'test_antlr_builder',
  sources = ['test_antlr_builder.py'],
  dependencies = [
    'src/antlr/twitter/pants/python/test:csv',
    'src/antlr/twitter/pants/python/test:eval',
    'src/python/twitter/pants:pants-lib',
  ]
)

python_tests(name = 'test_thrift_namespace_packages',
  sources = ['test_thrift_namespace_packages.py'],
  dependencies = [ pants('src/thrift/com/twitter/pants/testing:duck-py'),
                   pants('src/thrift/com/twitter/pants/testing:goose-py') ]
)

python_tests(name = 'test_resolver',
  sources = ['test_resolver.py'],
  dependencies = [
    pants('src/python/twitter/common/config'),
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/pants:pants-lib')
  ]
)

python_tests(name = 'test_thrift_builder',
  sources = ['test_thrift_builder.py'],
  dependencies = [
    pants('3rdparty/python:mock'),
    pants('src/python/twitter/common/config'),
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/pants:pants-lib'),
    pants('tests/python/twitter/pants:base-test'),
    pants('tests/python/twitter/pants/base:base-test')
  ]
)
