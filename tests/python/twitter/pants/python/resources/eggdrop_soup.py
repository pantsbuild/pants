import sys

try:
  from lib import my_lib
  if my_lib.VALUE == 1:
    sys.exit(0)
except Exception, e:
  print 'Got exception trying to load my_lib: %s' % e
  pass

sys.exit(1)
