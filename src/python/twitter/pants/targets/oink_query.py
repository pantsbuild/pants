from twitter.pants.targets.jvm_target import JvmTarget

class OinkQuery(JvmTarget):

  def __init__(self, name, dependencies, sources=None, excludes=None):
    JvmTarget.__init__(self, name, sources, dependencies, excludes)
    # TODO: configurations is required when fetching jar_dependencies but should not be
    self.configurations = None
