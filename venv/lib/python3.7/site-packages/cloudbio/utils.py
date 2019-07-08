"""Utilities for logging and progress tracking.
"""
import logging

from fabric.api import sudo

def _setup_logging(env):
    env.logger = logging.getLogger("cloudbiolinux")
    env.logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    # create formatter
    formatter = logging.Formatter('%(name)s %(levelname)s: %(message)s')
    # add formatter to ch
    ch.setFormatter(formatter)
    env.logger.addHandler(ch)

def _update_biolinux_log(env, target, flavor):
    """Updates the VM so it contains information on the latest BioLinux
       update in /var/log/biolinux.log.

       The latest information is appended to the file and can be used to see if
       an installation/update has completed (see also ./test/test_vagrant).
    """
    if not target:
        target = env.get("target", None)
        if not target:
            target = "unknown"
        else:
            target = target.name
    if not flavor:
        flavor = env.get("flavor", None)
        if not flavor:
            flavor = "unknown"
        else:
            flavor = flavor.name
    logfn = "/var/log/biolinux.log"
    info = "Target="+target+"; Edition="+env.edition.name+"; Flavor="+flavor
    env.logger.info(info)
    sudo("date +\"%D %T - Updated "+info+"\" >> "+logfn)
