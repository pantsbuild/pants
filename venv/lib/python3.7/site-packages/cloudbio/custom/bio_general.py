"""Custom installs for biological packages.
"""
import os

from fabric.api import *
from fabric.contrib.files import *

from shared import (_if_not_installed, _get_install, _configure_make)

@_if_not_installed("embossversion")
def install_emboss(env):
    """Emboss target for platforms without packages (CentOS -- rpm systems).
    """
    version = "6.3.1"
    url = "ftp://emboss.open-bio.org/pub/EMBOSS/EMBOSS-%s.tar.gz" % version
    _get_install(url, env, _configure_make)
