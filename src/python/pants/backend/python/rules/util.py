# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import io
import os
from collections import abc, defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple, cast

from pkg_resources import Requirement

from pants.backend.python.rules.targets import PythonSources
from pants.engine.fs import FilesContent
from pants.engine.target import Target
from pants.python.python_setup import PythonSetup
from pants.rules.core.strip_source_roots import SourceRootStrippedSources
from pants.rules.core.targets import ResourcesSources
from pants.source.source_root import NoSourceRootError, SourceRoots
from pants.util.strutil import ensure_text

# Convenient type alias for the pair (package name, data files in the package).
PackageDatum = Tuple[str, Tuple[str, ...]]


def parse_interpreter_constraint(constraint: str) -> Requirement:
    """Parse an interpreter constraint, e.g., CPython>=2.7,<3.

    We allow shorthand such as `>=3.7`, which gets expanded to `CPython>=3.7`. See Pex's
    interpreter.py's `parse_requirement()`.
    """
    try:
        parsed_requirement = Requirement.parse(constraint)
    except ValueError:
        parsed_requirement = Requirement.parse(f"CPython{constraint}")
    return parsed_requirement


def source_root_or_raise(source_roots: SourceRoots, path: str) -> str:
    """Find the source root for the given path, or raise if none is found."""
    source_root = source_roots.find_by_path(path)
    if not source_root:
        raise NoSourceRootError(f"Found no source root for {path}")
    return source_root.path


# Distutils does not support unicode strings in setup.py, so we must explicitly convert to binary
# strings as pants uses unicode_literals. A natural and prior technique was to use `pprint.pformat`,
# but that embeds u's in the string itself during conversion. For that reason we roll out own
# literal pretty-printer here.
#
# Note that we must still keep this code, even though Pants only runs with Python 3, because
# the created product may still be run by Python 2.
#
# For more information, see http://bugs.python.org/issue13943.
def distutils_repr(obj):
    """Compute a string repr suitable for use in generated setup.py files."""
    output = io.StringIO()
    linesep = os.linesep

    def _write(data):
        output.write(ensure_text(data))

    def _write_repr(o, indent=False, level=0):
        pad = " " * 4 * level
        if indent:
            _write(pad)
        level += 1

        if isinstance(o, (bytes, str)):
            # The py2 repr of str (unicode) is `u'...'` and we don't want the `u` prefix; likewise,
            # the py3 repr of bytes is `b'...'` and we don't want the `b` prefix so we hand-roll a
            # repr here.
            o_txt = ensure_text(o)
            if linesep in o_txt:
                _write('"""{}"""'.format(o_txt.replace('"""', r"\"\"\"")))
            else:
                _write("'{}'".format(o_txt.replace("'", r"\'")))
        elif isinstance(o, abc.Mapping):
            _write("{" + linesep)
            for k, v in o.items():
                _write_repr(k, indent=True, level=level)
                _write(": ")
                _write_repr(v, indent=False, level=level)
                _write("," + linesep)
            _write(pad + "}")
        elif isinstance(o, abc.Iterable):
            if isinstance(o, abc.MutableSequence):
                open_collection, close_collection = "[]"
            elif isinstance(o, abc.Set):
                open_collection, close_collection = "{}"
            else:
                open_collection, close_collection = "()"

            _write(open_collection + linesep)
            for i in o:
                _write_repr(i, indent=True, level=level)
                _write("," + linesep)
            _write(pad + close_collection)
        else:
            _write(repr(o))  # Numbers and bools.

    _write_repr(obj)
    return output.getvalue()


