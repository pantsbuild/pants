# =================================================================================================
# Copyright 2011 Twitter, Inc.
# -------------------------------------------------------------------------------------------------
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
# =================================================================================================


from __future__ import print_function

import os
import sys

from twitter.pants.version import VERSION as _VERSION


def get_version():
  return _VERSION


_BUILDROOT = None


def get_buildroot():
  """Returns the pants ROOT_DIR, calculating it if needed."""

  global _BUILDROOT
  if not _BUILDROOT:
    if 'PANTS_BUILD_ROOT' in os.environ:
      set_buildroot(os.environ['PANTS_BUILD_ROOT'])
    else:
      buildroot = os.path.abspath(os.getcwd())
      while not os.path.exists(os.path.join(buildroot, 'pants.ini')):
        if buildroot != os.path.dirname(buildroot):
          buildroot = os.path.dirname(buildroot)
        else:
          print('Could not find pants.ini!', file=sys.stderr)
          sys.exit(1)
      set_buildroot(buildroot)
  return _BUILDROOT


def set_buildroot(path):
  """Sets the pants ROOT_DIR.

  Generally only useful for tests.
  """
  if not os.path.exists(path):
    raise ValueError('Build root does not exist: %s' % path)
  global _BUILDROOT
  _BUILDROOT = os.path.realpath(path)


from twitter.pants.scm import Scm

_SCM = None
def get_scm():
  """Returns the pants Scm if any."""
  return _SCM


def set_scm(scm):
  """Sets the pants Scm."""
  if scm is not None:
    if not isinstance(scm, Scm):
      raise ValueError('The scm must be an instance of Scm, given %s' % scm)
    global _SCM
    _SCM = scm


def maven_layout():
  """Sets up typical maven project source roots for all built-in pants target types."""

  source_root('src/main/antlr', java_antlr_library, page, python_antlr_library)
  source_root('src/main/java', annotation_processor, java_library, jvm_binary, page)
  source_root('src/main/protobuf', java_protobuf_library, page)
  source_root('src/main/python', page, python_binary, python_library)
  source_root('src/main/resources', page, resources)
  source_root('src/main/scala', jvm_binary, page, scala_library)
  source_root('src/main/thrift', java_thrift_library, page, python_thrift_library)

  source_root('src/test/java', java_library, junit_tests, page)
  source_root('src/test/python', page, python_library, python_tests, python_test_suite)
  source_root('src/test/resources', page, resources)
  source_root('src/test/scala', junit_tests, page, scala_library, scala_specs)
