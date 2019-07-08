"""Build instructions associated with CloudMan.

http://wiki.g2.bx.psu.edu/Admin/Cloud

Adapted from Enis Afgan's code: https://bitbucket.org/afgane/mi-deployment
"""

cm_upstart = """
description     "Start CloudMan contextualization script"

start on runlevel [2345]

task
exec python %s
"""
import os

from fabric.api import sudo, run, put
from fabric.contrib.files import exists, settings, contains, append

REPO_ROOT_URL = "https://bitbucket.org/afgane/mi-deployment/raw/tip"

def _configure_cloudman(env, use_repo_autorun=False):
    _setup_users(env)
    _configure_ec2_autorun(env, use_repo_autorun)
    _configure_sge(env)
    _configure_nfs(env)

def _setup_users(env):
    def _add_user(username, uid=None):
        """ Add user with username to the system """
        if not contains('/etc/passwd', "%s:" % username):
            uid_str = "--uid %s" % uid if uid else ""
            sudo('useradd -d /home/%s --create-home --shell /bin/bash ' \
                 '-c"Galaxy-required user" %s --user-group %s' % \
                     (username, uid_str, username))
    # Must specify uid for 'galaxy' user because of the configuration for proFTPd
    _add_user('galaxy', '1001')
    _add_user('sgeadmin')
    _add_user('postgres')

def _configure_ec2_autorun(env, use_repo_autorun=False):
    script = "ec2autorun.py"
    remote = os.path.join(env.install_dir, "bin", script)
    if use_repo_autorun:
        url = os.path.join(REPO_ROOT_URL, script)
        sudo("wget --output-document=%s %s" % (remote, url))
    else:
        install_file_dir = os.path.join(env.config_dir, os.pardir, "installed_files")
        put(os.path.join(install_file_dir, script), remote, mode=0777, use_sudo=True)
    # Create upstart configuration file for boot-time script
    cloudman_boot_file = 'cloudman.conf'
    with open( cloudman_boot_file, 'w' ) as f:
        print >> f, cm_upstart % remote
    remote_file = '/etc/init/%s' % cloudman_boot_file
    put(cloudman_boot_file, remote_file, use_sudo=777)
    os.remove(cloudman_boot_file)

def _configure_sge(env):
    """This method only sets up the environment for SGE w/o actually setting up SGE"""
    sge_root = '/opt/sge'
    if not exists(sge_root):
        sudo("mkdir -p %s" % sge_root)
        sudo("chown sgeadmin:sgeadmin %s" % sge_root)
    # link our installed SGE to CloudMan's expected directory
    sge_package_dir = "/opt/galaxy/pkg"
    sge_dir = "ge6.2u5"
    sudo("mkdir -p %s" % sge_package_dir)
    if not exists(os.path.join(sge_package_dir, sge_dir)):
        sudo("ln -s %s/%s %s/%s" % (env.install_dir, sge_dir, sge_package_dir, sge_dir))

def _configure_nfs(env):
    nfs_dir = "/export/data"
    cloudman_dir = "/mnt/galaxyData/export"
    sudo("mkdir -p %s" % os.path.dirname(nfs_dir))
    sudo("chown -R ubuntu %s" % os.path.dirname(nfs_dir))
    with settings(warn_only=True):
        run("ln -s %s %s" % (cloudman_dir, nfs_dir))
    exports = [ '/opt/sge           *(rw,sync,no_root_squash,no_subtree_check)',
                '/mnt/galaxyData    *(rw,sync,no_root_squash,subtree_check,no_wdelay)',
                '/mnt/galaxyIndices *(rw,sync,no_root_squash,no_subtree_check)',
                '/mnt/galaxyTools   *(rw,sync,no_root_squash,no_subtree_check)',
                '%s       *(rw,sync,no_root_squash,no_subtree_check)' % nfs_dir,
                '%s/openmpi         *(rw,sync,no_root_squash,no_subtree_check)' % env.install_dir]
    append('/etc/exports', exports, use_sudo=True)

def _cleanup_ec2(env):
    """Clean up any extra files after building.
    """
    env.logger.info("Cleaning up for EC2 AMI creation")
    fnames = [".bash_history", "/var/log/firstboot.done", ".nx_setup_done",
              "/var/crash/*", "%s/ec2autorun.py.log" % env.install_dir]
    for fname in fnames:
        sudo("rm -f %s" % fname)
    rmdirs = ["/mnt/galaxyData", "/mnt/cm", "/tmp/cm"]
    for rmdir in rmdirs:
        sudo("rm -rf %s" % rmdir)
    # Stop Apache from starting automatically at boot (it conflicts with Galaxy's nginx)
    sudo('/usr/sbin/update-rc.d -f apache2 remove')

    # RabbitMQ fails to start if its database is embedded into the image
    # because it saves the current IP address or host name so delete it now.
    # When starting up, RabbitMQ will recreate that directory.
    with settings(warn_only=True):
        sudo('/etc/init.d/rabbitmq-server stop')
        sudo('stop rabbitmq-server')
        sudo('/etc/init.d/rabbitmq-server stop')
    sudo('initctl reload-configuration')
    for db_location in ['/var/lib/rabbitmq/mnesia', '/mnesia']:
        if exists(db_location):
            sudo('rm -rf %s' % db_location)
    # remove existing ssh host key pairs
    # http://docs.amazonwebservices.com/AWSEC2/latest/UserGuide/index.html?AESDG-chapter-sharingamis.htm
    sudo("rm -f /etc/ssh/ssh_host_*")
