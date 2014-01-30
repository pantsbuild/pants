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

NG_CLIENT = ['java/bin/ng.py']

PANTS_SOURCES   = rglobs('*.py') - NG_CLIENT
PANTS_GARBAGE   = rglobs('*.pyc') + rglobs('*~')
PANTS_RESOURCES = rglobs('*') - PANTS_SOURCES - NG_CLIENT - PANTS_GARBAGE


def pylint_build_filter(python, platform):
  return python.startswith('2')


python_library(
  name='pants-deps',
  dependencies=[
    pants('3rdparty/python:ansicolors'),
    pants('3rdparty/python:elementtree'),
    pants('3rdparty/python:markdown'),
    pants('3rdparty/python:psutil'),
    pants('3rdparty/python:pygments'),
    pants('3rdparty/python:pystache'),
    pants('3rdparty/python:pytest'),
    pants('3rdparty/python:pytest-cov'),
    pants('3rdparty/python:python_daemon'),
    pants('3rdparty/python:requests'),
    python_requirement('pylint==1.1.0', version_filter=pylint_build_filter)
  ]
)

python_library(
  name='pants-lib',
  dependencies=[
    pants(':pants-deps'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/config'),
    pants('src/python/twitter/common/confluence'),
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/decorators'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/java'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/common/log'),
    pants('src/python/twitter/common/process'),
    pants('src/python/twitter/common/python'),
    pants('src/python/twitter/common/quantity'),
    pants('src/python/twitter/common/rwbuf'),
    pants('src/python/twitter/common/threading'),
    pants('src/python/twitter/common/util'),
    pants('src/python/twitter/thrift/text'),
  ],
  sources=PANTS_SOURCES,
  resources=PANTS_RESOURCES,
)

python_binary(
  name='pants',
  entry_point='twitter.pants.bin.pants_exe:main',
  dependencies=[
    pants(':pants-lib')
  ],
  platforms=[
    'current',
    'macosx-10.4-x86_64',
    'linux-x86_64'
  ]
)

python_library(
  name='pants-packaged',
  dependencies=[
    pants(':pants-lib'),
  ],
  # TODO(wickman) This version should be automatically pulled in from twitter.pants.version
  provides=setup_py(
    name='twitter.pants',
    version='0.0.12',
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
    pants=pants(':pants'),
  )
)

python_binary(
  name='ng',
  dependencies=[
    pants('src/python/twitter/common/app'),
    pants('src/python/twitter/common/log'),

    # TODO(John Sirois): Break up pants src/ into proper libs - the ng client should not need all
    # of pants
    pants(':pants-lib')
  ],
  source=NG_CLIENT,
)

page(name='readme',
  source='README.md',
)
