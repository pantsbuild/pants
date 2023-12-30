# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: The project names must follow the naming scheme at
#  https://www.python.org/dev/peps/pep-0503/#normalized-names.

import re
from functools import partial
from typing import Dict, Iterable, Match, Tuple


def all_hyphen_to_dot(m: Match[str]) -> str:
    """Convert all hyphens to dots e.g. azure-foo-bar -> azure.foo.bar.

    >>> all_hyphen_to_dot(re.match(r"^azure-.+", "azure-foo-bar"))
    'azure.foo.bar'
    """
    return m.string.replace("-", ".")


def first_group_hyphen_to_underscore(m: Match[str]) -> str:
    """Convert the first group(regex match group) of hyphens to underscores. Only returns the first
    group and must contain at least one group.

    >>> first_group_hyphen_to_underscore(re.match(r"^django-((.+(-.+)?))", "django-admin-cursor-paginator"))
    'admin_cursor_paginator'
    """
    if m.re.groups == 0 or not m.groups():
        raise ValueError(f"expected at least one group in the pattern{m.re.pattern} but got none.")
    return str(m.groups()[0]).replace("-", "_")


def two_groups_hyphens_two_replacements_with_suffix(
    m: Match[str],
    first_group_replacement: str = ".",
    second_group_replacement: str = "",
    custom_suffix: str = "",
) -> str:
    """take two groups, and by default, the first will have '-' replaced with '.', the second will
    have '-' replaced with '' e.g. google-cloud-foo-bar -> group1(google.cloud.)group2(foobar)

    >>> two_groups_hyphens_two_replacements_with_suffix(re.match(r"^(google-cloud-)([^.]+)", "google-cloud-foo-bar"))
    'google.cloud.foobar'
    """
    if m.re.groups < 2 or not m.groups():
        raise ValueError(f"expected at least two groups in the pattern{m.re.pattern}.")
    prefix = m.string[m.start(1) : m.end(1)].replace("-", first_group_replacement)
    suffix = m.string[m.start(2) : m.end(2)].replace("-", second_group_replacement)
    return f"{prefix}{suffix}{custom_suffix}"


"""
A mapping of Patterns and their replacements. will be used with `re.sub`.
The match is either a string or a function`(str) -> str`; that takes a re.Match and returns
the replacement. see re.sub for more information

then if an import in the python code is google.cloud.foo, then the package of
google-cloud-foo will be used.
"""
DEFAULT_MODULE_PATTERN_MAPPING: Dict[re.Pattern, Iterable] = {
    re.compile(r"""^azure-.+"""): [all_hyphen_to_dot],
    re.compile(r"""^django-((.+(-.+)?))"""): [first_group_hyphen_to_underscore],
    # See https://github.com/googleapis/google-cloud-python#libraries for all Google cloud
    # libraries. We only add libraries in GA, not beta.
    re.compile(r"""^(google-cloud-)([^.]+)"""): [
        partial(two_groups_hyphens_two_replacements_with_suffix, custom_suffix=custom_suffix)
        for custom_suffix in ("", "_v1", "_v2", "_v3")
    ],
    re.compile(r"""^(opentelemetry-instrumentation-)([^.]+)"""): [
        partial(two_groups_hyphens_two_replacements_with_suffix, second_group_replacement="_"),
    ],
    re.compile(r"""^(oslo-.+)"""): [first_group_hyphen_to_underscore],
    re.compile(r"""^python-(.+)"""): [first_group_hyphen_to_underscore],
}

