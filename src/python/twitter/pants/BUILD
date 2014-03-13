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

dependencies(
  name = 'pants',
  dependencies = [
    pants('src/python/twitter/pants/bin:pants'),
  ],
).with_description('An alias for the pants binary target.')

python_library(
  name = 'pants-packaged',

  # TODO(wickman) This version should be automatically pulled in from twitter.pants.version
  provides=setup_py(
    name='twitter.pants',
    version='0.0.17',
    description="Twitter's pants build tool.",
    url='https://github.com/twitter/commons',
    license='Apache License, Version 2.0',
    zip_safe=True,
    namespace_packages=['twitter'],
    classifiers=[
      'Intended Audience :: Developers',
      'License :: OSI Approved :: Apache Software License',
      'Operating System :: OS Independent',
      'Programming Language :: Python',
    ]
  ).with_binaries(
    # TODO(John Sirois): Switch back when target cycles have been sorted out.
    # pants=pants('src/python/twitter/pants/bin:pants'),
    pants=pants(':_pants_transitional_publishable_binary_'),
  )
)

page(name='readme',
  source='README.md',
)

# XXX move into base or thrift
python_library(
  name = 'binary_util',
  sources = ['binary_util.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/common/log'),
    pants('src/python/twitter/pants/base:config'),
    pants('src/python/twitter/pants/tasks:task_error'),
  ],
)

python_library(
  name = 'thrift_util',
  sources = ['thrift_util.py'],
  dependencies = [
    pants(':binary_util'),
  ],
)
