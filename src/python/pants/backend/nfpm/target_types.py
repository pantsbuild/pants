# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.nfpm.fields.all import (
    NfpmArchField,
    NfpmDependencies,
    NfpmHomepageField,
    NfpmLicenseField,
    NfpmOutputPathField,
    NfpmPackageNameField,
    NfpmPlatformField,
)
from pants.backend.nfpm.fields.apk import (
    NfpmApkDependsField,
    NfpmApkMaintainerField,
    NfpmApkProvidesField,
    NfpmApkReplacesField,
)
from pants.backend.nfpm.fields.archlinux import (
    NfpmArchlinuxConflictsField,
    NfpmArchlinuxDependsField,
    NfpmArchlinuxPackagerField,
    NfpmArchlinuxPkgbaseField,
    NfpmArchlinuxProvidesField,
    NfpmArchlinuxReplacesField,
)
from pants.backend.nfpm.fields.contents import (
    NfpmContentDirDstField,
    NfpmContentDirsField,
    NfpmContentDirsOverridesField,
    NfpmContentDstField,
    NfpmContentFileGroupField,
    NfpmContentFileModeField,
    NfpmContentFileMtimeField,
    NfpmContentFileOwnerField,
    NfpmContentFilesField,
    NfpmContentFileSourceField,
    NfpmContentFilesOverridesField,
    NfpmContentSrcField,
    NfpmContentSymlinkDstField,
    NfpmContentSymlinksField,
    NfpmContentSymlinkSrcField,
    NfpmContentSymlinksOverridesField,
    NfpmContentTypeField,
)
from pants.backend.nfpm.fields.deb import (
    NfpmDebBreaksField,
    NfpmDebCompressionField,
    NfpmDebConflictsField,
    NfpmDebDependsField,
    NfpmDebMaintainerField,
    NfpmDebPriorityField,
    NfpmDebProvidesField,
    NfpmDebRecommendsField,
    NfpmDebReplacesField,
    NfpmDebSectionField,
    NfpmDebSuggestsField,
)
from pants.backend.nfpm.fields.rpm import (
    NfpmRpmCompressionField,
    NfpmRpmConflictsField,
    NfpmRpmDependsField,
    NfpmRpmGhostContents,
    NfpmRpmGroupField,
    NfpmRpmPackagerField,
    NfpmRpmProvidesField,
    NfpmRpmRecommendsField,
    NfpmRpmReplacesField,
    NfpmRpmSuggestsField,
    NfpmRpmSummaryField,
    NfpmRpmVendorField,
)
from pants.backend.nfpm.fields.version import (
    NfpmVersionEpochField,
    NfpmVersionField,
    NfpmVersionMetadataField,
    NfpmVersionPrereleaseField,
    NfpmVersionReleaseField,
    NfpmVersionSchemaField,
)
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    InvalidTargetException,
    Target,
    TargetGenerator,
)
from pants.util.docutil import doc_url
from pants.util.strutil import help_text

# Fields required to satisfy NfpmPackageFieldSet on all NfpmPackageTarget subclasses.
COMMON_NFPM_PACKAGE_FIELDS = (
    *COMMON_TARGET_FIELDS,  # tags, description
    NfpmOutputPathField,
    NfpmDependencies,
    # NfpmPackageNameField is in the packager-specific lists of fields so that it ends up
    # in field_set.required_fields even though it is also required by NfpmPackageFieldSet.
)


class NfpmPackageTarget(Target):
    pass


APK_FIELDS = (
    NfpmPackageNameField,
    NfpmArchField,
    # version fields (apk does NOT get: version_metadata or epoch)
    NfpmVersionField,
    NfpmVersionSchemaField,
    NfpmVersionPrereleaseField,
    NfpmVersionReleaseField,
    # other package metadata fields
    NfpmHomepageField,
    NfpmLicenseField,
    NfpmApkMaintainerField,
    # package relationships
    NfpmApkReplacesField,
    NfpmApkProvidesField,
    NfpmApkDependsField,
)


class NfpmApkPackage(NfpmPackageTarget):
    alias = "nfpm_apk_package"
    core_fields = (
        *COMMON_NFPM_PACKAGE_FIELDS,
        *APK_FIELDS,
    )
    help = help_text(
        f"""
        An APK system package (Alpine Package Keeper) built by nFPM.

        This will not install the package, only create an .apk file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-apk-package')}.
        """
    )


