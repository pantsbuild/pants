
__author__ = 'Ryan Williams'

from twitter.pants.targets import InternalTarget

class MockTarget(InternalTarget):

  def __init__(self, id, dependencies = None, num_sources = 0):
    self.id = id
    self.address = id
    self.dependencies = dependencies if dependencies else []
    self.internal_dependencies = self.dependencies
    self.num_sources = num_sources

  def resolve(self):
    yield self

  def walk(self, work):
    work(self)
    for dep in self.dependencies:
      dep.walk(work)

