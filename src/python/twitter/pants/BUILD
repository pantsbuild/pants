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

python_library(
  name = 'pants-lib',
  dependencies = [
    pants("3rdparty/python:elementtree"),
    pants("3rdparty/python:lxml"),
    pants("3rdparty/python:mako"),
    pants("3rdparty/python:markdown"),
    pants("3rdparty/python:psutil"),
    pants("3rdparty/python:pylint"),
    pants("3rdparty/python:pytest"),
    pants("src/python/twitter/common"),
    pants("src/python/twitter/common/app"),
    pants("src/python/twitter/common/python")
  ],
  sources = PANTS_SOURCES,
  resources = PANTS_RESOURCES
)

python_binary(
  name = 'pants',
  dependencies = [pants(":pants-lib")],
  source = 'bin/pants_exe.py',
)

python_binary(
  name = 'ng',
  dependencies = [pants(":pants-lib")],
  source = 'java/nailgun_client.py',
)
