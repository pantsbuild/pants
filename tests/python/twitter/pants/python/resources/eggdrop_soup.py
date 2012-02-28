from __future__ import print_function

import sys

try:
  from lib import my_lib
  if my_lib.VALUE == 1:
    sys.exit(0)
except Exception as e:
  print('Got exception trying to load my_lib: %s' % e)
  pass

sys.exit(1)
