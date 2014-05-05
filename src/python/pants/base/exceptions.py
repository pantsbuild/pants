

class TargetDefinitionException(Exception):
  """Thrown on errors in target definitions."""

  def __init__(self, target, msg):
    super(Exception, self).__init__('Error with %s: %s' % (target.address, msg))
