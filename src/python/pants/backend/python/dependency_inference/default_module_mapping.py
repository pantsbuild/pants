# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: The project names must follow the naming scheme at
#  https://www.python.org/dev/peps/pep-0503/#normalized-names.

import re
from typing import Match
from functools import partial


def all_hyphen_to_dot(m: Match) -> str:
    return m.string.replace("-", ".")


def first_group_hyphen_to_underscore(m: Match) -> str:
    return m.groups()[0].replace("-", "_")


# TODO: combine the following two functions by passing in the replacements?
def first_group_hyphen_to_dot_second_hyphen_to_underscore(m: Match) -> str:
    """
    take two groups, the first will have '-' replaced with '.',
    the second will have '-' replaced with '_'
    e.g. opentelemetry-instrumentation-aio-pika ->
         group1(opentelemtetry.instrumentation.)group2(aio_pika)
    """
    prefix = m.string[m.start(1) : m.end(1)].replace("-", ".")
    suffix = m.string[m.start(2) : m.end(2)].replace("-", "_")
    return f"{prefix}{suffix}"


def two_groups_hyphen_dot_concat_with_suffix(m: Match, custom_suffix: str = "") -> str:
    """
    take two groups, the first will have '-' replaced with '.',
    the second will have '-' replaced with ''
    e.g. google-cloud-foo-bar -> group1(google.cloud.)group2(foobar)
    """
    prefix = m.string[m.start(1) : m.end(1)].replace("-", ".")
    suffix = m.string[m.start(2) : m.end(2)].replace("-", "")
    return f"{prefix}{suffix}{custom_suffix}"


"""
A mapping of Patterns and their replacements. will be used with `sub` e.g.
```python
pattern="^google-cloud-(.*)"
replacement="google.cloud.\\g<1>" # just one '\' for realbies

then if an import in the python code is google.cloud.foo, then the package of
google-cloud-foo will be used.

The match is either a string or a function that takes a re.Match and returns
the replacement. see re.sub for more information
```
"""
DEFAULT_MODULE_PATTERN_MAPPING = {
    re.compile(r"""^(google-cloud-)([^.]+)"""): [
        two_groups_hyphen_dot_concat_with_suffix,
        partial(two_groups_hyphen_dot_concat_with_suffix, custom_suffix="_v1"),
        partial(two_groups_hyphen_dot_concat_with_suffix, custom_suffix="_v2"),
        partial(two_groups_hyphen_dot_concat_with_suffix, custom_suffix="_v3"),
    ],
    re.compile(r"""^azure-.+"""): [all_hyphen_to_dot],
    re.compile(r"""^django-((.+(-.+)?))"""): [first_group_hyphen_to_underscore],
    re.compile(r"""^(opentelemetry-instrumentation-)([^.]+)"""): [
        first_group_hyphen_to_dot_second_hyphen_to_underscore,
    ],
    re.compile(r"""^(oslo-.*)"""): [first_group_hyphen_to_underscore],
    re.compile(r"""^python-(.*)"""): [first_group_hyphen_to_underscore],
}

DEFAULT_MODULE_MAPPING = {
    "absl-py": ("absl",),
    "acryl-datahub": ("datahub",),
    "ansicolors": ("colors",),
    "apache-airflow": ("airflow",),
    "atlassian-python-api": ("atlassian",),
    "attrs": ("attr", "attrs"),
    "beautifulsoup4": ("bs4",),
    "bitvector": ("BitVector",),
    "cattrs": ("cattr",),
    # explicit for django, as these don't follow the patterns
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
    # See https://github.com/googleapis/google-cloud-python#libraries for all Google cloud
    # libraries. We only add libraries in GA, not beta.
    "graphql-core": ("graphql",),
    "grpcio": ("grpc",),
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
    # exception: kafka-python -> kafka instead of kafka_python
    "opentelemetry-instrumentation-kafka-python": ("opentelemetry.instrumentation.kafka",),
    # exporters
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
    "pywinrm": ("winrm",),
    "randomwords": ("random_words",),
    "scikit-image": ("skimage",),
    "scikit-learn": ("sklearn",),
    "scikit-video": ("skvideo",),
    "sseclient-py": ("sseclient",),
    "setuptools": ("easy_install", "pkg_resources", "setuptools"),
    "snowflake-connector-python": ("snowflake.connector",),
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
