# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: The project names must follow the naming scheme at
#  https://www.python.org/dev/peps/pep-0503/#normalized-names.
DEFAULT_MODULE_MAPPING = {
    "absl-py": ("absl",),
    "ansicolors": ("colors",),
    "apache-airflow": ("airflow",),
    "attrs": ("attr",),
    # Azure
    "azure-common": ("azure.common",),
    "azure-core": ("azure.core",),
    "azure-graphrbac": ("azure.graphrbac",),
    "azure-identity": ("azure.identity",),
    "azure-keyvault-certificates": ("azure.keyvault.certificates",),
    "azure-keyvault-keys": ("azure.keyvault.keys",),
    "azure-keyvault-secrets": ("azure.keyvault.secrets",),
    "azure-keyvault": ("azure.keyvault",),
    "azure-mgmt-apimanagement": ("azure.mgmt.apimanagement",),
    "azure-mgmt-authorization": ("azure.mgmt.authorization",),
    "azure-mgmt-automation": ("azure.mgmt.automation",),
    "azure-mgmt-batch": ("azure.mgmt.batch",),
    "azure-mgmt-compute": ("azure.mgmt.compute",),
    "azure-mgmt-containerinstance": ("azure.mgmt.containerinstance",),
    "azure-mgmt-containerregistry": ("azure.mgmt.containerregistry",),
    "azure-mgmt-containerservice": ("azure.mgmt.containerservice",),
    "azure-mgmt-core": ("azure.mgmt.core",),
    "azure-mgmt-cosmosdb": ("azure.mgmt.cosmosdb",),
    "azure-mgmt-frontdoor": ("azure.mgmt.frontdoor",),
    "azure-mgmt-hybridkubernetes": ("azure.mgmt.hybridkubernetes",),
    "azure-mgmt-keyvault": ("azure.mgmt.keyvault",),
    "azure-mgmt-logic": ("azure.mgmt.logic",),
    "azure-mgmt-managementgroups": ("azure.mgmt.managementgroups",),
    "azure-mgmt-monitor": ("azure.mgmt.monitor",),
    "azure-mgmt-msi": ("azure.mgmt.msi",),
    "azure-mgmt-network": ("azure.mgmt.network",),
    "azure-mgmt-rdbms": ("azure.mgmt.rdbms",),
    "azure-mgmt-resource": ("azure.mgmt.resource",),
    "azure-mgmt-security": ("azure.mgmt.security",),
    "azure-mgmt-servicefabric": ("azure.mgmt.servicefabric",),
    "azure-mgmt-sql": ("azure.mgmt.sql",),
    "azure-mgmt-storage": ("azure.mgmt.storage",),
    "azure-mgmt-subscription": ("azure.mgmt.subscription",),
    "azure-mgmt-web": ("azure.mgmt.web",),
    "azure-storage-blob": ("azure.storage.blob",),
    "azure-storage-queue": ("azure.storage.queue",),
    "beautifulsoup4": ("bs4",),
    "bitvector": ("BitVector",),
    "cattrs": ("cattr",),
    "django-cors-headers": ("corsheaders",),
    "django-debug-toolbar": ("debug_toolbar",),
    "django-dotenv": ("dotenv",),
    "django-filter": ("django_filters",),
    "django-safedelete": ("safedelete",),
    "django-simple-history": ("simple_history",),
    "djangorestframework": ("rest_framework",),
    "django-csp": ("csp",),
    "enum34": ("enum",),
    "factory-boy": ("factory",),
    "fluent-logger": ("fluent",),
    "gitpython": ("git",),
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
    "google-cloud-logging": ("google.cloud.logging_v2", "google.cloud.logging"),
    "google-cloud-pubsub": ("google.cloud.pubsub_v1", "google.cloud.pubsub"),
    "google-cloud-secret-manager": ("google.cloud.secretmanager",),
    "google-cloud-storage": ("google.cloud.storage",),
    "grpcio": ("grpc",),
    "ipython": ("IPython",),
    "jack-client": ("jack",),
    "kafka-python": ("kafka",),
    "lark-parser": ("lark",),
    "opencv-python": ("cv2",),
    # opentelemetry
    "opentelemetry-api": ("opentelemetry",),
    "opentelemetry-exporter-otlp-proto-grpc": ("opentelemetry.exporter.otlp.proto.grpc",),
    "opentelemetry-exporter-otlp-proto-http": ("opentelemetry.exporter.otlp.proto.http",),
    "opentelemetry-instrumentation-aiohttp-client": (
        "opentelemetry.instrumentation.aiohttp_client",
    ),
    "opentelemetry-instrumentation-grpc": ("opentelemetry.instrumentation.grpc",),
    "opentelemetry-instrumentation-pymongo": ("opentelemetry.instrumentation.pymongo",),
    "opentelemetry-instrumentation-requests": ("opentelemetry.instrumentation.requests",),
    "opentelemetry-instrumentation-botocore": ("opentelemetry.instrumentation.botocore",),
    "opentelemetry-instrumentation-django": ("opentelemetry.instrumentation.django",),
    "opentelemetry-instrumentation-httpx": ("opentelemetry.instrumentation.httpx",),
    "opentelemetry-instrumentation-elasticsearch": ("opentelemetry.instrumentation.elasticsearch",),
    "opentelemetry-instrumentation-psycopg2": ("opentelemetry.instrumentation.psycopg2",),
    "opentelemetry-instrumentation-jinja2": ("opentelemetry.instrumentation.jinja2",),
    "opentelemetry-sdk": ("opentelemetry.sdk",),
    "opentelemetry-test-utils": ("opentelemetry.test",),
    "paho-mqtt": ("paho",),
    "pillow": ("PIL",),
    "pip-tools": ("piptools",),
    "progressbar2": ("progressbar",),
    "protobuf": ("google.protobuf",),
    "psycopg2-binary": ("psycopg2",),
    "pycrypto": ("Crypto",),
    "pyhamcrest": ("hamcrest",),
    "pygithub": ("github",),
    "pygobject": ("gi",),
    "pyjwt": ("jwt",),
    "pyopenssl": ("OpenSSL",),
    "pypdf2": ("PyPDF2",),
    "pypi-kenlm": ("kenlm",),
    "pytest": ("pytest", "_pytest"),
    "python-dateutil": ("dateutil",),
    "python-docx": ("docx",),
    "python-dotenv": ("dotenv",),
    "python-hcl2": ("hcl2",),
    "python-jose": ("jose",),
    "python-levenshtein": ("Levenshtein",),
    "python-lsp-jsonrpc": ("pylsp_jsonrpc",),
    "python-magic": ("magic",),
    "python-pptx": ("pptx",),
    "python-socketio": ("socketio",),
    "pyyaml": ("yaml",),
    "pymongo": ("bson", "gridfs", "pymongo"),
    "pymupdf": ("fitz",),
    "pytest-runner": ("ptr",),
    "scikit-image": ("skimage",),
    "scikit-learn": ("sklearn",),
    "setuptools": ("easy_install", "pkg_resources", "setuptools"),
    "streamlit-aggrid": ("st_aggrid",),
    "opensearch-py": ("opensearchpy",),
}

DEFAULT_TYPE_STUB_MODULE_MAPPING = {
    "djangorestframework-types": ("rest_framework",),
    "lark-stubs": ("lark",),
    "types-enum34": ("enum34",),
    "types-pillow": ("PIL",),
    "types-protobuf": ("google.protobuf",),
    "types-pycrypto": ("Crypto",),
    "types-pyopenssl": ("OpenSSL",),
    "types-pyyaml": ("yaml",),
    "types-python-dateutil": ("dateutil",),
    "types-setuptools": ("easy_install", "pkg_resources", "setuptools"),
}
