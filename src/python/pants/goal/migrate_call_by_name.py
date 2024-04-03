# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
import fileinput
import importlib.util
import json
import logging
import tokenize
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePath
from typing import TypedDict

from pants.base.build_environment import get_buildroot
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.fs import Paths
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.init.engine_initializer import GraphSession
from pants.option.option_types import BoolOption
from pants.option.options import Options
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class MigrateCallByNameBuiltinGoal(BuiltinGoal):
    name = "migrate-call-by-name"
    help = softwrap("Migrate from `Get` syntax to call-by-name syntax. See #19730.")

    should_dump_json = BoolOption(
        flag_name="--json", help=softwrap("Dump the migration plan as JSON"), default=False
    )

    def run(
        self,
        *,
        build_config: BuildConfiguration,
        graph_session: GraphSession,
        options: Options,
        specs: Specs,
        union_membership: UnionMembership,
    ) -> ExitCode:
        # Emit all `@rules` which use non-union Gets.
        plan = self._create_migration_plan(graph_session, PurePath(get_buildroot()))
        if self.should_dump_json:
            print(json.dumps(plan, indent=2, sort_keys=True))

        path_globs = specs.includes.to_specs_paths_path_globs()
        if not path_globs.globs:
            return PANTS_SUCCEEDED_EXIT_CODE

        plan_files = {item["filepath"] for item in plan}

        paths: list[Paths] = graph_session.scheduler_session.product_request(Paths, [path_globs])
        requested_files = set(paths[0].files)

        files_to_migrate = requested_files.intersection(plan_files)
        if not files_to_migrate:
            logger.info(
                f"None of the {len(requested_files)} requested files are part of the {len(plan_files)} files in the migration plan"
            )
            return PANTS_SUCCEEDED_EXIT_CODE

        syntax_mapper = CallByNameSyntaxMapper(plan)
        for f in sorted(files_to_migrate):
            file = Path(f)
            if replacements := self._create_replacements_for_file(file, syntax_mapper):
                self._perform_replacements_on_file(file, replacements)

        return PANTS_SUCCEEDED_EXIT_CODE

    def _create_migration_plan(
        self, session: GraphSession, build_root: PurePath
    ) -> list[RuleGraphGet]:
        items: list[RuleGraphGet] = []
        for rule, deps in session.scheduler_session.rule_graph_rule_gets().items():
            if isinstance(rule, partial):
                continue

            assert (spec := importlib.util.find_spec(rule.__module__)) is not None
            assert spec.origin is not None
            spec_origin = PurePath(spec.origin)

            item: RuleGraphGet = {
                "filepath": str(spec_origin.relative_to(build_root)),
                "module": rule.__module__,
                "function": rule.__name__,
                "gets": [],
            }
            unsorted_deps: list[RuleGraphGetDep] = []

            for output_type, input_types, rule_dep in deps:
                if isinstance(rule_dep, partial):
                    continue

                unsorted_deps.append(
                    {
                        "input_types": sorted(
                            [
                                {
                                    "module": input_type.__module__,
                                    "name": input_type.__name__,
                                }
                                for input_type in input_types
                            ],
                            key=lambda x: (x["module"], x["name"]),
                        ),
                        "output_type": {
                            "module": output_type.__module__,
                            "name": output_type.__name__,
                        },
                        "rule_dep": {
                            "function": rule_dep.__name__,
                            "module": rule_dep.__module__,
                        },
                    }
                )

            # Sort the dependencies by the rule_dep, and then by the input_types.
            sorted_deps = sorted(
                unsorted_deps, key=lambda x: (x["rule_dep"]["module"], x["rule_dep"]["function"])
            )
            item["gets"] = sorted_deps
            items.append(item)

        return sorted(items, key=lambda x: (x["filepath"], x["function"]))

    def _create_replacements_for_file(
        self, file: Path, syntax_mapper: CallByNameSyntaxMapper
    ) -> list[Replacement]:
        visitor = CallByNameVisitor(file, syntax_mapper)
        with open(file, "rb") as f:
            logging.info(f"Processing {file}")
            try:
                tree = ast.parse(f.read(), filename=file, type_comments=True)
                visitor.visit(tree)
            except SyntaxError as e:
                logging.error(f"SyntaxError in {file}: {e}")
            except tokenize.TokenError as e:
                logging.error(f"TokenError in {file}: {e}")

        for replacement in visitor.replacements:
            replacement.sanitize(visitor.names)

        return [r for r in visitor.replacements if not r.contains_comments()]

    def _perform_replacements_on_file(self, file: Path, replacements: list[Replacement]):
        """In-place replacements for the new source code in a file."""

        imports_added = False
        import_strings: set[str] = set()
        for replacement in replacements:
            import_strings.update(ast.unparse(i) for i in replacement.sanitized_imports())

        with fileinput.input(file, inplace=True) as f:
            for line in f:
                line_number = f.lineno()

                modified = False
                for replacement in replacements:
                    if line_number == replacement.line_range[0]:
                        # On the first line of the range, emit the new source code where the old code started
                        line_end = ",\n" if replacement.is_argument else "\n"
                        print(line[: replacement.col_range[0]], end="")
                        print(ast.unparse(replacement.new_source), end=line_end)
                        modified = True
                    elif line_number in range(
                        replacement.line_range[0], replacement.line_range[1] + 1
                    ):
                        # If there are other lines in the range, just skip them
                        modified = True
                        continue

                # For any lines that were not involved with replacements, emit them verbatim
                if not modified:
                    print(line, end="")

                # Add the below "pants.engine.rules"
                # Note: Intentionally not trying to add to the existing "pants.engine.rules" import, as merging and unparsing would wipe out comments (if any)
                # Instead, add a new import and let the formatters sort it out
                if not imports_added and line.startswith("from pants.engine.rules"):
                    print("\n".join(sorted(import_strings)))
                    imports_added = True


