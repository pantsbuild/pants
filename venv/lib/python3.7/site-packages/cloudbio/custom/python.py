"""Install instructions for python libraries not ready for easy_install.
"""
import os

from fabric.api import *
from fabric.contrib.files import *

from shared import _if_not_python_lib, _get_install, _python_make

@_if_not_python_lib("bx")
def install_bx_python(env):
    url = "hg clone http://bitbucket.org/james_taylor/bx-python"
    _get_install(url, env, _python_make)

@_if_not_python_lib("matplotlib")
def install_matplotlib(env):
    version = "1.0.1"
    url = "http://downloads.sourceforge.net/project/matplotlib/matplotlib/" \
          "matplotlib-%s/matplotlib-%s.tar.gz" % (version, version)
    _get_install(url, env, _python_make)

@_if_not_python_lib("rpy")
def install_rpy(env):
    version = "1.0.3"
    ext = "a"
    url = "http://downloads.sourceforge.net/project/rpy/rpy/" \
          "%s/rpy-%s%s.zip" % (version, version, ext)
    def _fix_libraries(env):
        run("""sed -i.bak -r -e "s/,'Rlapack'//g" setup.py""")
    _get_install(url, env, _python_make, post_unpack_fn=_fix_libraries)
