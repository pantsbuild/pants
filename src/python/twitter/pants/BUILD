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

PANTS_SOURCES   = rglobs('*.py') - rglobs('bin/*.py')
PANTS_GARBAGE   = rglobs('*.pyc') + rglobs('*~')
PANTS_RESOURCES = rglobs('*') - PANTS_SOURCES - PANTS_GARBAGE

# Only build pylint on py 2.x
def pylint_build_filter():
  import sys
  return sys.version_info[0] == 2

python_library(
  name = 'pants-deps',
  dependencies = [
    python_requirement("elementtree"),
    python_requirement('mako'),
    python_requirement('markdown'),
    python_requirement('psutil'),
    python_requirement("pygments"),
    python_requirement("pylint", version_filter=pylint_build_filter),
    python_requirement("pytest"),
  ]
)

python_library(
  name = 'pants-lib',
  dependencies = [
    pants("src/python/twitter/common"),
    pants("src/python/twitter/common/app"),
    pants("src/python/twitter/common/confluence"),
    pants("src/python/twitter/common/python"),
    pants("src/python/twitter/common/lang"),
    pants(":pants-deps"),
  ],
  sources = PANTS_SOURCES,
  resources = PANTS_RESOURCES
)

python_binary(
  name = 'pants',
  dependencies = [
    pants(":pants-lib")
  ],
  source = 'bin/pants_exe.py',
)

python_binary(
  name = 'ng',
  dependencies = [
    pants('src/python/twitter/common/app'),
    pants('src/python/twitter/common/log')
  ],
  source = 'java/nailgun_client.py',
)

# TODO(John Sirois): add a BUILD.commons github wiki goal to the 'publish' phase and publish these

page(name = 'readme',
  source = 'README.md',
  dependencies = [
    pants('src/python/twitter/pants/docs:migration')
  ]
)
