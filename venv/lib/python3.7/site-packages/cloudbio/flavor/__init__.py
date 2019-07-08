"""A Flavor reflects a specialization of a base install, the default being BioLinux.

If you want to create a new specialization (say for your own server), the
recommended procedure is to choose an existing base install (Edition) and write
a Flavor. When your Flavor is of interest to other users, it may be a good idea
to commit it to the main project (in ./contrib/flavor).

Other (main) flavors can be found in this directory and in ./contrib/flavors
"""

from fabric.api import *

class Flavor:
    """Base class. Every flavor derives from this
    """
    def __init__(self, env):
        self.name = "Base Flavor - no overrides"
        self.env = env

    def rewrite_config_items(self, name, items):
        """Generic hook to rewrite a list of configured items.

        Can define custom dispatches based on name: packages, custom,
        python, ruby, perl
        """
        return items

    def post_install(self):
        """Post installation hook"""

env.flavor = Flavor(env)
