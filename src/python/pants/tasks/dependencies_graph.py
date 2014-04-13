from pants.base.build_environment import get_buildroot
from pants.targets.pants_target import Pants
from pants.targets.sources import SourceRoot

__author__ = 'fkorotkov'

import json
import os

from .console_task import ConsoleTask

class DependenciesGraph(ConsoleTask):
  """Generates dependencies graph in JSON format"""

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(DependenciesGraph, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("format"), mkflag("format", negate=True), default=True,
                            action="callback", callback=mkflag.set_bool, dest="format",
                            help="[%default] Format the output.")

  def __init__(self, context):
    super(DependenciesGraph, self).__init__(context)
    self.format = self.context.options.format
    self.context.products.require_data('ivy_jar_products')

  @staticmethod
  def jar_id(jar):
    return '%s:%s:%s' % (jar.org, jar.name, jar.rev) if jar.rev else '%s:%s' % (jar.org, jar.name)

  def resolve_jars_info(self):
    mapping = {}
    jar_data = self.context.products.get_data('ivy_jar_products')
    if not jar_data: return mapping

    for dep in jar_data['default'] or list():
      for module in dep.modules_by_ref.values():
        mapping[self.jar_id(module.ref)] = [
          artifact.path for artifact in module.artifacts
        ]
    return mapping

  def console_output(self, targets):
    targets_map = {}

    def process_target(current_target):
      """
      :type current_target:pants.base.target.Target
      """

      info = {
        'targets': [],
        'libraries': [],
        'roots': [],
        'test_target': target.is_test
      }

      if hasattr(current_target, 'dependencies'):
        for dep in current_target.dependencies:
          if isinstance(dep, Pants):
            info['targets'].append(str(dep.address))

          if dep.is_jar:
            info['libraries'].append(self.jar_id(dep))

      if hasattr(current_target, 'sources'):
        source_root = SourceRoot.find(current_target)
        absolute_source_root = os.path.join(get_buildroot(), source_root)
        roots = list(set([os.path.dirname(source) for source in current_target.sources]))
        info['roots'] = map(lambda source: {
          'source_root': os.path.join(absolute_source_root, source),
          'package_prefix': source.replace('/', '.')
        }, roots)

      targets_map[str(current_target.address)] = info

    for target in targets:
      process_target(target)

    graph_info = {
      'targets': targets_map,
      'libraries': self.resolve_jars_info()
    }

    if not self.format:
      return [json.dumps(graph_info)]
    else:
      return json.dumps(graph_info, indent=4, separators=(',', ': ')).splitlines()