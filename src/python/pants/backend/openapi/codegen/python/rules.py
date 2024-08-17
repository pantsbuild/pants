from pants.backend.openapi.util_rules import generator_process, pom_parser
from pants.backend.openapi.codegen.python import extra_fields, generate


def rules():
    return [
        *generate.rules(),
        *extra_fields.rules(),
        *generator_process.rules(),
        *pom_parser.rules(),
    ]
