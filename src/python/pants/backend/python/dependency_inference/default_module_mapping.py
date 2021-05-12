# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: You must use lowercase and replace all `-` with `_` for the requirement's name.
DEFAULT_MODULE_MAPPING = {
    "ansicolors": ("colors",),
    "apache_airflow": ("airflow",),
    "attrs": ("attr",),
    "beautifulsoup4": ("bs4",),
    "djangorestframework": ("rest_framework",),
    "enum34": ("enum",),
    "paho_mqtt": ("paho",),
    "protobuf": ("google.protobuf",),
    "pycrypto": ("Crypto",),
    "pyopenssl": ("OpenSSL",),
    "python_dateutil": ("dateutil",),
    "python_jose": ("jose",),
    "pyyaml": ("yaml",),
    "pymongo": ("bson", "gridfs"),
    "pytest_runner": ("ptr",),
    "setuptools": ("easy_install", "pkg_resources"),
}