ARCHLINUX_FIELDS = (
    NfpmPackageNameField,
    NfpmArchField,
    # version fields (archlinux does NOT get: version_metadata)
    NfpmVersionField,
    NfpmVersionSchemaField,
    NfpmVersionPrereleaseField,
    NfpmVersionReleaseField,
    NfpmVersionEpochField,
    # other package metadata fields
    NfpmHomepageField,
    NfpmLicenseField,
    NfpmArchlinuxPackagerField,
    NfpmArchlinuxPkgbaseField,
    # package relationships
    NfpmArchlinuxReplacesField,
    NfpmArchlinuxProvidesField,
    NfpmArchlinuxDependsField,
    NfpmArchlinuxConflictsField,
)


class NfpmArchlinuxPackage(NfpmPackageTarget):
    alias = "nfpm_archlinux_package"
    core_fields = (
        *COMMON_NFPM_PACKAGE_FIELDS,
        *ARCHLINUX_FIELDS,
    )
    help = help_text(
        f"""
        An Archlinux system package built by nFPM.

        This will not install the package, only create an .tar.zst file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-archlinux-package')}.
        """
    )


DEB_FIELDS = (
    NfpmPackageNameField,
    NfpmArchField,
    NfpmPlatformField,
    # version fields
    NfpmVersionField,
    NfpmVersionSchemaField,
    NfpmVersionPrereleaseField,
    NfpmVersionMetadataField,
    NfpmVersionReleaseField,
    NfpmVersionEpochField,
    # other package metadata fields
    NfpmHomepageField,
    NfpmLicenseField,  # not used by nFPM yet.
    NfpmDebMaintainerField,
    NfpmDebSectionField,
    NfpmDebPriorityField,
    # package relationships
    NfpmDebReplacesField,
    NfpmDebProvidesField,
    NfpmDebDependsField,
    NfpmDebRecommendsField,
    NfpmDebSuggestsField,
    NfpmDebConflictsField,
    NfpmDebBreaksField,
    # how to build the package
    NfpmDebCompressionField,
)


class NfpmDebPackage(NfpmPackageTarget):
    alias = "nfpm_deb_package"
    core_fields = (
        *COMMON_NFPM_PACKAGE_FIELDS,
        *DEB_FIELDS,
    )
    help = help_text(
        f"""
        A Debian system package built by nFPM.

        This will not install the package, only create a .deb file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-deb-package')}.
        """
    )


RPM_FIELDS = (
    NfpmPackageNameField,
    NfpmArchField,
    NfpmPlatformField,
    # version fields
    NfpmVersionField,
    NfpmVersionSchemaField,
    NfpmVersionPrereleaseField,
    NfpmVersionMetadataField,
    NfpmVersionReleaseField,
    NfpmVersionEpochField,
    # other package metadata fields
    NfpmHomepageField,
    NfpmLicenseField,
    NfpmRpmPackagerField,
    NfpmRpmVendorField,
    NfpmRpmGroupField,
    NfpmRpmSummaryField,
    # package relationships
    NfpmRpmReplacesField,
    NfpmRpmProvidesField,
    NfpmRpmDependsField,
    NfpmRpmRecommendsField,
    NfpmRpmSuggestsField,
    NfpmRpmConflictsField,
    # how to build the package
    NfpmRpmCompressionField,
)


class NfpmRpmPackage(NfpmPackageTarget):
    alias = "nfpm_rpm_package"
    core_fields = (
        *COMMON_NFPM_PACKAGE_FIELDS,
        *RPM_FIELDS,
        NfpmRpmGhostContents,
    )
    help = help_text(
        f"""
        An RPM system package built by nFPM.

        This will not install the package, only create an .rpm file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-rpm-package')}.
        """
    )


CONTENT_FILE_INFO_FIELDS = (
    NfpmContentFileOwnerField,
    NfpmContentFileGroupField,
    NfpmContentFileModeField,
    NfpmContentFileMtimeField,
)


