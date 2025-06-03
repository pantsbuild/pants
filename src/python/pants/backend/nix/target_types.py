from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    SingleSourceField,
    StringField,
    Target,
)


class NixSourceField(SingleSourceField):
    pass


class NixDependenciesField(Dependencies):
    pass


class NixSourceTarget(Target):
    alias = "nix_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        NixSourceField,
        NixDependenciesField,
    )


class NixBinaryExprField(StringField):
    alias = "expr"
    required = True  # TODO make expr optional
    help = "Passed to nix-instantiate --expr."


class NixBinaryRelativePathField(StringField):
    alias = "rel_path"
    required = True
    help = "Binary path relative to derivation root."


class NixBinaryDependencies(Dependencies):
    pass


class NixBinaryTarget(Target):
    alias = "nix_binary"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        NixBinaryExprField,
        NixBinaryDependencies,
        NixBinaryRelativePathField,
    )
