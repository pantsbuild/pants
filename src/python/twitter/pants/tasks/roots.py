from twitter.pants.targets.sources import SourceRoot

from .console_task import ConsoleTask


class ListRoots(ConsoleTask):
  """
  List the registered source roots of the repo.
  """

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ListRoots, cls).setup_parser(option_group, args, mkflag)

  def console_output(self, targets):
    for src_root, targets in SourceRoot.all_roots().items():
      all_targets = ','.join(sorted([tgt.__name__ for tgt in targets]))
      yield '%s: %s' % (src_root, all_targets or '*')
