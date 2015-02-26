# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet

from pants.backend.python.python_artifact import PythonArtifact
from pants.base.build_environment import get_buildroot, pants_version
from pants.base.build_file_aliases import BuildFileAliases


def pants_setup_py(name, description, namespace_packages=None, additional_classifiers=None):
  """Creates the setup_py for a pants artifact.

  :param str name: The name of the package.
  :param str description: A brief description of what the package provides.
  :param list additional_classifiers: Any additional trove classifiers that apply to the package,
                                      see: https://pypi.python.org/pypi?%3Aaction=list_classifiers
  :returns: A setup_py suitable for building and publishing pants components.
  """
  standard_classifiers = [
      'Intended Audience :: Developers',
      'License :: OSI Approved :: Apache Software License',
      # We know for a fact these OSs work but, for example, know Windows
      # does not work yet.  Take the conservative approach and only list OSs
      # we know pants works with for now.
      'Operating System :: MacOS :: MacOS X',
      'Operating System :: POSIX :: Linux',
      'Programming Language :: Python',
      'Topic :: Software Development :: Build Tools']
  classifiers = OrderedSet(standard_classifiers + (additional_classifiers or []))

  def _read_contents(path):
    with open(os.path.join(get_buildroot(), path), 'rb') as fp:
      return fp.read()

  return PythonArtifact(
      name=name,
      version=pants_version(),
      description=description,
      long_description=(_read_contents('src/python/pants/ABOUT.rst') +
                        _read_contents('src/python/pants/CHANGELOG.rst')),
      url='https://github.com/pantsbuild/pants',
      license='Apache License, Version 2.0',
      zip_safe=True,
      namespace_packages=namespace_packages,
      classifiers=list(classifiers))


def contrib_setup_py(name, description, additional_classifiers=None):
  """Creates the setup_py for a pants contrib plugin artifact.

  :param str name: The name of the package; must start with 'pantsbuild.pants.contrib.'.
  :param str description: A brief description of what the plugin provides.
  :param list additional_classifiers: Any additional trove classifiers that apply to the plugin,
                                      see: https://pypi.python.org/pypi?%3Aaction=list_classifiers
  :returns: A setup_py suitable for building and publishing pants components.
  """
  if not name.startswith('pantsbuild.pants.contrib.'):
    raise ValueError("Contrib plugin package names must start with 'pantsbuild.pants.contrib.', "
                     "given {}".format(name))

  return pants_setup_py(name,
                        description,
                        namespace_packages=['pants', 'pants.contrib'],
                        additional_classifiers=additional_classifiers)


def build_file_aliases():
  return BuildFileAliases.create(
    objects={
      'pants_setup_py': pants_setup_py,
      'contrib_setup_py': contrib_setup_py
    }
  )
