# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# A simple example to include in a python 3 binary target

def say_something():
  print('I am a python 3 library method.')
  # Return reduce function for testing purposes.
  # Note that reduce exists as a built-in in Python 2 and
  # does not exist in Python 3
  try:
  	ret = reduce
  except NameError:
  	ret = None
  assert ret == None
  return ret 
