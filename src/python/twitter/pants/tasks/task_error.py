from twitter.pants.base import manual


@manual.builddict()
class TaskError(Exception):
  """
    Raised to indicate a task has failed.

    :param int exit_code: an optional exit code (1, by default)
  """
  def __init__(self, *args, **kwargs):
    self._exit_code = kwargs.pop('exit_code', 1)
    super(TaskError, self).__init__(*args, **kwargs)

  @property
  def exit_code(self):
    return self._exit_code
