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

python_library(
  name = 'antlr-3.1.3',
  dependencies = [egg("antlr_python_runtime-3.1.3-py2.6.egg")])

python_library(
  name = 'paramiko',
  dependencies = [
    pants(":pycrypto"),
    egg("paramiko-1.7.7.1-py2.6.egg")
  ]
)

python_library(
  name = 'py',
  dependencies = [egg("py-1.4.2-py2.6.egg")])

python_library(
  name = 'pycrypto',
  dependencies = [egg("pycrypto-2.3-*.egg")])

python_library(
  name = 'pytest',
  dependencies = [
    pants(":py"),
    egg("pytest-2.0.2-py2.6.egg"),
  ]
)

python_library(
  name = 'python-ldap',
  dependencies = [egg("python_ldap-*.egg")])

python_library(
  name = 'mako',
  dependencies = [egg("Mako-0.4.0-py2.6.egg")])

python_library(
  name = 'rbtools',
  dependencies = [egg("RBTools-0.2-py2.6.egg")])

python_library(
  name = 'thrift-0.7',
  dependencies = [egg("Thrift-0.7.0_dev-py2.6.egg")])

python_library(
  name = 'zookeeper',
  dependencies = [egg("ZooKeeper-*.egg")])
