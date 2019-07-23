"""An Edition reflects a base install, the default being BioLinux.

Editions are shared between multiple projects. To specialize an edition, create
a Flavor instead.

Other editions can be found in this directory
"""

from cloudbio.edition.base import Edition, Minimal, BioNode

_edition_map = {None: Edition,
                "minimal": Minimal,
                "bionode": BioNode}

def _setup_edition(env):
    """Setup one of the BioLinux editions (which are derived from
       the Edition base class)
    """
    # fetch Edition from environment and load relevant class. Use
    # an existing edition, if possible, and override behaviour through
    # the Flavor mechanism.
    edition_class = _edition_map[env.get("edition", None)]
    env.edition = edition_class(env)
    env.logger.debug("%s %s" % (env.edition.name, env.edition.version))
    env.logger.info("This is a %s" % env.edition.short_name)