DEFAULT_MODULE_MAPPING: Dict[str, Tuple] = {
    "absl-py": ("absl",),
    "acryl-datahub": ("datahub",),
    "ansicolors": ("colors",),
    "apache-airflow": ("airflow",),
    "atlassian-python-api": ("atlassian",),
    "attrs": ("attr", "attrs"),
    "beautifulsoup4": ("bs4",),
    "bitvector": ("BitVector",),
    "cattrs": ("cattr", "cattrs"),
    "django-filter": ("django_filters",),
    "django-postgres-extra": ("psqlextra",),
    "django-cors-headers": ("corsheaders",),
    "djangorestframework": ("rest_framework",),
    "djangorestframework-dataclasses": ("rest_framework_dataclasses",),
    "djangorestframework-simplejwt": ("rest_framework_simplejwt",),
    "elastic-apm": ("elasticapm",),
    "enum34": ("enum",),
    "factory-boy": ("factory",),
    "fluent-logger": ("fluent",),
    "gitpython": ("git",),
    "graphql-core": ("graphql",),
    "grpcio": ("grpc",),
    "grpcio-health-checking": ("grpc_health",),
    "honeycomb-opentelemetry": ("honeycomb.opentelemetry",),
    "ipython": ("IPython",),
    "jack-client": ("jack",),
    "kafka-python": ("kafka",),
    "lark-parser": ("lark",),
    "launchdarkly-server-sdk": ("ldclient",),
    "mail-parser": ("mailparser",),
    "mysql-connector-python": ("mysql.connector",),
    "opencv-python": ("cv2",),
    "opensearch-py": ("opensearchpy",),
    # opentelemetry
    "opentelemetry-api": ("opentelemetry",),
    "opentelemetry-instrumentation-kafka-python": ("opentelemetry.instrumentation.kafka",),
    "opentelemetry-exporter-otlp": ("opentelemetry.exporter",),
    "opentelemetry-exporter-otlp-proto-grpc": ("opentelemetry.exporter.otlp.proto.grpc",),
    "opentelemetry-exporter-otlp-proto-http": ("opentelemetry.exporter.otlp.proto.http",),
    "opentelemetry-sdk": ("opentelemetry.sdk",),
    "opentelemetry-test-utils": ("opentelemetry.test",),
    "paho-mqtt": ("paho",),
    "phonenumberslite": ("phonenumbers",),
    "pillow": ("PIL",),
    "pip-tools": ("piptools",),
    "progressbar2": ("progressbar",),
    "protobuf": ("google.protobuf",),
    "psycopg2-binary": ("psycopg2",),
    "pycrypto": ("Crypto",),
    "pykube-ng": ("pykube",),
    "pyhamcrest": ("hamcrest",),
    "pygithub": ("github",),
    "pygobject": ("gi",),
    "pyjwt": ("jwt",),
    "pyopenssl": ("OpenSSL",),
    "pypdf2": ("PyPDF2",),
    "pypi-kenlm": ("kenlm",),
    "pysocks": ("socks",),
    "pytest": ("pytest", "_pytest"),
    "pyyaml": ("yaml",),
    "pymongo": ("bson", "gridfs", "pymongo"),
    "pymupdf": ("fitz",),
    "pytest-runner": ("ptr",),
    "python-json-logger": ("pythonjsonlogger",),
    "python-levenshtein": ("Levenshtein",),
    "python-lsp-jsonrpc": ("pylsp_jsonrpc",),
    "pywinrm": ("winrm",),
    "randomwords": ("random_words",),
    "scikit-image": ("skimage",),
    "scikit-learn": ("sklearn",),
    "scikit-video": ("skvideo",),
    "sseclient-py": ("sseclient",),
    "setuptools": ("easy_install", "pkg_resources", "setuptools"),
    "snowflake-connector-python": ("snowflake.connector",),
    "snowflake-snowpark-python": ("snowflake.snowpark",),
    "snowflake-sqlalchemy": ("snowflake.sqlalchemy",),
    "strawberry-graphql": ("strawberry",),
    "streamlit-aggrid": ("st_aggrid",),
    "unleashclient": ("UnleashClient",),
    "websocket-client": ("websocket",),
}

DEFAULT_TYPE_STUB_MODULE_MAPPING = {
    "djangorestframework-types": ("rest_framework",),
    "lark-stubs": ("lark",),
    "types-beautifulsoup4": ("bs4",),
    "types-enum34": ("enum34",),
    "types-pillow": ("PIL",),
    "types-protobuf": ("google.protobuf",),
    "types-pycrypto": ("Crypto",),
    "types-pyopenssl": ("OpenSSL",),
    "types-pyyaml": ("yaml",),
    "types-python-dateutil": ("dateutil",),
    "types-setuptools": ("easy_install", "pkg_resources", "setuptools"),
}

if __name__ == "__main__":
    import doctest

    doctest.testmod()
