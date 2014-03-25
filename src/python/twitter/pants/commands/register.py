
from twitter.pants.commands.build import Build
from twitter.pants.commands.goal import Goal
from twitter.pants.commands.help import Help
from twitter.pants.commands.py import Py
from twitter.pants.commands.setup_py import SetupPy

def register_commands():
  for cmd in (Build, Goal, Help, Py, SetupPy):
    cmd._register()
