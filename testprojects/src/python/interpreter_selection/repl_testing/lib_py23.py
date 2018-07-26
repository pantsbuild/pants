def say_something():
  print('I am a python 2/3 library method.')
  # Note that ascii exists as a built-in in Python 3 and
  # does not exist in Python 2.
  try:
    ret = ascii
  except NameError:
    ret = None
  return 'Python2' if ret is None else 'Python3'