class RuleGraphGet(TypedDict):
    filepath: str
    function: str
    module: str
    gets: list[RuleGraphGetDep]


class RuleGraphGetDep(TypedDict):
    input_types: list[RuleType]
    output_type: RuleType
    rule_dep: RuleFunction


class RuleType(TypedDict):
    module: str
    name: str


class RuleFunction(TypedDict):
    function: str
    module: str


@dataclass
class Replacement:
    filename: PurePath
    module: str
    line_range: tuple[int, int]
    col_range: tuple[int, int]
    current_source: ast.Call
    new_source: ast.Call
    additional_imports: list[ast.ImportFrom]
    is_argument: bool = False

    def sanitized_imports(self) -> list[ast.ImportFrom]:
        """Remove any circular or self-imports."""
        return [i for i in self.additional_imports if i.module != self.module]

    def sanitize(self, names: set[str]):
        """Remove any shadowing of names, except if the new_func is in the current file."""
        assert isinstance(self.new_source.func, ast.Name)
        func_name = self.new_source.func.id
        if func_name not in names:
            return

        # If the new function is not in the sanitized imports, it must be in the current file
        if not any(i.names[0].name == func_name for i in self.sanitized_imports()):
            return

        bound_name = f"{func_name}_get"
        self.new_source.func.id = bound_name
        for i in self.additional_imports:
            if i.names[0].name == func_name:
                i.names[0].asname = bound_name
        logging.warning(f"Renamed {func_name} to {bound_name} to avoid shadowing")

    def contains_comments(self) -> bool:
        """Check if there are any comments within the replacement range.

        Opens a file for reading
        """
        with open(self.filename) as f:
            lines = f.readlines()

        for line_number in range(self.line_range[0], self.line_range[1] + 1):
            if "#" in lines[line_number - 1]:
                logger.warning(
                    f"Comments found in {self.filename} within replacement range: {self.line_range}"
                )
                return True
        return False


