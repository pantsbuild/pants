from pants.contrib.mypy.tasks.mypy_task import MypyTask, MypyTaskError
from pants_test.task_test_base import TaskTestBase
from pants.backend.python.targets.python_library import PythonLibrary


class MyPyTests(TaskTestBase):

  @classmethod
  def task_type(cls):
    return MypyTask

  def test_raises_no_error_on_all_whitelisted_target_roots(self):
    t1 = self.make_target('t1', PythonLibrary, tags=['type_checked'])
    t2 = self.make_target('t2', PythonLibrary, tags=['type_checked'])
    task = self.create_task(self.context(target_roots=[t1, t2]))
    task.execute()

  def test_raises_no_error_on_some_whitelisted_target_roots_but_all_whitelisted_in_context(self):
    t1 = self.make_target('t1', PythonLibrary)
    t2 = self.make_target('t2', PythonLibrary, tags=['type_checked'])
    t3 = self.make_target('t3', PythonLibrary, tags=['type_checked'], dependencies=[t2])
    task = self.create_task(self.context(target_roots=[t1, t3]))
    task.execute()

  def test_raises_error_on_some_whitelisted_target_roots_but_all_whitelisted_in_context(self):
    t1 = self.make_target('t1', PythonLibrary)
    t2 = self.make_target('t2', PythonLibrary, tags=['something_else'])
    t3 = self.make_target('t3', PythonLibrary, tags=['type_checked'], dependencies=[t2])
    task = self.create_task(self.context(target_roots=[t1, t3]))
    with self.assertRaises(MypyTaskError):
      task.execute()

  def test_raises_error_on_all_whitelisted_target_roots_but_some_whitelisted_transitive_targets(self):
    t1 = self.make_target('t1', PythonLibrary, tags=['type_checked'])
    t2 = self.make_target('t2', PythonLibrary, tags=['something_else'])
    t3 = self.make_target('t3', PythonLibrary, tags=['type_checked'], dependencies=[t2])
    t4 = self.make_target('t4', PythonLibrary, tags=['type_checked'], dependencies=[t3])
    task = self.create_task(self.context(target_roots=[t1, t4]))
    with self.assertRaises(MypyTaskError):
      task.execute()