class NfpmContentFile(Target):
    alias = "nfpm_content_file"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        NfpmContentFileSourceField,
        NfpmDependencies,
        NfpmContentSrcField,
        NfpmContentDstField,
        NfpmContentTypeField,
        *CONTENT_FILE_INFO_FIELDS,
    )
    help = help_text(
        lambda: f"""
        A file (of any type) that should be copied into an nFPM package.

        The file comes from either the '{NfpmContentFileSourceField.alias}' field
        or from any of the targets listed in the '{NfpmDependencies.alias}' field.
        The file may be a workspace file, a generated file, or even a package.

        The '{NfpmContentSrcField}' field determines where the file is in the sandbox.
        The '{NfpmContentDstField}' field tells nFPM where the file should be installed
        by the nFPM-generated package.
        """
    )

    def validate(self) -> None:
        if self[NfpmContentFileSourceField].value is None and not (
            self[NfpmContentSrcField].value and self[NfpmDependencies].value
        ):
            raise InvalidTargetException(
                help_text(
                    f"""
                    The '{self.alias}' target {self.address} must either
                    define a source file in the '{NfpmContentFileSourceField.alias}' field
                    or specify a path in '{NfpmContentSrcField.alias}' that is provided
                    by one of the targets in the '{NfpmDependencies.alias}' field.
                    """
                )
            )


class NfpmContentFiles(TargetGenerator):
    alias = "nfpm_content_files"
    generated_target_cls = NfpmContentFile
    core_fields = (
        *COMMON_TARGET_FIELDS,
        NfpmContentFilesField,  # TODO: if given a "sources" field, what does this look like?
        NfpmContentFilesOverridesField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        NfpmDependencies,
        NfpmContentTypeField,
        *CONTENT_FILE_INFO_FIELDS,
    )
    help = help_text(
        f"""
        Multiple files that should be copied into an nFPM package.

        Pass the list of ('{NfpmContentSrcField.alias}', '{NfpmContentDstField.alias}')
        file tuples in the '{NfpmContentFilesField.alias}' field.
        The '{NfpmContentSrcField.alias}' files must be provided by or generated by
        the targets in '{NfpmDependencies.alias}'.
        """
    )


class NfpmContentSymlink(Target):
    alias = "nfpm_content_symlink"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        # Modeled w/o dependencies for now (feel free to add later).
        NfpmContentSymlinkSrcField,  # path on package install target
        NfpmContentSymlinkDstField,  # path on package install target
        *CONTENT_FILE_INFO_FIELDS,
    )
    help = help_text(
        """
        A symlink in an nFPM package (created on package install).
        """
    )


class NfpmContentSymlinks(TargetGenerator):
    alias = "nfpm_content_symlinks"
    generated_target_cls = NfpmContentSymlink
    core_fields = (
        *COMMON_TARGET_FIELDS,
        # Modeled w/o dependencies for now (feel free to add later).
        NfpmContentSymlinksField,
        NfpmContentSymlinksOverridesField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = CONTENT_FILE_INFO_FIELDS
    help = help_text(
        f"""
        Multiple symlinks in an nFPM package (created on package install).

        Pass the list of ('{NfpmContentSymlinkSrcField.alias}', '{NfpmContentSymlinkDstField.alias}')
        symlink tuples in the '{NfpmContentSymlinksField.alias}' field.
        
        Note that '{NfpmContentSymlinkSrcField.alias}' is commonly known as the
        symlink "target" and '{NfpmContentSymlinkDstField.alias}' is the path
        to the symlink itself, also known as the symlink "name".
        """
    )


class NfpmContentDir(Target):
    alias = "nfpm_content_dir"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        # Modeled w/o dependencies for now (feel free to add later).
        NfpmContentDirDstField,  # path on package install target
        # nFPM also supports passing a real dir in "src", from which it
        # pulls the mode and mtime. But, pants creates the sandbox for nFPM,
        # so pants would have to explicitly set mode/mtime on sandboxed dirs.
        # So, the pants UX simplifies and only supports BUILD-defined values.
        *CONTENT_FILE_INFO_FIELDS,
    )
    help = help_text(
        """
        A directory in an nFPM package (created on package install).
        """
    )


class NfpmContentDirs(TargetGenerator):
    alias = "nfpm_content_dirs"
    generated_target_cls = NfpmContentDir
    core_fields = (
        *COMMON_TARGET_FIELDS,
        # Modeled w/o dependencies for now (feel free to add later).
        NfpmContentDirsField,
        NfpmContentDirsOverridesField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = CONTENT_FILE_INFO_FIELDS
    help = help_text(
        """
        Multiple directories in an nFPM package (created on package install).
        """
    )
