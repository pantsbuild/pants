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
