__author__ = 'Ryan Williams'

from twitter.pants.targets.pants_target import Pants

def resolve(arg):
  """Wraps strings in Pants() targets, for BUILD file convenience.

    - single string literal gets wrapped in Pants() target
    - single Pants() target is left alone
    - list of strings and Pants() targets gets its strings wrapped, returning a list of Pants() targets
  """

  if arg is None:
    return None

  if isinstance(arg, str):
    return Pants(arg)

  if isinstance(arg, Pants):
    return arg

  return [Pants(dependency) if isinstance(dependency, str) else dependency for dependency in arg]
