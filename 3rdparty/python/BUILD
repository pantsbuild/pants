# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

def make_dep(name, version, dependency_name=None):
  """Build a target from a specified dependency tuple.

    name is the target name, specified in other BUILD files.
    version is a hardcoded version string
    dependency_name is used to identify the specific binary to resolve
  """
  dependency_name = dependency_name or name
  versioned_name = "%s==%s" % (dependency_name, version)
  return python_requirement(requirement=versioned_name, name=name)


make_dep('ansicolors', '1.0.2')
make_dep('antlr-3.1.3', '3.1.3', 'antlr_python_runtime')
make_dep('bottle', '0.11.6')
make_dep('coverage', '3.7.1')
make_dep('elementtree', '1.2.7_20070827_preview')
make_dep('futures', '2.1.2')
make_dep('git-python', '0.3.2.RC1', 'GitPython')
make_dep('kazoo', '1.3.1')
make_dep('kerberos', '1.1.1')
make_dep('mako', '0.4.0', 'Mako')
make_dep('markdown', '2.1.1', 'Markdown')
make_dep('mock', '1.0.1')
make_dep('mox', '0.5.3')
make_dep('psutil', '1.1.2')
make_dep('pure-sasl', '0.1.4')
make_dep('pyfakefs', '2.3')
make_dep('pygments', '1.4', 'Pygments')
make_dep('pystache', '0.5.3')
make_dep('pytest', '2.5.2')
make_dep('pytest-cov', '1.6')
make_dep('python_daemon', '1.5.5')
make_dep('requests', '2.0.0')
make_dep('setuptools', '2.2')
make_dep('socksipy-branch', '1.01', 'SocksiPy-Branch')
make_dep('thrift', '0.9.1')
make_dep('zc-zookeeper-static', '3.4.4')

dependencies(name='antlr-python-runtime', dependencies=[':antlr-3.1.3'])


# twitter.common deps.
# TODO: Make these regular egg deps.

SHA = '0741ced0f787771d82b5703bddb2990e2d3dcae7'

REPO = ('http://pantsbuild.github.io/cheeseshop/third_party/twitter-commons/%s/index.html' % SHA)

def commons_dep(name):
  return python_requirement(requirement='twitter.common.%s' % name, repository=REPO)

commons_dep('collections')
commons_dep('config')
commons_dep('confluence')
commons_dep('contextutil')
commons_dep('decorators')
commons_dep('dirutil')
commons_dep('lang')
commons_dep('log')
commons_dep('process')
commons_dep('python')
commons_dep('quantity')
commons_dep('rwbuf') # XXX(fixme)
commons_dep('threading')
commons_dep('util')
