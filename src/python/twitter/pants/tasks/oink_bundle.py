import os

from collections import defaultdict

from twitter.common.dirutil import safe_mkdir

from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.fs.archive import TGZ
from twitter.pants.targets.oink_query import OinkQuery

from .jvm_binary_task import  JvmBinaryTask

from . import Task


class OinkBundleCreate(JvmBinaryTask):
  """Produces a deployable tar.gz bundle for an Oink Query.

  This is invoked as a bundle goal against OinkQuery Target.

  Example usage::

    ./pants goal bundle /path/to/oink_query_target
  """

  @staticmethod
  def is_oink_query(target):
    return isinstance(target, OinkQuery)

  def __init__(self, context):
    super(OinkBundleCreate, self).__init__(context)
    self.outdir = context.config.getdefault('outdir')
    self.context.products.require('jars', predicate=lambda t: t.is_java)
    self.context.products.require('jar_dependencies', predicate=self.is_oink_query)

  def execute(self, targets):
    all_jars = []
    def _visitor(target):
      jar_products = self.context.products.get('jars').get(target)
      if jar_products is not None:
        all_jars.append(jar_products)

    for oink_query in filter(self.is_oink_query, targets):
      oink_query.walk(_visitor, lambda t: t.is_java)

      dependencies_with_excludes = defaultdict(list)
      # list_jar_dependencies below expects a JvmBinary but we can safely pass an OinkQuery
      # since it has the deploy_excludes property and walk method list_jar_dependencies expects
      for basedir, externaljar in self.list_jar_dependencies(oink_query):
        dependencies_with_excludes[basedir].append(externaljar)
      all_jars.append(dependencies_with_excludes)

      self.context.log.debug("all jar dependencies: %s" % all_jars)

      flattened_jar_paths = []
      for product_mapping in all_jars:
        for basedir, jars in product_mapping.iteritems():
          flattened_jar_paths.extend(os.path.join(basedir, jar) for jar in jars)

      bundledir = os.path.join(self.outdir, '%s-bundle' % oink_query.name)
      libs_bundle_dir = os.path.join(bundledir, 'libs')

      safe_mkdir(bundledir, clean=True)

      safe_mkdir(libs_bundle_dir)
      for path in flattened_jar_paths:
        os.symlink(path, os.path.join(libs_bundle_dir, os.path.basename(path)))

      os.symlink('%s/src/main/pig' % get_buildroot(), os.path.join(bundledir, 'pig'))
      os.symlink('%s/src/main/ruby/gems' % get_buildroot(), os.path.join(bundledir, 'gems'))
      os.symlink('%s/src/main/ruby/oink' % get_buildroot(), os.path.join(bundledir, 'oink'))
      os.symlink('%s/src/scripts/oink_bundle/oink_bundle_runner.sh' % get_buildroot(),
                 os.path.join(bundledir, 'oink_bundle_runner.sh'))

      for source in oink_query.sources:
        os.symlink(os.path.join(get_buildroot(), oink_query.target_base, source),
                   os.path.join(bundledir, source))

      tarpath = TGZ.create(bundledir, self.outdir, oink_query.name)
      self.context.log.info('created %s' % os.path.relpath(tarpath, get_buildroot()))
