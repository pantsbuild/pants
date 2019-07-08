"""Base editions supplying CloudBioLinux functionality which can be customized.

These are a set of testing and supported edition classes.
"""
from fabric.api import *

class Edition:
    """Base class. Every edition derives from this
    """
    def __init__(self, env):
        self.name = "BioLinux base Edition"
        self.short_name = "biolinux"
        self.version = env.version
        self.env = env
        self.check_distribution()

    def check_distribution(self):
        """Ensure the distribution matches an expected type for this edition.

        Base supports multiple distributions.
        """
        pass

    def check_packages_source(self):
        """Override for check package definition file before updating
        """
        pass

    def rewrite_apt_sources_list(self, sources):
        """Allows editions to modify the sources list
        """
        return sources

    def rewrite_apt_automation(self, package_info):
        """Allows editions to modify the apt automation list
        """
        return package_info

    def rewrite_apt_keys(self, standalone, keyserver):
        """Allows editions to modify key list"""
        return standalone, keyserver

    def apt_upgrade_system(self):
        """Upgrade system through apt - so this behaviour can be overridden
        """
        sudo("apt-get -y --force-yes upgrade")

    def post_install(self):
        """Post installation hook"""
        pass

    def rewrite_config_items(self, name, items):
        """Generic hook to rewrite a list of configured items.

        Can define custom dispatches based on name: packages, custom,
        python, ruby, perl
        """
        return items


class BioNode(Edition):
    """BioNode specialization of BioLinux
    """
    def __init__(self, env):
        Edition.__init__(self,env)
        self.name = "BioNode Edition"
        self.short_name = "bionode"

    def check_distribution(self):
        if self.env.distribution not in ["debian"]:
            raise ValueError("Distribution is not pure Debian")

    def check_packages_source(self):
        # Bionode removes sources, just to be sure
        self.env.logger.debug("Clearing %s" % self.env.sources_file)
        sudo("cat /dev/null > %s" % self.env.sources_file)

    def rewrite_apt_sources_list(self, sources):
        self.env.logger.debug("BioNode.rewrite_apt_sources_list!")
        # See if the repository is defined in env
        if not env.get('debian_repository'):
            main_repository = 'http://ftp.us.debian.org/debian/'
        else:
            main_repository = env.debian_repository
        # The two basic repositories
        new_sources = ["deb {repo} {dist} main contrib non-free".format(repo=main_repository,
                                                                        dist=env.dist_name),
                       "deb {repo} {dist}-updates main contrib non-free".format(
                           repo=main_repository, dist=env.dist_name)]
        return sources + new_sources

class Minimal(Edition):
    """Minimal specialization of BioLinux
    """
    def __init__(self, env):
        Edition.__init__(self, env)
        self.name = "Minimal Edition"
        self.short_name = "minimal"

    def rewrite_apt_sources_list(self, sources):
        """Allows editions to modify the sources list. Minimal only
           uses the barest default packages
        """
        return []

    def rewrite_apt_automation(self, package_info):
        return []

    def rewrite_apt_keys(self, standalone, keyserver):
        return [], []

    def apt_upgrade_system(self):
        """Do nothing"""
        env.logger.debug("Skipping forced system upgrade")

    def rewrite_config_items(self, name, items):
        """Generic hook to rewrite a list of configured items.

        Can define custom dispatches based on name: packages, custom,
        python, ruby, perl
        """
        return items

