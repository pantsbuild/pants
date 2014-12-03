# coding=utf-8

import logging
import os
import yaml


from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.base.build_environment import get_buildroot


_YAML_FILENAME = "pants.yaml"

logger = logging.getLogger(__file__)


class Exclude(object):
  def __init__(self, org, name=None):
    self.org = org
    self.name = name


class JarDependencyWithGlobalExcludes(JarDependency):
  """Automatically append all 'excludes' defined in pants.yaml to a JarDependency target

  This target is aliased to 'sjar' in register.py
  """

  global_excludes = []
  loaded = False

  def __init__(self, org, name, rev = None, force = False, ext = None, url = None, apidocs = None,
               type_ = None, classifier = None):
    super(JarDependencyWithGlobalExcludes, self).__init__(org, name, rev, force, ext, url, apidocs,
        type_, classifier)
    self.excludes = [] + [e for e in self.global_excludes if not (e.org == org and e.name == name)]

  @classmethod
  def exclude_globally(cls, org, name):
    """Add a single exclude to the list of global excludes"""
    cls.global_excludes.append(Exclude(org, name))

  @classmethod
  def load_excludes_from_yaml(self, yaml_dir=None):
    yaml_dir = yaml_dir or get_buildroot()
    yaml_path = os.path.join(yaml_dir, _YAML_FILENAME)
    if not os.path.exists(yaml_path):
      logger.debug("{yaml_path} yaml file not found to load global excludes.".format(yaml_path))
    else:
      with open(yaml_path, 'r') as yaml_file:
        contents = yaml_file.read()
        pants_yaml_dict = yaml.load(contents)
        for exclude in pants_yaml_dict['excludes']:
          self.exclude_globally(org=exclude['org'], name=exclude['name'])

