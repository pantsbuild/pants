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

PANTS_SOURCES   = rglobs('*.py')
PANTS_GARBAGE   = rglobs('*.pyc') + rglobs('*~')
PANTS_RESOURCES = rglobs('*') - PANTS_SOURCES - PANTS_GARBAGE

# Only build pylint on py 2.x
def pylint_build_filter():
  import sys
  return sys.version_info[0] == 2

python_library(
  name = 'pants-deps',
  dependencies = [
    python_requirement("ansicolors"),
    python_requirement("elementtree"),
    python_requirement('Markdown'),
    python_requirement("pygments"),
    python_requirement("pylint", version_filter=pylint_build_filter),
    python_requirement('pystache'),
    python_requirement("pytest"),
    python_requirement("pytest-cov"),
    python_requirement("python_daemon"),
  ]
)

python_library(
  name = 'pants-lib',
  dependencies = [
    pants("src/python/twitter/common"),
    pants("src/python/twitter/common/app"),
    pants("src/python/twitter/common/confluence"),
    pants("src/python/twitter/common/dirutil"),
    pants("src/python/twitter/common/lang"),
    pants("src/python/twitter/common/process"),
    pants("src/python/twitter/common/python"),
    pants("src/python/twitter/common/util"),
    pants("src/python/twitter/thrift/text"),
    pants(":pants-deps")
  ],
  sources = PANTS_SOURCES,
  resources = PANTS_RESOURCES,
  provides = setup_py(
    name = 'twitter.pants',
    version = '0.0.3',
    description = 'the pants build tool',
    namespace_packages = [
      'twitter',
      'twitter.common',
    ]
  )
)

python_binary(
  name = 'pants',
  entry_point = 'twitter.pants.bin.pants_exe',
  dependencies = [
    pants(":pants-lib")
  ],
  platforms = [
    'current',
    'macosx-10.4-x86_64',
    'linux-x86_64'
  ]
)

python_binary(
  name = 'ng',
  dependencies = [
    'src/python/twitter/common/app',
    'src/python/twitter/common/log',
  ],
  source = 'java/nailgun_client.py',
)

# TODO(John Sirois): add a BUILD.commons github wiki goal to the 'publish' phase and publish these

page(name = 'readme',
  source = 'README.md',
  dependencies = [
    pants('src/python/twitter/pants/docs:migration'),
    pants('src/python/twitter/pants/docs:internals'),
    pants('src/python/twitter/pants/docs:setuprepo'),
    pants(':install'),
  ]
)

page(name = 'install',
  source = 'INSTALL.md',
)