class CallByNameSyntaxMapper:
    def __init__(self, graphs: list[RuleGraphGet]) -> None:
        self.graphs = graphs

    def map_get_to_new_syntax(
        self, get: ast.Call, filename: PurePath, calling_func: str
    ) -> Replacement | None:
        """There are 4 forms the old Get() syntax can take, so we can account for each one of them
        individually."""
        new_source: ast.Call | None = None
        imports: list[ast.ImportFrom] = []

        graph_item = next(
            (
                item
                for item in self.graphs
                if item["filepath"] == str(filename) and item["function"] == calling_func
            ),
            None,
        )
        if not graph_item:
            logger.warning(f"Failed to find dependencies for {filename} {calling_func}")
            return None

        get_deps = graph_item["gets"]

        try:
            if len(get.args) == 1:
                new_source, imports = self.map_no_args_get_to_new_syntax(get, get_deps)
            elif len(get.args) == 2 and isinstance(get.args[1], ast.Call):
                new_source, imports = self.map_short_form_get_to_new_syntax(get, get_deps)
            elif len(get.args) == 2 and isinstance(get.args[1], ast.Dict):
                new_source, imports = self.map_dict_form_get_to_new_syntax(get, get_deps)
            elif len(get.args) == 3:
                new_source, imports = self.map_long_form_get_to_new_syntax(get, get_deps)
            else:
                logging.warning(f"Failed to migrate {ast.unparse(get)} due to unknown form\n")
                return None
        except AssertionError as e:
            logging.warning(f"Failed to migrate {ast.unparse(get)} with assertion error {e}\n")
            return None
        except Exception as e:
            logging.warning(f"Failed to migrate {ast.unparse(get)} with {e}\n")
            return None

        assert get.end_lineno is not None
        assert get.end_col_offset is not None
        return Replacement(
            filename=filename,
            module=graph_item["module"],
            line_range=(get.lineno, get.end_lineno),
            col_range=(get.col_offset, get.end_col_offset),
            current_source=get,
            new_source=new_source,
            additional_imports=[
                ast.ImportFrom(
                    module="pants.engine.rules", names=[ast.alias("implicitly")], level=0
                ),
                *imports,
            ],
        )

    def map_no_args_get_to_new_syntax(
        self, get: ast.Call, deps: list[RuleGraphGetDep]
    ) -> tuple[ast.Call, list[ast.ImportFrom]]:
        """Get(<OutputType>) -> the_rule_to_call(**implicitly())"""

        logger.debug(ast.dump(get, indent=2))
        assert len(get.args) == 1, f"Expected 1 arg, got {len(get.args)}"
        assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"

        dep = next(
            dep
            for dep in deps
            if dep["output_type"]["name"] == output_type.id and not dep["input_types"]
        )
        module = dep["rule_dep"]["module"]
        new_function = dep["rule_dep"]["function"]

        new_call = ast.Call(
            func=ast.Name(id=new_function),
            args=[],
            keywords=[
                ast.keyword(value=ast.Call(func=ast.Name(id="implicitly"), args=[], keywords=[]))
            ],
        )
        imports = [ast.ImportFrom(module, names=[ast.alias(new_function)], level=0)]
        return new_call, imports

    def map_long_form_get_to_new_syntax(
        self, get: ast.Call, deps: list[RuleGraphGetDep]
    ) -> tuple[ast.Call, list[ast.ImportFrom]]:
        """Get(<OutputType>, <InputType>, input) -> the_rule_to_call(**implicitly(input))"""

        logger.debug(ast.dump(get, indent=2))
        assert len(get.args) == 3, f"Expected 3 arg, got {len(get.args)}"
        assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
        assert isinstance(input_type := get.args[1], ast.Name), f"Expected Name, got {get.args[1]}"

        dep = next(
            dep
            for dep in deps
            if dep["output_type"]["name"] == output_type.id
            and len(dep["input_types"]) == 1
            and dep["input_types"][0]["name"] == input_type.id
        )
        module = dep["rule_dep"]["module"]
        new_function = dep["rule_dep"]["function"]

        new_call = ast.Call(
            func=ast.Name(id=new_function),
            args=[],
            keywords=[
                ast.keyword(
                    value=ast.Call(
                        func=ast.Name(id="implicitly"),
                        args=[ast.Dict(keys=[get.args[2]], values=[ast.Name(id=input_type.id)])],
                        keywords=[],
                    )
                )
            ],
        )
        imports = [ast.ImportFrom(module, names=[ast.alias(new_function)], level=0)]
        return new_call, imports

    def map_short_form_get_to_new_syntax(
        self, get: ast.Call, deps: list[RuleGraphGetDep]
    ) -> tuple[ast.Call, list[ast.ImportFrom]]:
        """Get(<OutputType>, <InputType>(<constructor args for input>)) ->
        the_rule_to_call(**implicitly(input))"""

        logger.debug(ast.dump(get, indent=2))
        assert len(get.args) == 2, f"Expected 2 arg, got {len(get.args)}"
        assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
        assert isinstance(input_call := get.args[1], ast.Call), f"Expected Call, got {get.args[1]}"
        assert isinstance(
            input_type := input_call.func, ast.Name
        ), f"Expected Name, got {input_call.func}"

        dep = next(
            dep
            for dep in deps
            if dep["output_type"]["name"] == output_type.id
            and len(dep["input_types"]) == 1
            and dep["input_types"][0]["name"] == input_type.id
        )
        module = dep["rule_dep"]["module"]
        new_function = dep["rule_dep"]["function"]

        new_call = ast.Call(
            func=ast.Name(id=new_function),
            args=[],
            keywords=[
                ast.keyword(
                    value=ast.Call(func=ast.Name(id="implicitly"), args=[input_call], keywords=[])
                )
            ],
        )
        imports = [ast.ImportFrom(module, names=[ast.alias(new_function)], level=0)]
        return new_call, imports

    def map_dict_form_get_to_new_syntax(
        self, get: ast.Call, deps: list[RuleGraphGetDep]
    ) -> tuple[ast.Call, list[ast.ImportFrom]]:
        """Get(<OutputType>, {input1: <Input1Type>, ..inputN: <InputNType>}) ->
        the_rule_to_call(**implicitly(input))"""

        logger.debug(ast.dump(get, indent=2))
        assert len(get.args) == 2, f"Expected 2 arg, got {len(get.args)}"
        assert isinstance(output_type := get.args[0], ast.Name), f"Expected Name, got {get.args[0]}"
        assert isinstance(input_dict := get.args[1], ast.Dict), f"Expected Dict, got {get.args[1]}"

        input_types = {k.id for k in input_dict.values if isinstance(k, ast.Name)}

        dep = next(
            dep
            for dep in deps
            if dep["output_type"]["name"] == output_type.id
            and {i["name"] for i in dep["input_types"]} == input_types
        )

        module = dep["rule_dep"]["module"]
        new_function = dep["rule_dep"]["function"]

        new_call = ast.Call(
            func=ast.Name(id=new_function),
            args=[],
            keywords=[
                ast.keyword(
                    value=ast.Call(func=ast.Name(id="implicitly"), args=[input_dict], keywords=[])
                )
            ],
        )
        imports = [ast.ImportFrom(module, names=[ast.alias(new_function)], level=0)]
        return new_call, imports


