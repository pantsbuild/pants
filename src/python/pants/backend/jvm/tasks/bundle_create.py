# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Any

from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.bundle_mixin import BundleMixin
from pants.build_graph.target_scopes import Scopes
from pants.fs import archive
from pants.util.dirutil import safe_mkdir
from pants.util.ordered_set import OrderedSet


class BundleCreate(BundleMixin, JvmBinaryTask):
    """
    :API: public
    """

    # Directory for both internal and external libraries.
    LIBS_DIR = "libs"
    _target_closure_kwargs = dict(
        include_scopes=Scopes.JVM_RUNTIME_SCOPES, respect_intransitive=True
    )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--deployjar",
            advanced=True,
            type=bool,
            fingerprint=True,
            help="Pack all 3rdparty and internal jar classfiles into a single deployjar in "
            "the bundle's root dir. If unset, all jars will go into the bundle's libs "
            "directory, the root will only contain a synthetic jar with its manifest's "
            "Class-Path set to those jars. This option is also defined in jvm_app target. "
            "Precedence is CLI option > target option > pants.toml option.",
        )

    @classmethod
    def implementation_version(cls):
        return super().implementation_version() + [("BundleCreate", 1)]

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data("consolidated_classpath")

    @classmethod
    def product_types(cls):
        return ["jvm_archives", "jvm_bundles", "deployable_archives"]

    @dataclass(frozen=True)
    class App:
        """A uniform interface to an app."""

        address: Any
        binary: Any
        bundles: Any
        id: Any
        deployjar: Any
        archive: Any
        target: Any

        @staticmethod
        def is_app(target):
            return isinstance(target, (JvmApp, JvmBinary))

        @classmethod
        def create_app(cls, target, deployjar, archive):
            return cls(
                target.address,
                target if isinstance(target, JvmBinary) else target.binary,
                [] if isinstance(target, JvmBinary) else target.payload.bundles,
                target.id,
                deployjar,
                archive,
                target,
            )

    @property
    def cache_target_dirs(self):
        return True

    def _add_product(self, deployable_archive, app, path):
        deployable_archive.add(app.target, os.path.dirname(path)).append(os.path.basename(path))
        self.context.log.debug(f"created {os.path.relpath(path, get_buildroot())}")

    def execute(self):
        targets_to_bundle = self.context.targets(self.App.is_app)

        if self.get_options().use_basename_prefix:
            self.check_basename_conflicts(
                [t for t in self.context.target_roots if t in targets_to_bundle]
            )

        with self.invalidated(targets_to_bundle, invalidate_dependents=True) as invalidation_check:
            jvm_bundles_product = self.context.products.get("jvm_bundles")
            bundle_archive_product = self.context.products.get("deployable_archives")
            jvm_archive_product = self.context.products.get("jvm_archives")

            for vt in invalidation_check.all_vts:
                app = self.App.create_app(
                    vt.target,
                    self.resolved_option(self.get_options(), vt.target, "deployjar"),
                    self.resolved_option(self.get_options(), vt.target, "archive"),
                )
                archiver = archive.create_archiver(app.archive) if app.archive else None

                bundle_dir = self.get_bundle_dir(app.id, vt.results_dir)
                ext = archive.archive_extensions.get(app.archive, app.archive)
                filename = f"{app.id}.{ext}"
                archive_path = os.path.join(vt.results_dir, filename) if app.archive else ""
                if not vt.valid:
                    self.bundle(app, vt.results_dir)
                    if app.archive:
                        archiver.create(bundle_dir, vt.results_dir, app.id)

                self._add_product(jvm_bundles_product, app, bundle_dir)
                if archiver:
                    self._add_product(bundle_archive_product, app, archive_path)
                    self._add_product(jvm_archive_product, app, archive_path)

                # For root targets, create symlink.
                if vt.target in self.context.target_roots:
                    self.publish_results(
                        self.get_options().pants_distdir,
                        self.get_options().use_basename_prefix,
                        vt,
                        bundle_dir,
                        archive_path,
                        app.id,
                        app.archive,
                    )

    class BasenameConflictError(TaskError):
        """Indicates the same basename is used by two targets."""

    def bundle(self, app, results_dir):
        """Create a self-contained application bundle.

        The bundle will contain the target classes, dependencies and resources.
        """
        assert isinstance(app, BundleCreate.App)

        bundle_dir = self.get_bundle_dir(app.id, results_dir)
        self.context.log.debug(f"creating {os.path.relpath(bundle_dir, get_buildroot())}")

        safe_mkdir(bundle_dir, clean=True)

        classpath = OrderedSet()

        # Create symlinks for both internal and external dependencies under `lib_dir`. This is
        # only needed when not creating a deployjar
        lib_dir = os.path.join(bundle_dir, self.LIBS_DIR)
        if not app.deployjar:
            os.mkdir(lib_dir)
            consolidated_classpath = self.context.products.get_data("consolidated_classpath")
            classpath.update(
                ClasspathProducts.create_canonical_classpath(
                    consolidated_classpath,
                    app.target.closure(bfs=True, **self._target_closure_kwargs),
                    lib_dir,
                    internal_classpath_only=False,
                    excludes=app.binary.deploy_excludes,
                )
            )

        bundle_jar = os.path.join(bundle_dir, f"{app.binary.basename}.jar")
        with self.monolithic_jar(app.binary, bundle_jar, manifest_classpath=classpath) as jar:
            self.add_main_manifest_entry(jar, app.binary)

            # Make classpath complete by adding the monolithic jar.
            classpath.update([jar.path])

        if app.binary.shading_rules:
            for jar_path in classpath:
                # In case `jar_path` is a symlink, this is still safe, shaded jar will overwrite jar_path,
                # original file `jar_path` linked to remains untouched.
                # TODO run in parallel to speed up
                self.shade_jar(shading_rules=app.binary.shading_rules, jar_path=jar_path)

        self.symlink_bundles(app, bundle_dir)

        return bundle_dir

    def check_basename_conflicts(self, targets):
        """Apps' basenames are used as bundle directory names.

        Ensure they are all unique.
        """

        basename_seen = {}
        for target in targets:
            if target.basename in basename_seen:
                raise self.BasenameConflictError(
                    "Basename must be unique, found two targets use "
                    "the same basename: {}'\n\t{} and \n\t{}".format(
                        target.basename,
                        basename_seen[target.basename].address.spec,
                        target.address.spec,
                    )
                )
            basename_seen[target.basename] = target
