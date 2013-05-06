from .console_task import ConsoleTask
from twitter.pants.targets import SourceRoot


class ListRoots(ConsoleTask):
  """
  List the registered source roots of the repo.
  """

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ListRoots, cls).setup_parser(option_group, args, mkflag)

  @classmethod
  def console_output(self, targets):
    for srcroot, targets in SourceRoot.all_roots().items():
      all_targets = ",".join(sorted([tgt.__name__ for tgt in targets]))
      yield "%s: %s" % (srcroot, all_targets)