class CallByNameVisitor(ast.NodeVisitor):
    def __init__(self, filename: PurePath, syntax_mapper: CallByNameSyntaxMapper) -> None:
        super().__init__()

        self.filename = filename
        self.syntax_mapper = syntax_mapper
        self.names: set[str] = set()
        self.replacements: list[Replacement] = []

    def visit_Name(self, node: ast.Name):
        """Collect all names in the file, so we can avoid shadowing them with the new imports."""
        self.names.add(node.id)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Replace the Get() calls with a call-by-name equivalent syntax in @rule decorated async
        functions.

        The replacement code comes from the Rust rule graph implementation, and for the purpose of this script,
        it's assumed to be a lookup table as an array of items hashed against the function name of interest.

        In each file we do a replacement, we should add an import to the top of the file to reference the call-by-name'd function.
        We should also add an import to "implicitly", as we'll likely use it in the call-by-name'd function params.
        """

        # Ensure we collect all names in this function, as well
        names = [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]
        self.names.update(names)

        if not self._should_visit_node(node.decorator_list):
            return

        # In the body, look for `await Get`, and replace it with a call-by-name equivalent
        for child in node.body:
            if call := self._maybe_replaceable_call(child):
                if replacement := self.syntax_mapper.map_get_to_new_syntax(
                    call, self.filename, calling_func=node.name
                ):
                    self.replacements.append(replacement)

            for call in self._maybe_replaceable_multiget(child):
                if replacement := self.syntax_mapper.map_get_to_new_syntax(
                    call, self.filename, calling_func=node.name
                ):
                    replacement.is_argument = True
                    self.replacements.append(replacement)

    def _should_visit_node(self, decorator_list: list[ast.expr]) -> bool:
        """Only interested in async functions with the @rule(...) decorator."""
        for decorator in decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id in ["rule", "goal_rule"]:
                # Accounts for "@rule"
                return True
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id in ["rule", "goal_rule"]
            ):
                # Accounts for "@rule(desc=..., level=...)"
                return True
        return False

    def _maybe_replaceable_call(self, statement: ast.stmt) -> ast.Call | None:
        """There is one forms of Get that we want to replace (all in await'able functions):

        - bar_get = Get(...)
        - bar = await Get(...)
        """
        if (
            isinstance(statement, ast.Assign)
            and (
                isinstance((call_node := statement.value), ast.Call)
                or (
                    isinstance((await_node := statement.value), ast.Await)
                    and isinstance((call_node := await_node.value), ast.Call)
                )
            )
            and isinstance(call_node.func, ast.Name)
            and call_node.func.id == "Get"
        ):
            return call_node
        return None

    def _maybe_replaceable_multiget(self, statement: ast.stmt) -> list[ast.Call]:
        """There is one forms of Get that we want to replace (all in await'able functions):

        - multigot = await MultiGet(Get(...), Get(...), ...)
        """
        if (
            isinstance(statement, ast.Assign)
            and isinstance((await_node := statement.value), ast.Await)
            and isinstance((call_node := await_node.value), ast.Call)
            and isinstance(call_node.func, ast.Name)
            and call_node.func.id == "MultiGet"
        ):
            return [
                arg
                for arg in call_node.args
                if isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Name)
                and arg.func.id == "Get"
            ]
        return []
