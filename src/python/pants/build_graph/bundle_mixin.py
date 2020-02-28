# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.app_base import AppBase
from pants.fs import archive
from pants.task.task import TaskBase
from pants.util.dirutil import absolute_symlink, safe_mkdir, safe_mkdir_for
from pants.util.fileutil import atomic_copy


class BundleMixin(TaskBase):
    @classmethod
    def register_options(cls, register):
        """Register options common to all bundle tasks."""
        super().register_options(register)
        register(
            "--archive",
            choices=list(archive.TYPE_NAMES),
            fingerprint=True,
            help="Create an archive of this type from the bundle. "
            "This option is also defined in app target. "
            "Precedence is CLI option > target option > pants.toml option.",
        )
        # `target.id` ensures global uniqueness, this flag is provided primarily for
        # backward compatibility.
        register(
            "--use-basename-prefix",
            advanced=True,
            type=bool,
            help="Use target basename to prefix bundle folder or archive; otherwise a unique "
            "identifier derived from target will be used.",
        )

    @staticmethod
    def get_bundle_dir(name, results_dir):
        return os.path.join(results_dir, "{}-bundle".format(name))

    # TODO (Benjy): The following CLI > target > config logic
    # should be implemented in the options system.
    # https://github.com/pantsbuild/pants/issues/3538
    @staticmethod
    def resolved_option(options, target, key):
        """Get value for option "key".

        Resolution precedence is CLI option > target option > pants.toml option.

        :param options: Options returned by `task.get_option()`
        :param target: Target
        :param key: Key to get using the resolution precedence
        """
        option_value = options.get(key)
        if not isinstance(target, AppBase) or options.is_flagged(key):
            return option_value
        v = target.payload.get_field_value(key, None)
        return option_value if v is None else v

    def symlink_bundles(self, app, bundle_dir):
        """For each bundle in the given app, symlinks relevant matched paths.

        Validates that at least one path was matched by a bundle.
        """
        for bundle_counter, bundle in enumerate(app.bundles):
            count = 0
            for path, relpath in bundle.filemap.items():
                bundle_path = os.path.join(bundle_dir, relpath)
                count += 1
                if os.path.exists(bundle_path):
                    continue

                if os.path.isfile(path):
                    safe_mkdir(os.path.dirname(bundle_path))
                    os.symlink(path, bundle_path)
                elif os.path.isdir(path):
                    safe_mkdir(bundle_path)

            if count == 0:
                raise TargetDefinitionException(
                    app.target,
                    'Bundle index {} of "bundles" field '
                    "does not match any files.".format(bundle_counter),
                )

    def publish_results(
        self, dist_dir, use_basename_prefix, vt, bundle_dir, archivepath, id, archive_ext
    ):
        """Publish a copy of the bundle and archive from the results dir in dist."""
        # TODO (from mateor) move distdir management somewhere more general purpose.
        name = vt.target.basename if use_basename_prefix else id
        bundle_copy = os.path.join(dist_dir, "{}-bundle".format(name))
        absolute_symlink(bundle_dir, bundle_copy)
        self.context.log.info(
            "created bundle copy {}".format(os.path.relpath(bundle_copy, get_buildroot()))
        )

        if archivepath:
            ext = archive.archive_extensions.get(archive_ext, archive_ext)
            archive_copy = os.path.join(dist_dir, "{}.{}".format(name, ext))
            safe_mkdir_for(archive_copy)  # Ensure parent dir exists
            atomic_copy(archivepath, archive_copy)
            self.context.log.info(
                "created archive copy {}".format(os.path.relpath(archive_copy, get_buildroot()))
            )
