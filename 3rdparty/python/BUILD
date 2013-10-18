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
#
# Dependencies for the open source Twitter Commons

def make_dep(name, version, dependency_name=None):
  """Build a target from a specified dependency tuple.

    name is the target name, specified in other BUILD files.
    version is a hardcoded version string
    dependency_name is used to identify the specific binary to resolve
  """
  dependency_name = dependency_name or name
  versioned_name = "%s==%s" % (dependency_name, version)
  python_requirement(requirement=versioned_name, name=name)


make_dep('ansicolors', '1.0.2')
make_dep('antlr-python-runtime', '3.1.3', 'antlr_python_runtime')
make_dep('bottle', '0.11.6')
make_dep('distribute', '0.6.28')
make_dep('elementtree', '1.2.7_20070827_preview')
make_dep('futures', '2.1.2')
make_dep('git-python', '0.3.2.RC1', 'GitPython')
make_dep('kazoo', '1.3.1')
make_dep('kerberos', '1.1.1')
make_dep('mako', '0.4.0', 'Mako')
make_dep('markdown', '2.1.1', 'Markdown')
make_dep('mock', '1.0.1')
make_dep('mox', '0.5.3')
make_dep('psutil', '0.5.0')
make_dep('pure-sasl', '0.1.4')
make_dep('pyfakefs', '2.3')
make_dep('pygments', '1.4', 'Pygments')
make_dep('pylint', '0.25.1')
make_dep('pytest', '2.3.5')
make_dep('pytest-cov', '1.6')
make_dep('socksipy-branch', '1.03', 'SocksiPy-Branch')
make_dep('thrift', '0.9.0')
make_dep('zc-zookeeper-static', '3.4.4')
