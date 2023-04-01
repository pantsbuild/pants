---
title: "Add codegen"
slug: "plugins-codegen"
excerpt: "How to add a new code generator to Pants."
hidden: false
createdAt: "2020-07-01T04:52:54.817Z"
---
Pants supports code generators that convert a protocol language like Protobuf into other languages, such as Python or Java. The same protocol source may be used to generate multiple distinct languages.

Pants will not actually write the generated files to disk, except when running `pants export-codegen`. Instead, any targets that depend on the protocol targets will cause their code to be generated, and those generated files will be copied over into the "chroot" (temporary directory) where Pants executes.

> 📘 Example: Protobuf -> Python
> 
> This guide walks through each step of adding Protobuf to generate Python sources. See [here](https://github.com/pantsbuild/pants/tree/master/src/python/pants/backend/codegen/protobuf) for the final result.

This guide assumes that you are running a code generator that already exists outside of Pants as a stand-alone binary, such as running Protoc or Thrift.

If you are instead writing your own code generation logic inline, you can skip Step 2. In Step 4, rather than running a `Process`, use [`CreateDigest`](doc:rules-api-file-system).

1. Create a target type for the protocol
----------------------------------------

You will need to define a new target type to allow users to provide metadata for their protocol files, e.g. their `.proto` files. See [Creating new targets](doc:target-api-new-targets) for a guide on how to do this.

```python
from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, SingleSourceField, Target

class ProtobufSourceField(SingleSourceField):
    expected_file_extensions = (".proto",)

class ProtobufSourceTarget(Target):
    alias = "protobuf_source"
    help = "A single Protobuf file."
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ProtobufSourceField)
```

You should define a subclass of `SourcesField`, like `ProtobufSourceField` or `ThriftSourceField`. This is important for Step 3.

Typically, you will want to register the `Dependencies` field.

### Target type already exists?

If Pants already has a target type for your protocol—such as Pants already having a `ProtobufSourceTarget` defined—you should not create a new target type.

Instead, you can optionally add any additional fields that you would like through plugin fields. See [Extending pre-existing targets](doc:target-api-extending-targets).

### Add dependency injection (Optional)

Often, generated files will depend on a runtime library to work. For example, Python files generated from Protobuf depend on the `protobuf` library.

Instead of users having to explicitly add this dependency every time, you can dynamically inject this dependency for them.

To inject dependencies:

1. Subclass the `Dependencies` field. Register this subclass on your protocol target type.
2. Define a subclass of `InjectDependenciesRequest` and set the class property `inject_for` to the `Dependencies` subclass defined in the previous step. Register this new class with a [`UnionRule`](doc:rules-api-unions) for `InjectDependenciesRequest`.
3. Create a new rule that takes your new  `InjectDependenciesRequest` subclass as a parameter and returns `InjectedDependencies`.

```python
from pants.engine.addresses import Address
from pants.engine.target import Dependencies, InjectDependenciesRequest, InjectedDependencies
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule

class ProtobufDependencies(Dependencies):
    pass

...

class ProtobufSourceTarget(Target):
    alias = "protobuf_source"
    core_fields = (*COMMON_TARGET_FIELDS, ProtobufDependencies, ProtobufSourceField)

class InjectProtobufDependencies(InjectDependenciesRequest):
    inject_for = ProtobufDependencies

@rule
async def inject_dependencies(_: InjectProtobufDependencies) -> InjectedDependencies:
    address = Address("3rdparty/python", target_name="protobuf")
    return InjectedDependencies([address])

def rules():
    return [
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectProtobufDependencies),
    ]
```

This example hardcodes the injected address. You can instead add logic to your rule to make this dynamic. For example, in Pants's Protobuf implementation, Pants looks for a `python_requirement` target with `protobuf`. See [protobuf/python/python_protobuf_subsystem.py](https://github.com/pantsbuild/pants/blob/main/src/python/pants/backend/codegen/protobuf/python/python_protobuf_subsystem.py).

2. Install your code generator
------------------------------

There are several ways for Pants to install your tool. See [Installing tools](doc:rules-api-installing-tools). This example will use `ExternalTool` because there is already a pre-compiled binary for Protoc.

```python
from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform

class Protoc(ExternalTool):
    options_scope = "protoc"
    help = "The protocol buffer compiler (https://developers.google.com/protocol-buffers)."

    default_version = "3.11.4"
    default_known_versions = [
        "3.11.4|linux_arm64 |f24c9fa1fc4a7770b8a5da66e515cb8a638d086ad2afa633abb97137c5f029a8|1481946",
        "3.11.4|linux_x86_64|6d0f18cd84b918c7b3edd0203e75569e0c8caecb1367bbbe409b45e28514f5be|1591191",
        "3.11.4|macos_arm64 |8c6af11e1058efe953830ecb38324c0e0fd2fb67df3891896d138c535932e7db|2482119",
        "3.11.4|macos_x86_64|8c6af11e1058efe953830ecb38324c0e0fd2fb67df3891896d138c535932e7db|2482119",
    ]

    def generate_url(self, plat: Platform) -> str:
        platform_mapping = {
            "linux_arm64": "linux-aarch_64",
            "linux_x86_64": "linux-x86_64",
            "macos_arm64": "osx-x86_64",
            "macos_x86_64": "osx-x86_64",
        }
        plat_str = platform_mapping[plat.value]
        return (
            f"https://github.com/protocolbuffers/protobuf/releases/download/"
            f"v{self.version}/protoc-{self.version}-{plat_str}.zip"
        )

    def generate_exe(self, _: Platform) -> str:
        return "./bin/protoc"
```

3. Create a `GenerateSourcesRequest`
------------------------------------

`GenerateSourcesRequest` tells Pants the `input` and the `output` of your code generator, such as going from `ProtobufSourceField -> PythonSourceField`. Pants will use this to determine when to use your code generation implementation.

Subclass `GenerateSourcesRequest`:

```python
from pants.engine.target import GenerateSourcesRequest

class GeneratePythonFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSourceField
    output = PythonSourceField
```

The `input` should be the `SourcesField` class for your protocol target from Step 1.

The `output` should typically be the `SourcesField` class corresponding to the "language" you're generating for, such as `JavaSourceField` or `PythonSourceField`. The `output` type will understand subclasses of what you specify, so, generally, you should specify `PythonSourceField` instead of something more specific like `PythonTestSourceField`.

Note that your rule will not actually return an instance of the `output` type, e.g. `PythonSourceField`. Codegen rules only return a `Snapshot`, rather than a whole `SourcesField`. The `output` field is only used as a signal of intent.

Finally, register your new `GenerateSourcesRequest` with a [`UnionRule`](doc:rules-api-unions).

```python
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule

def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GeneratePythonFromProtobufRequest),
    ]
```

4. Create a rule for your codegen logic
---------------------------------------

Your rule should take as a parameter the `GenerateSourcesRequest` from Step 3 and the `Subsystem` (or `ExternalTool`) from Step 2. It should return `GeneratedSources`.

```python
from pants.engine.rules import rule
from pants.engine.target import GeneratedSources

...

@rule
async def generate_python_from_protobuf(
    request: GeneratePythonFromProtobufRequest, protoc: Protoc
) -> GeneratedSources:
    ...
    return GeneratedSources(result_snaphsot)
```

The `request` parameter will have two fields: `protocol_sources: Snapshot` and `protocol_target: Target`. Often, you will want to include `protocol_sources` in the `input_digest` to the `Process` you use to run the generator. You can use `protocol_target` to look up more information about the input target, such as finding its dependencies.

The rule should return `GeneratedSources`, which take a [`Snapshot`](doc:rules-api-file-system) as its only argument. This should be a Snapshot of the generated files for the input target.

If you used `ExternalTool` in step 1, you will use `Get(DownloadedExternalTool, ExternalToolRequest)` to install the tool. Be sure to merge this with the `protocol_sources` and any other relevant input digests via `Get(Digest, MergeDigests)`.

For many code generators, you will need to get the input target's direct or transitive dependencies and include their sources in the `input_digest`. See [Rules and the Target API](doc:rules-api-and-target-api).

You will likely need to add logic for handling [source roots](doc:source-roots). For example, the code generator may not understand source roots so you may need to [strip source roots](doc:rules-api-and-target-api) before putting the sources in the `input_digest`. Likely, you will want to restore a source root after generation because most Pants code will assume that there is a source root present. In the below example, we restore the original source root, e.g. `src/protobuf/f.proto` becomes `src/protobuf/f_pb2.py`. See [`protobuf/python/rules.py`](https://github.com/pantsbuild/pants/tree/master/src/python/pants/backend/codegen/protobuf/python/rules.py) for a more complex example that allows the user to specify what source root to use through a field on the `protobuf_library`.

```python
@rule
async def generate_python_from_protobuf(
    request: GeneratePythonFromProtobufRequest, protoc: Protoc, platform: Platform
) -> GeneratedSources:
    download_protoc_get = Get(
        DownloadedExternalTool, ExternalToolRequest, protoc.get_request(platform)
    )

    # Protoc needs all transitive dependencies on `protobuf_libraries` to work properly. It won't
    # actually generate those dependencies; it only needs to look at their .proto files to work
    # with imports.
    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest([request.protocol_target.address]),
    )

    # NB: By stripping the source roots, we avoid having to set the value `--proto_path`
    # for Protobuf imports to be discoverable.
    all_stripped_sources_get = Get(
        StrippedSourceFiles,
        SourceFilesRequest(
            (tgt.get(Sources) for tgt in transitive_targets.closure),
            for_sources_types=(ProtobufSources,),
        ),
    )
    target_stripped_sources_get= Get(
        StrippedSourceFiles, SourceFilesRequest([request.protocol_target[ProtobufSources]]),
    )

    (
        downloaded_protoc_binary,
        all_sources_stripped,
        target_sources_stripped,
    ) = await MultiGet(
        download_protoc_get,
        all_stripped_sources_get,
        target_stripped_sources_get,
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (all_sources_stripped.snapshot.digest, downloaded_protoc_binary.digest)
        ),
    )

    output_dir = "_generated_files"
    result = await Get(
        ProcessResult,
        Process(
            (
                downloaded_protoc_binary.exe,
                "--python_out",
                output_dir,
                *target_sources_stripped.snapshot.files,
            ),
            input_digest=input_digest,
            description=f"Generating Python sources from {request.protocol_target.address}.",
            output_directories=(output_dir,),
        ),
    )

    # We must do some path manipulation on the output digest for it to look like normal sources,
    # including adding back a source root.
    source_root_request = SourceRootRequest.for_target(request.protocol_target)
    normalized_digest, source_root = await MultiGet(
        Get(Digest, RemovePrefix(result.output_digest, output_dir)),
        Get(SourceRoot, SourceRootRequest, source_root_request),
    )
    source_root_restored = (
        await Get(Snapshot, AddPrefix(normalized_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, normalized_digest)
    )
    return GeneratedSources(source_root_restored)
```

Finally, update your plugin's `register.py` to activate this file's rules.

```python pants-plugins/protobuf/register.py
from protobuf import python_support

def rules():
    return [*python_support.rules()]
```

> 📘 Tip: use `export-codegen` to test it works
> 
> Run `pants export-codegen path/to/file.ext` to ensure Pants is correctly generating the file. This will write the generated file(s) under the `dist/` directory, using the same path that will be used during Pants runs.

5. Audit call sites to ensure they've enabled codegen
-----------------------------------------------------

Call sites must opt into using codegen, and they must also specify what types of sources they're expecting. See [Rules and the Target API](doc:rules-api-and-target-api) about `SourcesField`.

For example, if you added a code generator that goes from `ProtobufSourceField -> JavaSourceField`, then Pants's Python backend would not use your new implementation because it ignores `JavaSourceField`.

You should check that everywhere you're expecting is using your new codegen implementation by manually testing it out. Create a new protocol target, add it to the `dependencies` field of a target, and then run goals like `pants package` and `pants test` to make sure that the generated file works correctly.

6. Add tests (optional)
-----------------------

Refer to [Testing rules](doc:rules-api-testing).
