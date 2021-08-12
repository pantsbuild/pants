# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: The project names must follow the naming scheme at
#  https://www.python.org/dev/peps/pep-0503/#normalized-names.
DEFAULT_MODULE_MAPPING = {
    "ansicolors": ("colors",),
    "apache-airflow": ("airflow",),
    "attrs": ("attr",),
    "beautifulsoup4": ("bs4",),
    "django-cors-headers": ("corsheaders",),
    "django-debug-toolbar": ("debug_toolbar",),
    "django-filter": ("django_filters",),
    "django-simple-history": ("simple_history",),
    "djangorestframework": ("rest_framework",),
    "enum34": ("enum",),
    # See https://github.com/googleapis/google-cloud-python#libraries for all Google cloud
    # libraries. We only add libraries in GA, not beta.
    "google-cloud-aiplatform": ("google.cloud.aiplatform",),
    "google-cloud-bigquery": ("google.cloud.bigquery",),
    "google-cloud-bigtable": ("google.cloud.bigtable",),
    "google-cloud-datastore": ("google.cloud.datastore",),
    "google-cloud-firestore": ("google.cloud.firestore",),
    "google-cloud-functions": ("google.cloud.functions_v1", "google.cloud.functions"),
    "google-cloud-iam": ("google.cloud.iam_credentials_v1",),
    "google-cloud-iot": ("google.cloud.iot_v1",),
    "google-cloud-pubsub": ("google.cloud.pubsub_v1", "google.cloud.pubsub"),
    "google-cloud-secret-manager": ("google.cloud.secretmanager",),
    "google-cloud-storage": ("google.cloud.storage",),
    "paho-mqtt": ("paho",),
    "pillow": ("PIL",),
    "psycopg2-binary": ("psycopg2",),
    "protobuf": ("google.protobuf",),
    "pycrypto": ("Crypto",),
    "pyopenssl": ("OpenSSL",),
    "python-dateutil": ("dateutil",),
    "python-dotenv": ("dotenv",),
    "python-jose": ("jose",),
    "pyyaml": ("yaml",),
    "pymongo": ("bson", "gridfs"),
    "pytest-runner": ("ptr",),
    "scikit-image": ("skimage",),
    "setuptools": ("easy_install", "pkg_resources", "setuptools"),
}

DEFAULT_TYPE_STUB_MODULE_MAPPING = {
    "djangorestframework-types": ("rest_framework",),
    "types-enum34": ("enum34",),
    "types-pillow": ("PIL",),
    "types-protobuf": ("google.protobuf",),
    "types-pycrypto": ("Crypto",),
    "types-pyopenssl": ("OpenSSL",),
    "types-pyyaml": ("yaml",),
    "types-python-dateutil": ("dateutil",),
    "types-setuptools": ("easy_install", "pkg_resources", "setuptools"),
}
