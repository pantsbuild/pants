# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path, PurePath
from typing import Callable, Iterable, Sequence, TypedDict

import libcst
import libcst.matchers as m
from libcst.display import dump
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
    help = softwrap(
        """
        Migrate from `Get` syntax to call-by-name syntax (#19730). This is a **destructive** operation,
        so only run this on source controlled files that you are prepared to revert if necessary.

        This goal will attempt to migrate the set of paths/targets specified at the command line
        if they are part of the "migration plan". This migration does not add any new files, but
        instead modifies existing files in-place without any formatting. The resulting changes should
        be reviewed, tested, and formatted/linted before committing.

        The migration plan is a JSON representation of the rule graph, which is generated by the
        engine based on the active backends/rules in the project.

        Each item in the migration plan is a rule that contains the old `Get` syntax, the associated
        input/output types, and the new function to directly call. The migration plan can be dumped as
        JSON using the `--json` flag, which can be useful for debugging. For example:

        {
            "filepath": "src/python/pants/source/source_root.py",
            "function": "get_source_roots",
            "gets": [{
                "input_types": [{ "module": "pants.source.source_root", "name": "SourceRootsRequest" }],
                "output_type": { "module": "pants.source.source_root", "name": "OptionalSourceRootsResult" },
                "rule_dep": { "function": "get_optional_source_roots", "module": "pants.source.source_root" }
            }],
            "module": "pants.source.source_root"
        }
        """
    )

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
        migration_plan = self._create_migration_plan(graph_session, PurePath(get_buildroot()))
        if self.should_dump_json:
            print(json.dumps(migration_plan, indent=2, sort_keys=True))

        path_globs = specs.includes.to_specs_paths_path_globs()
        if not path_globs.globs:
            return PANTS_SUCCEEDED_EXIT_CODE

        plan_files = {item["filepath"] for item in migration_plan}

        paths: list[Paths] = graph_session.scheduler_session.product_request(Paths, [path_globs])
        requested_files = set(paths[0].files)

        files_to_migrate = requested_files.intersection(plan_files)
        if not files_to_migrate:
            logger.info(
                f"None of the {len(requested_files)} requested files are part of the {len(plan_files)} files in the migration plan"
            )
            return PANTS_SUCCEEDED_EXIT_CODE

        syntax_mapper = CallByNameSyntaxMapper(migration_plan)
        for f in sorted(files_to_migrate):
            file = Path(f)
            logger.error(f"Processing {file}")

            transformer = CallByNameTransformer(file, syntax_mapper)
            with open(file) as f:
                logging.info(f"Processing {file}")
                source_code = f.read()
                tree = libcst.parse_module(source_code)
                new_tree = tree.visit(transformer)
                new_source = new_tree.code  
                logger.error(f"New source is {new_source}")
                if source_code != new_source:
                    logger.error(f"Rewriting {file}")
                    with open(file, "w") as f:
                        f.write(new_source)

        return PANTS_SUCCEEDED_EXIT_CODE

    def _create_migration_plan(
        self, session: GraphSession, build_root: PurePath
    ) -> list[RuleGraphGet]:
        """Use the rule graph to create a migration plan for each "active" file that uses the old
        Get() syntax.

        This function is mostly about creating a stable-sorted collection of items with metadata for
        downstream
        """
        items: list[RuleGraphGet] = []
        for rule, deps in session.scheduler_session.rule_graph_rule_gets().items():
            if isinstance(rule, partial):
                # Ignoring partials, see https://github.com/pantsbuild/pants/issues/20744
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
                    # Ignoring partials, see https://github.com/pantsbuild/pants/issues/20744
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

            sorted_deps = sorted(
                unsorted_deps, key=lambda x: (x["rule_dep"]["module"], x["rule_dep"]["function"])
            )
            item["gets"] = sorted_deps
            items.append(item)

        return sorted(items, key=lambda x: (x["filepath"], x["function"]))

# ------------------------------------------------------------------------------------------
# Migration Plan Typed Dicts
# ------------------------------------------------------------------------------------------

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