def find_packages(
    source_roots: SourceRoots,
    tgts_and_stripped_srcs: Iterable[Tuple[Target, SourceRootStrippedSources]],
    init_py_contents: FilesContent,
    py2: bool,
) -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[PackageDatum, ...]]:
    """Analyze the package structure for the given sources.

    Returns a tuple (packages, namespace_packages, package_data), suitable for use as setup()
    kwargs.
    """
    # Find all packages implied by the sources.
    packages: Set[str] = set()
    package_data: Dict[str, List[str]] = defaultdict(list)
    for tgt, stripped_srcs in tgts_and_stripped_srcs:
        if tgt.has_field(PythonSources):
            for file in stripped_srcs.snapshot.files:
                # Python 2: An __init__.py file denotes a package.
                # Python 3: Any directory containing python source files is a package.
                if not py2 or os.path.basename(file) == "__init__.py":
                    packages.add(os.path.dirname(file).replace(os.path.sep, "."))

    # Add any packages implied by ancestor __init__.py files.
    # Note that init_py_contents includes all __init__.py files, not just ancestors, but
    # that's fine - the others will already have been found in tgts_and_stripped_srcs above.
    for init_py_content in init_py_contents:
        packages.add(os.path.dirname(init_py_content.path).replace(os.path.sep, "."))

    # Now find all package_data.
    for tgt, stripped_srcs in tgts_and_stripped_srcs:
        if tgt.has_field(ResourcesSources):
            source_root = source_root_or_raise(source_roots, tgt.address.spec_path)
            resource_dir_relpath = os.path.relpath(tgt.address.spec_path, source_root)
            # Find the closest enclosing package, if any.  Resources will be loaded relative to that.
            package: str = resource_dir_relpath.replace(os.path.sep, ".")
            while package and package not in packages:
                package = package.rpartition(".")[0]
            # If resource is not in a package, ignore it. There's no principled way to load it anyway.
            if package:
                package_dir_relpath = package.replace(".", os.path.sep)
                package_data[package].extend(
                    os.path.relpath(file, package_dir_relpath)
                    for file in stripped_srcs.snapshot.files
                )

    # See which packages are pkg_resources-style namespace packages.
    # Note that implicit PEP 420 namespace packages and pkgutil-style namespace packages
    # should *not* be listed in the setup namespace_packages kwarg. That's for pkg_resources-style
    # namespace pacakges only. See https://github.com/pypa/sample-namespace-packages/.
    namespace_packages: Set[str] = set()
    init_py_by_path: Dict[str, bytes] = {ipc.path: ipc.content for ipc in init_py_contents}
    for pkg in packages:
        path = os.path.join(pkg.replace(".", os.path.sep), "__init__.py")
        if path in init_py_by_path and declares_pkg_resources_namespace_package(
            init_py_by_path[path].decode()
        ):
            namespace_packages.add(pkg)

    return (
        tuple(sorted(packages)),
        tuple(sorted(namespace_packages)),
        tuple((pkg, tuple(sorted(files))) for pkg, files in package_data.items()),
    )


def declares_pkg_resources_namespace_package(python_src: str) -> bool:
    """Given .py file contents, determine if it declares a pkg_resources-style namespace package.

    Detects pkg_resources-style namespaces. See here for details:
    https://packaging.python.org/guides/packaging-namespace-packages/.

    Note: Accepted namespace package decls are valid Python syntax in all Python versions,
    so this code can, e.g., detect namespace packages in Python 2 code while running on Python 3.
    """
    import ast

    def is_name(node: ast.AST, name: str) -> bool:
        return isinstance(node, ast.Name) and node.id == name

    def is_call_to(node: ast.AST, func_name: str) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        return (isinstance(func, ast.Attribute) and func.attr == func_name) or is_name(
            func, func_name
        )

    def has_args(call_node: ast.Call, required_arg_ids: Tuple[str, ...]) -> bool:
        args = call_node.args
        if len(args) != len(required_arg_ids):
            return False
        actual_arg_ids = tuple(arg.id for arg in args if isinstance(arg, ast.Name))
        return actual_arg_ids == required_arg_ids

    try:
        python_src_ast = ast.parse(python_src)
    except SyntaxError:
        # The namespace package incantations we check for are valid code in all Python versions.
        # So if the code isn't parseable we know it isn't a valid namespace package.
        return False

    # Note that these checks are slightly heuristic. It is possible to construct adversarial code
    # that would defeat them. But the only consequence would be an incorrect namespace_packages list
    # in setup.py, and we're assuming our users aren't trying to shoot themselves in the foot.
    for ast_node in ast.walk(python_src_ast):
        # pkg_resources-style namespace, e.g.,
        #   __import__('pkg_resources').declare_namespace(__name__).
        if is_call_to(ast_node, "declare_namespace") and has_args(
            cast(ast.Call, ast_node), ("__name__",)
        ):
            return True
    return False


def is_python2(
    compatibilities: Iterable[Optional[Iterable[str]]], python_setup: PythonSetup
) -> bool:
    """Checks if we should assume python2 code."""

    def iter_reqs():
        for compatibility in compatibilities:
            for constraint in python_setup.compatibility_or_constraints(compatibility):
                yield parse_interpreter_constraint(constraint)

    for req in iter_reqs():
        for python_27_ver in range(0, 18):  # The last python 2.7 version was 2.7.18.
            if req.specifier.contains(f"2.7.{python_27_ver}"):
                # At least one constraint limits us to Python 2, so assume that.
                return True
    return False
