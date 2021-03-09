# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

DEFAULT_MODULE_MAPPING = {
    'attrs': (
        'attr',
    ),
    'enum34': (
        'enum',
    ),
    'paho_mqtt': (
        'paho',
    ),
    'pyopenssl': (
        'OpenSSL',
    ),
    'pycrypto': (
        'Crypto',
    ),
    'pymongo': (
        'bson',
        'gridfs',
    ),
    'pytest_runner': (
        'ptr',
    ),
    'python_dateutil': (
        'dateutil',
    ),
    'setuptools': (
        'easy_install',
        'pkg_resources',
    ),
}