# ------------------------------------------------------------------------------------------
# Replacement container
# ------------------------------------------------------------------------------------------


@dataclass
class Replacement:
    filename: PurePath
    module: str
    current_source: libcst.Call
    new_source: libcst.Call
    additional_imports: list[libcst.ImportFrom]

    # def sanitized_imports(self) -> list[libcst.ImportFrom]:
    #     """Remove any circular or self-imports."""
    #     return [i for i in self.additional_imports if i.module != self.module]

    # def sanitize(self, names: set[str]):
    #     """Remove any shadowing of names, except if the new_func is in the current file."""
    #     assert isinstance(self.new_source.func, libcst.Name)
    #     func_name = self.new_source.func.id
    #     if func_name not in names:
    #         return

    #     # If the new function is not in the sanitized imports, it must be in the current file
    #     if not any(i.names[0].name == func_name for i in self.sanitized_imports()):
    #         return

    #     bound_name = f"{func_name}_get"
    #     self.new_source.func.id = bound_name
    #     for i in self.additional_imports:
    #         if i.names[0].name == func_name:
    #             i.names[0].asname = bound_name
    #     logging.warning(f"Renamed {func_name} to {bound_name} to avoid shadowing")

    def __str__(self) -> str:
        return f"""
        Replacement(
            filename={self.filename},
            module={self.module},
            current_source={dump(self.current_source)},
            new_source={dump(self.new_source)},
            additional_imports={[dump(i) for i in self.additional_imports]},
        )
        """


# ------------------------------------------------------------------------------------------
# Call-by-name syntax mapping
# ------------------------------------------------------------------------------------------

