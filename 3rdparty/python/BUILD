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

def make_dep(name, dependency_name=None):
  dependency_name = dependency_name or name
  python_library(
    name=name,
    dependencies=[python_requirement(dependency_name)]
  )

make_dep('antlr-3.1.3', 'antlr_python_runtime==3.1.3')
make_dep('beautifulsoup', 'BeautifulSoup==3.2.0')
make_dep('boto', 'boto==2.0')
make_dep('bottle')
make_dep('cherrypy')
make_dep('coverage')
make_dep('dateutil', 'python-dateutil==1.5')
make_dep('dingus', 'dingus==0.3.4')
make_dep('django', 'Django>=1.3.1,<1.4')
make_dep('django_auth_ldap', 'django_auth_ldap==1.0.14')
make_dep('django_cpserver')
make_dep('elementtree')
make_dep('futures')
make_dep('gchartwrapper', 'GChartWrapper==0.9')
make_dep('gflags', 'python-gflags')
make_dep('git-python', 'GitPython')
make_dep('jenkinsapi', 'jenkinsapi==0.1.16')
make_dep('jira-python-0.9', 'jira-python==0.9')
# TODO(wickman) Update this to kazoo==1.2 once they cut a release
# with our patches.
make_dep('kazoo', 'kazoo==1.1dev')
make_dep('ldap', 'python-ldap')
make_dep('lxml', 'lxml==2.3.1')
make_dep('mako')
make_dep('markdown')
make_dep('markupsafe', 'MarkupSafe==0.15')
make_dep('MySQLdb', 'MySQL-python==1.2.3')
make_dep('paramiko')
make_dep('pil', 'PIL==1.1.7')
make_dep('ply')
make_dep('porterstemmer', 'PorterStemmer==0.3')
make_dep('poster', 'poster==0.8.2') # Twitter's monkeypatched poster
make_dep('protobuf')
make_dep('psutil', 'psutil==0.5.0')
make_dep('pycrypto')
make_dep('pygments', 'Pygments==1.4')
make_dep('pylint')
make_dep('pystache', 'pystache==0.3.1')
make_dep('pystachio')
make_dep('pytest')
make_dep('python-ldap', 'python-ldap==2.3.13')
make_dep('python-memcached', 'python-memcached==1.47')
make_dep('python_twitter', 'python-twitter==0.8.2')
make_dep('pytz')
make_dep('pyyaml')
make_dep('redis', 'redis==2.4.9')
make_dep('thrift')
make_dep('tornado')
make_dep('twython', 'twython==1.4.3')
make_dep('zookeeper', 'zc-zookeeper-static')
