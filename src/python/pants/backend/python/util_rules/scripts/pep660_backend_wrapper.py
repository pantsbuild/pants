# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import base64
import errno
import hashlib
import importlib
import json
import os
import shutil
import sys
import zipfile

_WHEEL_TEMPLATE = """\
Wheel-Version: 1.0
Generator: pantsbuild.pants
Root-Is-Purelib: true
Tag: {}
Build: 0.editable
"""


def import_build_backend(build_backend):
    module_path, _, object_path = build_backend.partition(":")
    backend_module = importlib.import_module(module_path)
    return getattr(backend_module, object_path) if object_path else backend_module


def mkdir(directory):
    """Python 2.7 doesn't have the exist_ok arg on os.makedirs()."""
    try:
        os.makedirs(directory)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def prepare_dist_info(backend, build_dir, wheel_config_settings):
    """Use PEP 660 or PEP 517 backend methods to create .dist-info directory.

    PEP 660 defines `prepare_metadata_for_build_editable`. If PEP 660 is not supported, we fall back
    to PEP 517's `prepare_metadata_for_build_wheel`. PEP 517, however, says that method is optional.
    So finally we fall back to using `build_wheel` and then extract the dist-info directory and then
    delete the extra wheel file (like one of PEP 517's examples).
    """
    prepare_metadata = getattr(
        backend,
        "prepare_metadata_for_build_editable",  # PEP 660
        getattr(backend, "prepare_metadata_for_build_wheel", None),  # PEP 517
    )
    if prepare_metadata is not None:
        print("prepare_metadata: " + str(prepare_metadata))
        metadata_path = prepare_metadata(build_dir, wheel_config_settings)
    else:
        # Optional PEP 517 method not defined. Use build_wheel instead.
        wheel_path = backend.build_wheel(build_dir, wheel_config_settings)
        with zipfile.ZipFile(os.path.join(build_dir, wheel_path), "r") as whl:
            dist_info_files = [n for n in whl.namelist() if ".dist-info/" in n]
            whl.extractall(build_dir, dist_info_files)
            metadata_path = os.path.dirname(dist_info_files[0])
    return standardize_dist_info_path(build_dir, metadata_path)


def standardize_dist_info_path(build_dir, metadata_path):
    """Make sure dist-info dir is named pkg-version.dist-info.

    Returns the package name, version, and update metadata_path
    """
    pkg_version = metadata_path.replace(".dist-info", "")
    if "-" in pkg_version:
        pkg, version = pkg_version.split("-")
    else:
        # The wrapped backend does not conform to the latest specs.
        pkg = pkg_version
        version = ""
        with open(os.path.join(build_dir, metadata_path, "METADATA")) as f:
            lines = f.readlines()
        for line in lines:
            if line.startswith("Version: "):
                version = line[len("Version: ") :].strip()
                break
        # Standardize the name of the dist-info directory per Binary distribution format spec.
        old_metadata_path = metadata_path
        metadata_path = pkg + "-" + version + ".dist-info"
        shutil.move(
            os.path.join(build_dir, old_metadata_path), os.path.join(build_dir, metadata_path)
        )
    return pkg, version, metadata_path


def remove_record_files(build_dir, metadata_path):
    """Any RECORD* file will be incorrect since we are creating the wheel."""
    for file in os.listdir(os.path.join(build_dir, metadata_path)):
        if file == "RECORD" or file.startswith("RECORD."):
            os.unlink(os.path.join(build_dir, metadata_path, file))


def write_wheel_file(tags, build_dir, metadata_path):
    metadata_wheel_file = os.path.join(build_dir, metadata_path, "WHEEL")
    if not os.path.exists(metadata_wheel_file):
        with open(metadata_wheel_file, "w") as f:
            f.write(_WHEEL_TEMPLATE.format(tags))


def write_direct_url_file(direct_url, build_dir, metadata_path):
    """Create a direct_url.json file for later use during wheel install.

    We abuse PEX to get the PEP 660 editable wheels into the virtualenv, and then use pip to
    actually install the wheel. But PEX and pip do not know that this is an editable install. We
    cannot add direct_url.json directly to the wheel because that must be added by the wheel
    installer. So we will rename this file to 'direct_url.json' after pip has installed everything
    else.
    """
    direct_url_contents = {"url": direct_url, "dir_info": {"editable": True}}
    direct_url_file = os.path.join(build_dir, metadata_path, "direct_url__pants__.json")
    with open(direct_url_file, "w") as f:
        json.dump(direct_url_contents, f)


def build_editable_wheel(pkg, build_dir, metadata_path, dist_dir, wheel_path, pth_file_path):
    """Build the editable wheel, including .pth and RECORD files."""

    _record = []

    def record(file_path, file_arcname):
        """Calculate an entry for the RECORD file (required by the wheel spec)."""
        with open(file_path, "rb") as f:
            file_digest = hashlib.sha256(f.read()).digest()
        file_hash = "sha256=" + base64.urlsafe_b64encode(file_digest).decode().rstrip("=")
        file_size = str(os.stat(file_path).st_size)
        _record.append(",".join([file_arcname, file_hash, file_size]))

    with zipfile.ZipFile(os.path.join(dist_dir, wheel_path), "w") as whl:
        pth_file_arcname = pkg + "__pants__.pth"
        record(pth_file_path, pth_file_arcname)
        whl.write(pth_file_path, pth_file_arcname)

        # The following for loop is loosely based on:
        # wheel.wheelfile.WheelFile.write_files (by @argonholm MIT license)
        for root, dirnames, filenames in os.walk(os.path.join(build_dir, metadata_path)):
            dirnames.sort()
            for name in sorted(filenames):
                path = os.path.normpath(os.path.join(root, name))
                if os.path.isfile(path):
                    arcname = os.path.relpath(path, build_dir).replace(os.path.sep, "/")
                    record(path, arcname)
                    whl.write(path, arcname)

        record_path = os.path.join(metadata_path, "RECORD")
        _record.append(record_path + ",,")
        _record.append("")  # "" to add newline at eof
        whl.writestr(record_path, os.linesep.join(_record))


def main(build_backend, dist_dir, pth_file_path, wheel_config_settings, tags, direct_url):
    backend = import_build_backend(build_backend)

    build_dir = "build"
    mkdir(dist_dir)
    mkdir(build_dir)

    pkg, version, metadata_path = prepare_dist_info(backend, build_dir, wheel_config_settings)
    remove_record_files(build_dir, metadata_path)
    write_wheel_file(tags, build_dir, metadata_path)
    write_direct_url_file(direct_url, build_dir, metadata_path)

    wheel_path = "{}-{}-0.editable-{}.whl".format(pkg, version, tags)
    build_editable_wheel(pkg, build_dir, metadata_path, dist_dir, wheel_path, pth_file_path)
    print("editable_path: {editable_path}".format(editable_path=wheel_path))


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        settings = json.load(f)

    main(**settings)