class CallByNameSyntaxMapper:
    def __init__(self, graphs: list[RuleGraphGet]) -> None:
        self.graphs = graphs

        self.mapping: dict[
            tuple[int, type[libcst.Call] | type[libcst.Dict] | None],
            Callable[[libcst.Call, list[RuleGraphGetDep]], tuple[libcst.Call, list[libcst.ImportFrom]]],
        ] = {
            (1, None): self.map_no_args_get_to_new_syntax,
            # (2, libcst.Call): self.map_short_form_get_to_new_syntax,
            # (2, libcst.Dict): self.map_dict_form_get_to_new_syntax,
            # (3, None): self.map_long_form_get_to_new_syntax,
        }

    def _get_graph_item(self, filename: PurePath, calling_func: str) -> RuleGraphGet | None:
        return next(
            (
                item
                for item in self.graphs
                if item["filepath"] == str(filename) and item["function"] == calling_func
            ),
            None,
        )

    def map_get_to_new_syntax(
        self, get: libcst.Call, filename: PurePath, calling_func: str
    ) -> Replacement | None:
        """There are 4 forms of Get() syntax. This function picks the correct one."""

        new_source: libcst.Call | None = None
        imports: list[libcst.ImportFrom] = []

        if not (graph_item := self._get_graph_item(filename, calling_func)):
            logger.warning(f"Failed to find dependencies for {filename} {calling_func}")
            return None

        get_deps = graph_item["gets"]
        num_args = len(get.args)
        arg_type: type[libcst.Call] | type[libcst.Dict] | None = None
        
        # if num_args == 2 and (arg := libcst.ensure_type(get.args[1], Union[libcst.Call, libcst.Dict])):
        #     arg_type = type(arg) if arg else None 

        try:
            new_source, imports = self.mapping[(num_args, arg_type)](get, get_deps)
        except Exception as e:
            logging.warning(f"Failed to migrate  with {e}\n")
            return None

        return Replacement(
            filename=filename,
            module=graph_item["module"],
            current_source=get,
            new_source=new_source,
            additional_imports=[
                _make_import_from("pants.engine.rules", "implicitly"),
                *imports,
            ],
        )

    def map_no_args_get_to_new_syntax(
        self, get: libcst.Call, deps: list[RuleGraphGetDep]
    ) -> tuple[libcst.Call, list[libcst.ImportFrom]]:
        """Map the no-args form of Get() to the new syntax.

        The expected mapping is roughly:
        Get(<OutputType>) -> the_rule_to_call(**implicitly())

        This form expects that the `get` call has exactly 1 arg (otherwise, a different form would be used)
        """

        logger.error(dump(get))
        output_type = libcst.ensure_type(get.args[0].value, libcst.Name).value

        dep = next(
            dep
            for dep in deps
            if dep["output_type"]["name"] == output_type and not dep["input_types"]
        )
        module = dep["rule_dep"]["module"]
        new_function = dep["rule_dep"]["function"]

        new_call = libcst.Call(
            func=libcst.Name(value=new_function),
            args=[
                libcst.Arg(
                    value=libcst.Name(value="implicitly"),
                    star="**"
                )   
            ],
        )
        imports = [_make_import_from(module, new_function)]
        return new_call, imports

    # def map_long_form_get_to_new_syntax(
    #     self, get: libcst.Call, deps: list[RuleGraphGetDep]
    # ) -> tuple[libcst.Call, list[libcst.ImportFrom]]:
    #     """Map the long form of Get() to the new syntax.

    #     The expected mapping is roughly:
    #     Get(<OutputType>, <InputType>, input) -> the_rule_to_call(**implicitly(input))

    #     This form expects that the `get` call has exactly 3 args (otherwise, a different form would be used)
    #     """

    #     logger.debug(dump(get, indent=2))
    #     output_type = narrow_type(get.args[0], libcst.Name)
    #     input_type = narrow_type(get.args[1], libcst.Name)

    #     dep = next(
    #         dep
    #         for dep in deps
    #         if dep["output_type"]["name"] == output_type.id
    #         and len(dep["input_types"]) == 1
    #         and dep["input_types"][0]["name"] == input_type.id
    #     )
    #     module = dep["rule_dep"]["module"]
    #     new_function = dep["rule_dep"]["function"]

    #     new_call = libcst.Call(
    #         func=libcst.Name(id=new_function),
    #         args=[],
    #         keywords=[
    #             libcst.keyword(
    #                 value=libcst.Call(
    #                     func=libcst.Name(id="implicitly"),
    #                     args=[libcst.Dict(keys=[get.args[2]], values=[libcst.Name(id=input_type.id)])],
    #                     keywords=[],
    #                 )
    #             )
    #         ],
    #     )
    #     imports = [libcst.ImportFrom(module, names=[libcst.alias(new_function)], level=0)]
    #     return new_call, imports

    # def map_short_form_get_to_new_syntax(
    #     self, get: libcst.Call, deps: list[RuleGraphGetDep]
    # ) -> tuple[libcst.Call, list[libcst.ImportFrom]]:
    #     """Map the short form of Get() to the new syntax.

    #     The expected mapping is roughly:
    #     Get(<OutputType>, <InputType>(<constructor args for input>)) -> the_rule_to_call(input, **implicitly())

    #     This form expects that the `get` call has exactly 2 args (otherwise, a different form would be used)
    #     """

    #     logger.debug(dump(get, indent=2))
    #     output_type = narrow_type(get.args[0], libcst.Name)
    #     input_call = narrow_type(get.args[1], libcst.Call)
    #     input_type = narrow_type(input_call.func, libcst.Name)

    #     dep = next(
    #         dep
    #         for dep in deps
    #         if dep["output_type"]["name"] == output_type.id
    #         and len(dep["input_types"]) == 1
    #         and dep["input_types"][0]["name"] == input_type.id
    #     )
    #     module = dep["rule_dep"]["module"]
    #     new_function = dep["rule_dep"]["function"]

    #     new_call = libcst.Call(
    #         func=libcst.Name(id=new_function),
    #         args=[input_call],
    #         keywords=[
    #             libcst.keyword(value=libcst.Call(func=libcst.Name(id="implicitly"), args=[], keywords=[]))
    #         ],
    #     )
    #     imports = [libcst.ImportFrom(module, names=[libcst.alias(new_function)], level=0)]
    #     return new_call, imports

    # def map_dict_form_get_to_new_syntax(
    #     self, get: libcst.Call, deps: list[RuleGraphGetDep]
    # ) -> tuple[libcst.Call, list[libcst.ImportFrom]]:
    #     """Map the dict form of Get() to the new syntax.

    #     The expected mapping is roughly:
    #     Get(<OutputType>, {input1: <Input1Type>, ..inputN: <InputNType>}) -> the_rule_to_call(**implicitly(input))

    #     This form expects that the `get` call has exactly 2 args (otherwise, a different form would be used)
    #     """

    #     logger.debug(dump(get, indent=2))
    #     output_type = narrow_type(get.args[0], libcst.Name)
    #     input_dict = narrow_type(get.args[1], libcst.Dict)
    #     input_types = {k.id for k in input_dict.values if isinstance(k, libcst.Name)}

    #     dep = next(
    #         dep
    #         for dep in deps
    #         if dep["output_type"]["name"] == output_type.id
    #         and {i["name"] for i in dep["input_types"]} == input_types
    #     )

    #     module = dep["rule_dep"]["module"]
    #     new_function = dep["rule_dep"]["function"]

    #     new_call = libcst.Call(
    #         func=libcst.Name(id=new_function),
    #         args=[],
    #         keywords=[
    #             libcst.keyword(
    #                 value=libcst.Call(func=libcst.Name(id="implicitly"), args=[input_dict], keywords=[])
    #             )
    #         ],
    #     )
    #     imports = [libcst.ImportFrom(module, names=[libcst.alias(new_function)], level=0)]
    #     return new_call, imports


