from fabric.api import *
from fabric.contrib.files import *

from cloudbio.flavor import Flavor

from cloudbio.custom.shared import (_fetch_and_unpack)

class BioTestFlavor(Flavor):
    """A Flavor for cross Bio* tests
    """
    def __init__(self, env):
        Flavor.__init__(self,env)
        self.name = "Bio* cross-lang flavor"

    def rewrite_config_items(self, name, items):
        if name == "packages":
            # list.remove('screen')
            # list.append('test')
            return items
        elif name == "python":
            return [ 'biopython' ]
        elif name == "perl":
            return [ 'bioperl' ]
        elif name == "ruby":
            return [ 'bio' ]
        elif name == "custom":
            return []
        else:
            return items

    def post_install(self):
        env.logger.info("Starting post-install")
        env.logger.info("Load Scalability tests")
        if exists('Scalability'):
            with cd('Scalability'):
               run('git pull')
        else:
           _fetch_and_unpack("git clone git://github.com/pjotrp/Scalability.git")
        # Now run a post installation routine (for the heck of it)
        run('./Scalability/scripts/hello.sh')

        env.logger.info("Load Cross-language tests")
        if exists('Cross-language-interfacing'):
            with cd('Cross-language-interfacing'):
               run('git pull')
        else:
           _fetch_and_unpack("git clone git://github.com/pjotrp/Cross-language-interfacing.git")
        # Special installs for the tests
        with cd('Cross-language-interfacing'):
            sudo('./scripts/install-packages-root.sh ')
            run('./scripts/install-packages.sh')
            run('./scripts/create_test_files.rb')


env.flavor = BioTestFlavor(env)
