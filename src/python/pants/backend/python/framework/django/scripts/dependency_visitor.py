# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: An easy way to debug this is to invoke it directly on a file.
#   E.g.
#   $ python src/python/pants/backend/python/framework/django/scripts/dependency_visitor.py FILE


import ast
import json
import sys


class DjangoDependencyVisitor(ast.NodeVisitor):
    def __init__(self):
        self.info = set()

    @staticmethod
    def maybe_str(node):
        if sys.version_info[0:2] < (3, 8):
            return node.s if isinstance(node, ast.Str) else None
        else:
            return node.value if isinstance(node, ast.Constant) else None

    def visit_ClassDef(self, node):
        # Detect `class Migration(migrations.Migration):`
        if (
            node.name == "Migration"
            and len(node.bases) > 0
            and node.bases[0].value.id == "migrations"
            and node.bases[0].attr == "Migration"
        ):
            # Detect `dependencies = [("app1", "migration1"), ("app2", "migration2")]`
            for child in node.body:
                if (
                    isinstance(child, ast.Assign)
                    and len(child.targets) == 1
                    and child.targets[0].id == "dependencies"
                    and isinstance(child.value, (ast.Tuple, ast.List))
                ):
                    for elt in child.value.elts:
                        if isinstance(elt, (ast.Tuple, ast.List)) and len(elt.elts) == 2:
                            app = self.maybe_str(elt.elts[0])
                            migration = self.maybe_str(elt.elts[1])
                            if app is not None and migration is not None:
                                self.info.add((app, migration))

        self.generic_visit(node)


def main(filename):
    with open(filename, "rb") as f:
        content = f.read()
    try:
        tree = ast.parse(content, filename=filename)
    except SyntaxError:
        return

    visitor = DjangoDependencyVisitor()
    visitor.visit(tree)
    # We have to be careful to set the encoding explicitly and write raw bytes ourselves.
    buffer = sys.stdout if sys.version_info[0:2] == (2, 7) else sys.stdout.buffer
    buffer.write(json.dumps(sorted(visitor.info)).encode("utf8"))


if __name__ == "__main__":
    main(sys.argv[1])