# ------------------------------------------------------------------------------------------
# Call-by-name visitor
# ------------------------------------------------------------------------------------------


class CallByNameTransformer(m.MatcherDecoratableTransformer):
    def __init__(self, filename: PurePath, syntax_mapper: CallByNameSyntaxMapper) -> None:
        super().__init__()

        self.filename = filename
        self.syntax_mapper = syntax_mapper
        self.calling_function: str = ""
        # self.replacements: list[Replacement] = []
    
    def visit_FunctionDef(self, node: libcst.FunctionDef) -> None:
        self.calling_function = node.name.value
    
    def leave_FunctionDef(self, original_node: libcst.FunctionDef, updated_node: libcst.FunctionDef) -> libcst.FunctionDef:
        self.calling_function = ""
        return updated_node
    # .with_changes(name=libcst.Name("sj"),
            # lpar=libcst.LeftParen(),
            # rpar=libcst.RightParen(),
        # )

    @m.leave(m.Call(func=m.Name(value="Get")))
    def handle_get(
        self, original_node: libcst.Call, updated_node: libcst.Call
    ) -> libcst.Call:
        replacement = self.syntax_mapper.map_get_to_new_syntax(original_node, self.filename, self.calling_function)
        if replacement:
            # logger.error(f"Rewriting {dump(original_node)} to {dump(replacement.new_source)}")
            # updated_node = replacement.new_source
            return replacement.new_source
            # return updated_node.with_changes(func=libcst.Name(value="implicitly"))

        return original_node
    
    # @m.leave(m.Call(func=m.Name(value="MultiGet")))
    # def handle_multiget(
    #     self, original_node: libcst.Call, updated_node: libcst.Call
    # ) -> libcst.Call:
    #     print(original_node.args[0].value, self.calling_function)
    #     return original_node


# ------------------------------------------------------------------------------------------
# libcst utilities
# ------------------------------------------------------------------------------------------

def _make_import_from(module: str, func: str) -> libcst.ImportFrom:
    """Manually generating ImportFrom using Attributes is tricky, parse a string instead"""
    statement = libcst.parse_statement(f"from {module} import {func}")
    assert isinstance(statement.body, Sequence)
    return libcst.ensure_type(statement.body[0], libcst.ImportFrom)