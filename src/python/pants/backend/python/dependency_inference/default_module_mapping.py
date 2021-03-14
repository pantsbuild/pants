# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# notice: using sets here to ensure the mapping is hashable
DEFAULT_MODULE_MAPPING = {
    "ansicolors": ("colors",),
    "attrs": ("attr",),
    "beautifulsoup4": ("bs4",),
    "djangorestframework": ("rest_framework",),
    "enum34": ("enum",),
    "paho_mqtt": ("paho",),
    "protobuf": ("google.protobuf",),
    "pycrypto": ("Crypto",),
    "pyopenssl": ("OpenSSL",),
    "python-dateutil": ("dateutil",),
    "python-jose": ("jose",),
    "PyYAML": ("yaml",),
    "pymongo": (
        "bson",
        "gridfs",
    ),
    "pytest_runner": ("ptr",),
    "python_dateutil": ("dateutil",),
    "setuptools": (
        "easy_install",
        "pkg_resources",
    ),
}
