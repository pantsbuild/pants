# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from hashlib import sha1

from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.jvm.tasks.jar_import_products import JarImportProducts
from pants.base.fingerprint_strategy import DefaultFingerprintHashingMixin, FingerprintStrategy
from pants.fs.archive import ZIP
from pants.task.unpack_remote_sources_base import UnpackRemoteSourcesBase
from pants.util.objects import SubclassesOf


class UnpackJarsFingerprintStrategy(DefaultFingerprintHashingMixin, FingerprintStrategy):
    def compute_fingerprint(self, target):
        """UnpackedJars targets need to be re-unpacked if any of its configuration changes or any of
        the jars they import have changed."""
        if isinstance(target, UnpackedJars):
            hasher = sha1()
            for cache_key in sorted(jar.cache_key() for jar in target.all_imported_jar_deps):
                hasher.update(cache_key.encode())
            hasher.update(target.payload.fingerprint().encode())
            return hasher.hexdigest()
        return None


class UnpackJars(UnpackRemoteSourcesBase):
    """Unpack artifacts specified by unpacked_jars() targets.

    Adds an entry to SourceRoot for the contents.

    :API: public
    """

    source_target_constraint = SubclassesOf(UnpackedJars)

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data(JarImportProducts)

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("UnpackJars", 0)]

    def get_fingerprint_strategy(self):
        return UnpackJarsFingerprintStrategy()

    def unpack_target(self, unpacked_jars, unpack_dir):
        direct_coords = {jar.coordinate for jar in unpacked_jars.all_imported_jar_deps}
        unpack_filter = self.get_unpack_filter(unpacked_jars)
        jar_import_products = self.context.products.get_data(JarImportProducts)

        for coordinate, jar_path in jar_import_products.imports(unpacked_jars):
            if not unpacked_jars.payload.intransitive or coordinate in direct_coords:
                self.context.log.info(
                    "Unpacking jar {coordinate} from {jar_path} to {unpack_dir}.".format(
                        coordinate=coordinate, jar_path=jar_path, unpack_dir=unpack_dir
                    )
                )
                ZIP.extract(jar_path, unpack_dir, filter_func=unpack_filter)
