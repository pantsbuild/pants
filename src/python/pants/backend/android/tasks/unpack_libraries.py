# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from hashlib import sha1

from pants.backend.android.targets.android_library import AndroidLibrary
from pants.backend.android.targets.android_resources import AndroidResources
from pants.backend.core.tasks.task import Task
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.fs.archive import ZIP


class AndroidLibraryFingerprintStrategy(DefaultFingerprintStrategy):

  def compute_fingerprint(self, target):
    """AndroidLibrary targets need to be re-unpacked if any of the imported jars have changed."""
    # TODO(mateor) Create a utility function to add a block of fingerprints to a hasher with caller
    # handing in list of items of the same type and a function to extract a fingerprint from each.
    if isinstance(target, AndroidLibrary):
      hasher = sha1()
      for jar_import in sorted(target.imported_jars, key=lambda t: t.id):
        hasher.update(jar_import.cache_key())
      hasher.update(target.payload.fingerprint())
      return hasher.hexdigest()
    return None

class UnpackLibraries(Task):
  """Unpack AndroidDependency artifacts, including .jar and .aar libraries."""

  class MissingElementException(Exception):
    """Raised if an unpacked file or directory unexpectedly does not exist."""

  class UnexpectedArchiveType(Exception):
    """Raised if an archive has an extension that is not explicitly handled by this class."""

  @classmethod
  def prepare(cls, options, round_manager):
    super(UnpackLibraries, cls).prepare(options, round_manager)
    round_manager.require_data('ivy_imports')

  @classmethod
  def product_types(cls):
    return ['unpacked_libraries']

  @staticmethod
  def is_library(target):
    """Return True for AndroidLibrary targets."""
    # TODO(mateor) add AndroidBinary support. If include/exclude patterns aren't needed, an
    #  android_binary should be able to simply declare an android_dependency as a dep.
    return isinstance(target, AndroidLibrary)

  def __init__(self, *args, **kwargs):
    super(UnpackLibraries, self).__init__(*args, **kwargs)
    self._created_targets = {}
    self._unpacked_archives = set()

  def create_classes_jar_target(self, target, archive, jar_file):
    """Create a JarLibrary target containing the jar_file as a JarDependency.

    :param AndroidLibrary target: The new JarLibrary will be derived from this AndroidLibrary .
    :param string archive: Archive name as fetched by ivy, e.g. 'org.pantsbuild.example-1.0.aar'.
    :param string jar_file: Full path of the classes.jar contained within unpacked aar files.
    :return: A new Target.
    :rtype: JarLibrary
    """
    # TODO(mateor) add another JarDependency for every jar under 'libs'.

    # Try to parse revision number. This is just to satisfy the spec, the rev is part of 'archive'.
    archive_version = os.path.splitext(archive)[0].rpartition('-')[-1]
    jar_url = 'file://{0}'.format(jar_file)
    jar_dep = JarDependency(org=target.id, name=archive, rev=archive_version, url=jar_url)
    address = SyntheticAddress(self.workdir, '{}-classes.jar'.format(archive))
    new_target = self.context.add_new_target(address, JarLibrary, jars=[jar_dep],
                                             derived_from=target)
    return new_target


  def create_resource_target(self, target, archive, manifest, resource_dir):
    """Create an AndroidResources target.

    :param AndroidLibrary target: AndroidLibrary that the new AndroidResources target derives from.
    :param string archive: Archive name as fetched by ivy, e.g. 'org.pantsbuild.example-1.0.aar'.
    :param string resource_dir: Full path of the res directory contained within aar files.
    :return: A new Target.
    :rtype: AndroidResources
    """

    address = SyntheticAddress(self.workdir, '{}-resources'.format(archive))
    new_target = self.context.add_new_target(address, AndroidResources,
                                             manifest=manifest, resource_dir=resource_dir,
                                             derived_from=target)
    return new_target

  def create_android_library_target(self, target, archive, unpacked_aar_location):
    """Create an AndroidLibrary target.

    The aar files are unpacked and the contents used to create a new AndroidLibrary target.
    :param AndroidLibrary target: AndroidLibrary that the new AndroidLibrary target derives from.
    :param string archive: An archive name as fetched by ivy, e.g. 'org.pantsbuild.example-1.0.aar'.
    :param string unpacked_aar_location: Full path of dir holding contents of an unpacked aar file.
    :return: A new Target.
    :rtype: AndroidLibrary
    """
    # The following three elements of an aar file have names mandated by the aar spec:
    #   http://tools.android.com/tech-docs/new-build-system/aar-format
    # They are said to be mandatory although in practice that assumption only holds for manifest.
    manifest = os.path.join(unpacked_aar_location, 'AndroidManifest.xml')
    jar_file = os.path.join(unpacked_aar_location, 'classes.jar')
    resource_dir = os.path.join(unpacked_aar_location, 'res')

    # Sanity check to make sure all .aar files we expect to be unpacked are actually unpacked.
    if not os.path.isfile(manifest):
      raise self.MissingElementException("An AndroidManifest.xml is expected in every unpacked "
                                         ".aar file but none was found in the {} archive "
                                         "for the {} target".format(archive, target))

    # Depending on the contents of the unpacked aar file, create the dependencies.
    deps = []
    if os.path.isdir(resource_dir):
      deps.append(self.create_resource_target(target, archive, manifest, resource_dir))
    if os.path.isfile(jar_file):
      deps.append(self.create_classes_jar_target(target, archive, jar_file))

    address = SyntheticAddress(self.workdir, '{}-android_library'.format(archive))
    new_target = self.context.add_new_target(address, AndroidLibrary,
                                             manifest=manifest,
                                             include_patterns=target.include_patterns,
                                             exclude_patterns=target.exclude_patterns,
                                             dependencies=deps,
                                             derived_from=target)
    return new_target

  def _unpack_artifacts(self, imports):
    # Unpack the aar and jar library artifacts. If the aar files have a jar in the contents,
    # unpack that jar as well.
    for archive_path in imports:
      for archive in imports[archive_path]:
        jar_outdir = self.unpacked_jar_location(archive)
        if archive.endswith('.jar'):
          jar_file = os.path.join(archive_path, archive)
        elif archive.endswith('.aar'):
          unpacked_aar_destination = self.unpacked_aar_location(archive)
          jar_file = os.path.join(unpacked_aar_destination, 'classes.jar')

          # Unpack .aar files.
          if archive not in self._unpacked_archives:
            ZIP.extract(os.path.join(archive_path, archive), unpacked_aar_destination)
            self._unpacked_archives.update([archive])

            # Create an .aar/classes.jar signature for self._unpacked_archives.
            archive = os.path.join(archive, 'classes.jar')
        else:
          raise self.UnexpectedArchiveType('Android dependencies can be .aar or .jar '
                                           'archives (was: {})'.format(archive))
        # Unpack the jar files.
        if archive not in self._unpacked_archives and os.path.isfile(jar_file):
          ZIP.extract(jar_file, jar_outdir)
          self._unpacked_archives.update([archive])

  def _create_target(self, target, imports):
    # Create a target for the components of an unpacked .aar file.
    for archives in imports.values():
      for archive in archives:

        # The contents of the unpacked aar file must be made into an AndroidLibrary target.
        if archive.endswith('.aar'):
          if archive not in self._created_targets:
            unpacked_location = self.unpacked_aar_location(archive)
            if not os.path.isdir(unpacked_location):
              raise self.MissingElementException('{}: Expected to unpack {} at {} but did not!'
                                                 .format(target, archive, unpacked_location))
            new_target = self.create_android_library_target(target, archive, unpacked_location)
            self._created_targets[archive] = new_target
          target.inject_dependency(self._created_targets[archive].address)

        # The unpacked_libraries product is a dir containing the full unpacked source. The files
        # that match the include/exclude patterns are calculated during DxCompile.
        unpacked_products = self.context.products.get('unpacked_libraries')
        unpacked_products.add(target, get_buildroot()).append(self.unpacked_jar_location(archive))

  def execute(self):
    ivy_imports = self.context.products.get('ivy_imports')
    library_targets = self.context.targets(predicate=self.is_library)

    targets_to_unpack = []
    with self.invalidated(library_targets,
                          fingerprint_strategy=AndroidLibraryFingerprintStrategy(),
                          invalidate_dependents=True) as invalidation_check:
      if invalidation_check.invalid_vts:
        targets_to_unpack.extend([vt.target for vt in invalidation_check.invalid_vts])
        for target in targets_to_unpack:
          imports = ivy_imports.get(target)
          if imports:
            self._unpack_artifacts(imports)

    # Create the new targets from the contents of unpacked aar files.
    for target in library_targets:
      imports = ivy_imports.get(target)
      if imports:
        self._create_target(target, imports)

  def unpacked_jar_location(self, archive):
    """Location for unpacked jar files, whether imported as-is or found inside an aar file."""
    return os.path.join(self.workdir, 'explode-jars', archive)

  def unpacked_aar_location(self, archive):
    """Output location for unpacking .aar archives."""
    return os.path.join(self.workdir, archive)
