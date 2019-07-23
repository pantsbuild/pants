"""Install instructions for distributed MapReduce style programs.
"""
import os

from fabric.api import *
from fabric.contrib.files import *

from shared import _if_not_installed, _make_tmp_dir, _if_not_python_lib, _fetch_and_unpack

@_if_not_python_lib("pydoop")
def install_pydoop(env):
    """Install pydoop; provides Hadoop access for Python.

    http://pydoop.sourceforge.net/docs/installation.html
    """
    hadoop_version = "0.20.2"
    pydoop_version = "0.3.7_rc1"
    ubuntu_hadoop_src = "/usr/src/hadoop-0.20"
    hadoop_url = "http://apache.mirrors.hoobly.com/hadoop/core/" \
            "hadoop-%s/hadoop-%s.tar.gz" % (hadoop_version, hadoop_version)
    pydoop_url ="http://downloads.sourceforge.net/project/pydoop/" \
                "Pydoop-%s/pydoop-%s.tar.gz" % (pydoop_version, pydoop_version)
    java_home = env.java_home if env.has_key("java_home") else os.environ["JAVA_HOME"]
    pyext = env.python_version_ext if env.has_key("python_version_ext") else ""

    with _make_tmp_dir() as work_dir:
        with cd(work_dir):
            pydoop_dir = _fetch_and_unpack(pydoop_url)
            # Use native supplied Hadoop source to match installed defaults. On
            # Ubuntu this is currently 0.20.2.
            if exists(ubuntu_hadoop_src):
                hadoop_dir = ubuntu_hadoop_src
                with cd(pydoop_dir):
                    sed("setup.py", "src/c", "c")
            else:
                hadoop_dir = _fetch_and_unpack(hadoop_url)
            with cd(pydoop_dir):
                export_str = "export HADOOP_VERSION=%s && export HADOOP_HOME=%s " \
                             "&& export JAVA_HOME=%s" % (hadoop_version,
                                os.path.join(os.pardir, hadoop_dir), java_home)
                run("%s && python%s setup.py build" % (export_str, pyext))
                env.safe_sudo("%s && python%s setup.py install --skip-build" %
                              (export_str, pyext))

def install_mahout(env):
    # ToDo setup mahout, must be checked out from repo ATM:
    # https://cwiki.apache.org/MAHOUT/mahoutec2.html
    pass
