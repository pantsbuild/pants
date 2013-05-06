from twitter.pants.base import ParseContext

__author__ = 'Ryan Williams'

from twitter.pants.targets import InternalTarget, TargetWithSources


class MockTarget(InternalTarget, TargetWithSources):
  def __init__(self, name, dependencies=None, num_sources=0):
    with ParseContext.temp():
      InternalTarget.__init__(self, name, dependencies)
      TargetWithSources.__init__(self, name)
    self.num_sources = num_sources

  def resolve(self):
    yield self

  def walk(self, work, predicate=None):
    work(self)
    for dep in self.dependencies:
      dep.walk(work)

