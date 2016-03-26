# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from hashlib import sha1

from pants.backend.jvm.jar_dependency_utils import M2Coordinate
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.jar_import_products import JarImportProducts
from pants.base.build_environment import get_buildroot
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.build_graph.address import Address
from pants.fs.archive import ZIP
from pants.task.task import Task

from pants.contrib.android.targets.android_binary import AndroidBinary
from pants.contrib.android.targets.android_library import AndroidLibrary
from pants.contrib.android.targets.android_resources import AndroidResources


class AndroidLibraryFingerprintStrategy(DefaultFingerprintStrategy):

  def compute_fingerprint(self, target):
    """AndroidLibrary targets need to be re-unpacked if any of the imported jars have changed."""
    # TODO(mateor) Create a utility function to add a block of fingerprints to a hasher with caller
    # handing in list of items of the same type and a function to extract a fingerprint from each.
    if isinstance(target, AndroidLibrary):
      hasher = sha1()
      for cache_key in sorted(jar.cache_key() for jar in target.imported_jars):
        hasher.update(cache_key)
      hasher.update(target.payload.fingerprint())
      return hasher.hexdigest()
    return None


class UnpackLibraries(Task):
  """Unpack AndroidDependency artifacts, including .jar and .aar libraries.

  The UnpackLibraries task unpacks artifacts imported by AndroidLibraries, as .aar or .jar files,
  through a 'libraries' attribute. The .aar files may contain components which require creation
  of some synthetic targets, as well as a classes.jar. The classes.jar is packaged into a
  JarDependency target and sent to javac compilation. All jar files are then unpacked-
  android_binaries repack the class files of all the android_libraries in their transitive
  dependencies into a dex file.

  All archives are unpacked only once, regardless of differing include/exclude patterns or how many
  targets depend upon it. All targets that depend on a particular artifact will be passed the
  unpack_libraries product, which is a directory containing the entire source of the unpacked jars.
  These sources are filtered against the AndroidLibrary's include/exclude patterns during the
  creation of the dex file.
  """

  class MissingElementException(Exception):
    """Raised if an unpacked file or directory unexpectedly does not exist."""

  class UnexpectedArchiveType(Exception):
    """Raised if an archive has an extension that is not explicitly handled by this class."""

  @classmethod
  def prepare(cls, options, round_manager):
    super(UnpackLibraries, cls).prepare(options, round_manager)
    round_manager.require_data(JarImportProducts)

  @classmethod
  def product_types(cls):
    return ['unpacked_libraries']

  @staticmethod
  def is_binary(target):
    """Return True for AndroidBinary targets."""
    return isinstance(target, AndroidBinary)

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

  def create_classes_jar_target(self, library, coordinate, jar_file):
    """Create a JarLibrary target containing the jar_file as a JarDependency.

    :param library: The new JarLibrary will be derived from this AndroidLibrary.
    :type target: :class:`pants.contrib.android.targets.android_library.AndroidLibrary`
    :param coordinate: Archive coordinate fetched by ivy, e.g. 'org.pantsbuild:example::1.0:aar'.
    :type coordinate: :class:`pants.contrib.jvm.jar_dependency_utils.M2Coordinate`
    :param string jar_file: Full path of the classes.jar contained within unpacked aar files.
    :returns: A new jar library target.
    :rtype: :class:`pants.contrib.jvm.targets.jar_library.JarLibrary`
    """
    # TODO(mateor) add another JarDependency for every jar under 'libs'.
    jar_url = 'file://{0}'.format(jar_file)
    jar_dep = JarDependency(org=library.id, name=coordinate.artifact_filename, rev=coordinate.rev,
                            url=jar_url)
    address = Address(self.workdir, '{}-classes.jar'.format(coordinate.artifact_filename))
    new_target = self.context.add_new_target(address, JarLibrary, jars=[jar_dep],
                                             derived_from=library)
    return new_target

  def create_resource_target(self, library, coordinate, manifest, resource_dir):
    """Create an AndroidResources target.

    :param library: AndroidLibrary that the new AndroidResources target derives from.
    :type target: :class:`pants.contrib.android.targets.android_library.AndroidLibrary`
    :param coordinate: Archive coordinate fetched by ivy, e.g. 'org.pantsbuild:example::1.0:aar'.
    :type coordinate: :class:`pants.contrib.jvm.jar_dependency_utils.M2Coordinate`
    :param string manifest: The path of 'AndroidManifest.xml'
    :param string resource_dir: Full path of the res directory contained within aar files.
    :return: A new android resources target.
    :rtype::class:`pants.contrib.android.targets.AndroidResources`
    """

    address = Address(self.workdir, '{}-resources'.format(coordinate.artifact_filename))
    new_target = self.context.add_new_target(address, AndroidResources,
                                             manifest=manifest, resource_dir=resource_dir,
                                             derived_from=library)
    return new_target

  def create_android_library_target(self, binary, library, coordinate, unpacked_aar_location):
    """Create an AndroidLibrary target.

    The aar files are unpacked and the contents used to create a new AndroidLibrary target.
    :param AndroidBinary binary: AndroidBinary that depends on the AndroidLibrary being processed.
    :param AndroidLibrary library: AndroidLibrary that the new AndroidLibrary target derives from.
    :param coordinate: Archive coordinate fetched by ivy, e.g. 'org.pantsbuild:example::1.0:aar'.
    :type coordinate: :class:`pants.contrib.jvm.jar_dependency_utils.M2Coordinate`
    :param string unpacked_aar_location: Full path of dir holding contents of an unpacked aar file.
    :return: A new android library target.
    :rtype::class:`pants.contrib.android.targets.AndroidLibrary`
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
                                         "for the {} target".format(coordinate, library))

    # Depending on the contents of the unpacked aar file, create the dependencies.
    deps = []
    if os.path.isdir(resource_dir):
      new_resource_target = self.create_resource_target(library, coordinate, manifest, resource_dir)

      # # The new libraries resources must be compiled both by themselves and along with the dependent library.
      deps.append(new_resource_target)
    if os.path.isfile(jar_file):
      if jar_file not in self._created_targets:
        # TODO(mateo): So the binary needs the classes on the classpath. I should probably bundle up the include/exclude
        # filtered classes and put them on the compile classpath, either as a jar or as source.
        self._created_targets[jar_file] =  self.create_classes_jar_target(library, coordinate, jar_file)
      binary.inject_dependency(self._created_targets[jar_file].address)
    address = Address(self.workdir, '{}-android_library'.format(coordinate.artifact_filename))
    new_target = self.context.add_new_target(address, AndroidLibrary,
                                             manifest=manifest,
                                             include_patterns=library.payload.include_patterns,
                                             exclude_patterns=library.payload.exclude_patterns,
                                             dependencies=deps,
                                             derived_from=library)
    return new_target

  def _unpack_artifacts(self, jar_imports):
    # Unpack the aar and jar library artifacts. If the aar files have a jar in the contents,
    # unpack that jar as well.
    for coordinate, aar_or_jar in jar_imports:
      jar_outdir = self.unpacked_jar_location(coordinate)
      if 'jar' == coordinate.ext:
        jar_file = aar_or_jar
      elif 'aar' == coordinate.ext:
        unpacked_aar_destination = self.unpacked_aar_location(coordinate)
        jar_file = os.path.join(unpacked_aar_destination, 'classes.jar')
        # Unpack .aar files.
        if coordinate not in self._unpacked_archives:
          ZIP.extract(aar_or_jar, unpacked_aar_destination)
          self._unpacked_archives.add(aar_or_jar)

          # Create an .aar/classes.jar signature for self._unpacked_archives.
          coordinate = M2Coordinate(org=coordinate.org,
                                    name=coordinate.name,
                                    rev=coordinate.rev,
                                    classifier=coordinate.classifier,
                                    ext='classes.jar')
      else:
        raise self.UnexpectedArchiveType('Android dependencies can be .aar or .jar archives '
                                         '(was: {} at {})'.format(coordinate, aar_or_jar))
      # Unpack the jar files.
      if coordinate not in self._unpacked_archives and os.path.isfile(jar_file):
        ZIP.extract(jar_file, jar_outdir)
        self._unpacked_archives.add(aar_or_jar)

  def _create_target(self, binary, library, coordinates):
    # Create a target for the components of an unpacked .aar file.
    for coordinate in coordinates:
      # The contents of the unpacked aar file must be made into an AndroidLibrary target.
      if 'aar' == coordinate.ext:
        if coordinate not in self._created_targets:
          unpacked_location = self.unpacked_aar_location(coordinate)
          if not os.path.isdir(unpacked_location):
            raise self.MissingElementException('{}: Expected to unpack {} at {} but did not!'
                                               .format(library.address.spec, coordinate, unpacked_location))

          # The binary is being threaded through because android binaries need the classes.jar on their classpath
          # in jvm_compile.
          new_target = self.create_android_library_target(binary,
                                                          library,
                                                          coordinate,
                                                          unpacked_location)
          self._created_targets[coordinate] = new_target

        library.inject_dependency(self._created_targets[coordinate].address)
      # The unpacked_libraries product is a dir containing the full unpacked source. The files
      # that match the include/exclude patterns are calculated during DxCompile.
      unpacked_products = self.context.products.get('unpacked_libraries')
      unpacked_products.add(library, get_buildroot()).append(self.unpacked_jar_location(coordinate))

  def execute(self):
    jar_import_products = self.context.products.get_data(JarImportProducts)
    library_targets = self.context.targets(predicate=self.is_library)

    with self.invalidated(library_targets,
                          fingerprint_strategy=AndroidLibraryFingerprintStrategy(),
                          invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.invalid_vts:
        jar_imports = jar_import_products.imports(vt.target)
        if jar_imports:
          self._unpack_artifacts(jar_imports)

    # Create the new targets from the contents of unpacked aar files.
    binary_targets = self.context.targets(predicate=self.is_binary)
    for binary in binary_targets:
      library_dependencies = [x for x in binary.dependencies if isinstance(x, AndroidLibrary)]

      for library in library_dependencies:
        jar_imports = jar_import_products.imports(library)
        if jar_imports:
          self._create_target(binary, library, (jar_import.coordinate for jar_import in jar_imports))

  def unpacked_jar_location(self, coordinate):
    """Location for unpacked jar files, whether imported as-is or found inside an aar file."""
    return os.path.join(self.workdir, 'explode-jars', coordinate.artifact_filename)

  def unpacked_aar_location(self, coordinate):
    """Output location for unpacking .aar archives."""
    return os.path.join(self.workdir, coordinate.artifact_filename)
