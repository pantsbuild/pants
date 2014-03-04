import os

from contextlib import contextmanager

from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.base.target import Target
from twitter.pants.targets.sources import SourceRoot
from twitter.pants.tasks.roots import ListRoots
from twitter.pants.tasks.test_base import ConsoleTaskTest


@contextmanager
def register_sourceroot():
  try:
    yield SourceRoot.register
  except (ValueError, IndexError) as e:
    print("SourceRoot Registration Failed.")
    raise e
  finally:
    SourceRoot.reset()


class ListRootsTest(ConsoleTaskTest):

  class TypeA(Target):
    pass

  class TypeB(Target):
    pass

  @classmethod
  def task_type(cls):
    return ListRoots

  def test_roots_without_register(self):
    try:
      self.assert_console_output()
    except AssertionError:
      self.fail("./pants goal roots failed without any registered SourceRoot.")

  def test_no_source_root(self):
    with register_sourceroot() as sourceroot:
      sourceroot(os.path.join(get_buildroot(), "fakeroot"))
      self.assert_console_output('fakeroot: *')

  def test_single_source_root(self):
    with register_sourceroot() as sourceroot:
      sourceroot(os.path.join(get_buildroot(), "fakeroot"), ListRootsTest.TypeA,
                                                            ListRootsTest.TypeB)
      self.assert_console_output("fakeroot: TypeA,TypeB")

  def test_multiple_source_root(self):
    with register_sourceroot() as sourceroot:
      sourceroot(os.path.join(get_buildroot(), "fakerootA"), ListRootsTest.TypeA)
      sourceroot(os.path.join(get_buildroot(), "fakerootB"), ListRootsTest.TypeB)
      self.assert_console_output('fakerootA: TypeA', 'fakerootB: TypeB')
