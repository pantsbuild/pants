# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, Optional, Tuple, Union, cast

from pants.backend.jvm.subsystems import shader
from pants.backend.jvm.targets.jvm_binary import JarRules
from pants.build_graph.address import Address
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    BundlesField,
    Dependencies,
    DictStringToStringField,
    DictStringToStringSequenceField,
    IntField,
    PrimitiveField,
    ProvidesField,
    ScalarField,
    SequenceField,
    Sources,
    StringField,
    StringSequenceField,
    Target,
)
from pants.fs.archive import TYPE_NAMES
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency import JarDependency

# -----------------------------------------------------------------------------------------------
# Common JVM Fields
# -----------------------------------------------------------------------------------------------


class JvmExcludes(SequenceField):
    """`exclude` objects to filter this target's transitive dependencies against."""

    alias = "excludes"
    expected_element_type = Exclude
    expected_type_description = "an iterable of `exclude` objects (e.g. a list)"

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[Exclude]], *, address: Address
    ) -> Optional[Tuple[Exclude, ...]]:
        return super().compute_value(raw_value, address=address)


class JvmServices(DictStringToStringSequenceField):
    """A dictionary mapping service interface names to the classes owned by this target that
    implement them.

    Keys should be fully qualified service class names. Values should be lists of strings, where
    each string is the fully qualified class name of a class owned by this target that implements
    the service interface and should be discoverable by the JVM service provider discovery
    mechanism described here: https://docs.oracle.com/javase/10/docs/api/java/util/ServiceLoader.html.
    """

    alias = "services"


class JvmPlatform(StringField):
    """The name of the platform (defined under the jvm-platform subsystem) to use for compilation
    (that is, a key into the --jvm-platform-platforms dictionary).

    If unspecified, the platform will default to the first one of these that exist: (1) the
    default_platform specified for jvm-platform, (2) a platform constructed from whatever Java
    version is returned by DistributionLocator.cached().version.
    """

    alias = "platform"


class JvmRuntimePlatform(StringField):
    """The name of the platform (defined under the jvm-platform subsystem) to use for runtime (that
    is, a key into the --jvm-platform-platforms dictionary).

    If unspecified, the platform will default to the first one of these that exist: (1) the
    default_runtime_platform specified for jvm-platform, (2) the platform that would be used for the
    `platform` field.
    """

    alias = "runtime_platform"


class JvmStrictDeps(BoolField):
    """When True, only the directly declared deps of the target will be used at compilation time.

    This enforces that all direct deps of the target are declared, and can improve compilation speed
    due to smaller classpaths. Transitive deps are always provided at runtime.
    """

    alias = "strict_deps"
    default = False


class JvmExports(StringSequenceField):
    """A sequence of exported targets, which will be accessible to dependents even with strict_deps
    turned on.

    A common use case is for library targets to to export dependencies that it knows its dependents
    will need. Then any dependents of that library target will have access to those dependencies
    even when strict_deps is True.

    Note: exports is transitive, which means dependents have access to the closure of exports. An
    example will be that if A exports B, and B exports C, then any targets that depends on A will
    have access to both B and C.
    """

    alias = "exports"


class JvmCompilerOptionSets(StringSequenceField):
    """For every element in this list, enable the corresponding flags during compilation of the
    target."""

    alias = "compiler_option_sets"


class ZincFileManagerToggle(BoolField):
    """Whether to use zinc provided file manager that allows transactional rollbacks, but in certain
    cases may conflict with user libraries."""

    alias = "zinc_file_manager"
    default = False


class JavacPluginsField(StringSequenceField):
    """Names of compiler plugins to use when compiling this target with javac."""

    alias = "javac_plugins"


class JavacPluginArgs(DictStringToStringSequenceField):
    """Map from javac plugin name to list of arguments for that plugin."""

    alias = "javac_plugin_args"


COMMON_JVM_FIELDS = (
    *COMMON_TARGET_FIELDS,
    Dependencies,
    ProvidesField,
    JvmExcludes,
    JvmExports,
    JvmServices,
    JvmPlatform,
    JvmStrictDeps,
    JvmCompilerOptionSets,
    ZincFileManagerToggle,
    JavacPluginsField,
    JavacPluginArgs,
)


class ExtraJvmOptions(StringSequenceField):
    """A list of options to be passed to the JVM when running.

    Example: ['-Dexample.property=1', '-DMyFlag', '-Xmx4g'].
    """

    alias = "extra_jvm_options"


class ScalacPluginsField(StringSequenceField):
    """Names of compiler plugins to use when compiling this target with scalac."""

    alias = "scalac_plugins"


class ScalacPluginArgs(DictStringToStringSequenceField):
    """Map from scalac plugin name to list of arguments for that plugin."""

    alias = "scalac_plugin_args"


# -----------------------------------------------------------------------------------------------
# `annotation_processor` target
# -----------------------------------------------------------------------------------------------


class AnnotationProcessorsField(StringSequenceField):
    """The fully qualified class names of the annotation processors this library exports."""

    alias = "processors"


class AnnotationProcessor(Target):
    """A Java library containing annotation processors."""

    alias = "annotation_processor"
    core_fields = (
        *COMMON_JVM_FIELDS,
        Sources,
        ScalacPluginsField,
        ScalacPluginArgs,
        AnnotationProcessorsField,
    )
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `benchmark` target
# -----------------------------------------------------------------------------------------------


class JvmBenchmark(Target):
    """A caliper benchmark.

    Run it with the `bench` goal.
    """

    alias = "benchmark"
    core_fields = (
        *COMMON_JVM_FIELDS,
        Sources,
        ScalacPluginsField,
        ScalacPluginArgs,
        JvmRuntimePlatform,
    )
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `credentials` and `netrc_credentials` targets
# -----------------------------------------------------------------------------------------------


class CredentialsUsername(StringField):
    """The username to use with Maven."""

    alias = "username"
    required = True


class CredentialsPassword(StringField):
    """The password to use with Maven."""

    alias = "password"
    required = True


class JvmCredentials(Target):
    """Credentials for a Maven repository.

    See the target `netrc_credentials` if you'd like to load the credentials through ~/.netrc.

    The `publish.jar` section of your `pants.toml` file can refer to one or more of these.
    """

    alias = "credentials"
    core_fields = (*COMMON_TARGET_FIELDS, CredentialsUsername, CredentialsPassword)
    v1_only = True


class NetrcCredentials(Target):
    """Credentials for a Maven repository that get automatically loaded from ~/.netrc.

    The `publish.jar` section of your `pants.toml` file can refer to one or more of these.
    """

    alias = "netrc_credentials"
    core_fields = COMMON_TARGET_FIELDS
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `jar_library` target
# -----------------------------------------------------------------------------------------------


class JarsField(SequenceField):
    """A list of `jar` objects to depend upon."""

    alias = "jars"
    expected_element_type = JarDependency
    expected_type_description = "an iterable of `jar` objects (e.g. a list)"
    value: Tuple[JarDependency, ...]
    required = True

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[JarDependency]], *, address: Address
    ) -> Tuple[JarDependency, ...]:
        return cast(Tuple[JarDependency, ...], super().compute_value(raw_value, address=address))


class ManagedJarDependenciesAddress(StringField):
    """Address of a managed_jar_dependencies() target to use.

    If omitted, uses the default managed_jar_dependencies() target set by
    --jar-dependency-management-default-target.
    """

    alias = "managed_dependencies"


class JarLibrary(Target):
    """A set of external JAR files."""

    alias = "jar_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, JarsField, ManagedJarDependenciesAddress)
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `java_library` target
# -----------------------------------------------------------------------------------------------


class JavaLibrarySources(Sources):
    default = ("*.java", "!*Test.java")


class JavaLibrary(Target):
    """A Java library."""

    alias = "java_library"
    core_fields = (*COMMON_JVM_FIELDS, JavaLibrarySources)
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `java_agent` target
# -----------------------------------------------------------------------------------------------


class JavaAgentPremain(StringField):
    """When an agent is specified at JVM launch time this attribute specifies the agent class.

    Either the `premain` or `agent_class` field must be specified.
    """

    alias = "premain"


class JavaAgentClass(StringField):
    """If an implementation supports a mechanism to start agents sometime after the VM has started,
    then this attribute specifies the agent class.

    Either the `premain` or `agent_class` field must be specified.
    """

    alias = "agent_class"


class JavaAgentCanRedefine(BoolField):
    """`True` if the ability to redefine classes is needed by this agent."""

    alias = "can_redefine"
    default = False


class JavaAgentCanRetransform(BoolField):
    """`True` if the ability to retransform classes is needed by this agent."""

    alias = "can_retransform"
    default = False


class JavaAgentCanSetNativeMethodPrefix(BoolField):
    """`True` if the ability to set the native method prefix is needed by this agent."""

    alias = "can_set_native_method_prefix"
    default = False


class JavaAgent(Target):
    """A Java agent entry point."""

    alias = "java_agent"
    core_fields = (
        *JavaLibrary.core_fields,
        JavaAgentPremain,
        JavaAgentClass,
        JavaAgentCanRedefine,
        JavaAgentCanRetransform,
        JavaAgentCanSetNativeMethodPrefix,
    )
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `junit_tests` target
# -----------------------------------------------------------------------------------------------


class JunitTestsSources(Sources):
    default = ("*Test.java", "*Test.scala", "*Spec.scala")


class JunitTestsCwd(StringField):
    """Working directory (relative to the build root) for the tests under this target.

    If unspecified, the working directory will be controlled by junit_run's --cwd and --chroot
    options.
    """

    alias = "cwd"


class JunitTimeout(IntField):
    """A timeout (in seconds) which covers the total runtime of all tests in this target.

    Only applied if `--test-junit-timeouts` is set to True.
    """

    alias = "timeout"


class JunitExtraEnvVars(DictStringToStringField):
    """A map of environment variables to set when running the tests, e.g. {'FOOBAR': '12'}."""

    alias = "extra_env_vars"


class JunitConcurrency(StringField):
    """The concurrency approach to use with tests.

    Overrides the setting of --test-junit-default-concurrency.
    """

    alias = "concurrency"
    valid_choices = (
        "SERIAL",
        "PARALLEL_CLASSES",
        "PARALLEL_METHODS",
        "PARALLEL_CLASSES_AND_METHODS",
    )


class JunitNumThreads(IntField):
    """Use the specified number of threads when running the test.

    Overrides the setting of --test-junit-parallel-threads.
    """

    alias = "threads"


class JunitTests(Target):
    """JUnit tests (both Scala and Java)."""

    alias = "junit_tests"
    core_fields = (
        *COMMON_JVM_FIELDS,
        JvmRuntimePlatform,
        ExtraJvmOptions,
        JunitTestsSources,
        JunitTestsCwd,
        JunitTimeout,
        JunitExtraEnvVars,
        JunitConcurrency,
        JunitNumThreads,
    )
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `jvm_app` target
# -----------------------------------------------------------------------------------------------


class JvmAppBinaryField(StringField):
    """Target spec of the `jvm_binary` that contains the app main."""

    alias = "binary"


class JvmAppBasename(StringField):
    """Name of this application, if different from the `name`.

    Pants uses this in the `bundle` goal to name the distribution artifact.
    """

    alias = "basename"


class JvmAppArchiveFormat(StringField):
    """Create an archive of this type from the bundle."""

    alias = "archive"
    valid_choices = tuple(sorted(TYPE_NAMES))


class JvmAppDeployJarToggle(BoolField):
    """If True, pack all 3rdparty and internal JAR classfiles into a single deployjar in the
    bundle's root dir.

    If unset, all JARs will go into the bundle's libs directory; the root will only contain a
    synthetic jar with its manifest's Class-Path set to those JARs.
    """

    alias = "deployjar"
    default = False


class JvmApp(Target):
    """A deployable JVM application.

    Invoking the `bundle` goal on one of these targets creates a self-contained artifact suitable
    for deployment on some other machine. The artifact contains the executable JAR, its
    dependencies, and extra files like config files, startup scripts, etc.
    """

    alias = "jvm_app"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        BundlesField,
        JvmAppBinaryField,
        JvmAppBasename,
        JvmAppArchiveFormat,
        JvmAppDeployJarToggle,
    )
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `jvm_binary` target
# -----------------------------------------------------------------------------------------------


class JvmBinaryMain(StringField):
    """The name of the `main` class, e.g. 'org.pantsbuild.example.hello.main.HelloMain'.

    This class may be present as the source of this target or depended-upon library.
    """

    alias = "main"


class JvmBinaryBasename(StringField):
    """Base name for the generated `.jar` file, e.g. 'hello'.

    By default, this uses the `name` field. Note this default is unsafe because of the possible
    conflict when multiple binaries are built.
    """

    alias = "basename"


class JvmBinaryDeployExcludes(JvmExcludes):
    """A list of `exclude` objects to apply at deploy time.

    If you, for example, deploy a Java servlet that has one version of `servlet.jar` onto a Tomcat
    environment that provides another version, they might conflict. `deploy_excludes` gives you a
    way to build your code but exclude the conflicting `jar` when deploying.
    """

    alias = "deploy_excludes"


class JvmBinaryDeployJarRules(ScalarField):
    """A `jar_rules` object for packaging this binary in a deploy JAR."""

    alias = "deploy_jar_rules"
    expected_type = JarRules
    expected_type_description = "a `jar_rules` object"

    @classmethod
    def compute_value(
        cls, raw_value: Optional[JarRules], *, address: Address
    ) -> Optional[JarRules]:
        return super().compute_value(raw_value, address=address)


class JvmBinaryManifestEntries(DictStringToStringField):
    """A dict that specifies entries for `ManifestEntries` for adding to MANIFEST.MF when packaging
    this binary."""

    alias = "manifest_entries"


class JvmBinaryShadingRules(PrimitiveField):
    """A list of shading rules to apply when building a shaded (aka monolithic aka fat) binary jar.

    The order of the rules matters: the first rule which matches a fully-qualified class name is
    used to shade it. See shading_relocate(), shading_exclude(), shading_relocate_package(), and
    shading_exclude_package().
    """

    alias = "shading_rules"
    value: Optional[Tuple[Union[shader.UnaryRule, shader.RelocateRule], ...]]
    default = None

    @classmethod
    def compute_value(
        cls,
        raw_value: Optional[Iterable[Union[shader.UnaryRule, shader.RelocateRule]]],
        *,
        address: Address
    ) -> Optional[Tuple[Union[shader.UnaryRule, shader.RelocateRule], ...]]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is None:
            return None
        return tuple(value_or_default)


class JvmBinary(Target):
    """A JVM binary."""

    alias = "jvm_binary"
    core_fields = (
        *COMMON_JVM_FIELDS,
        Sources,
        ExtraJvmOptions,
        JvmRuntimePlatform,
        JvmBinaryMain,
        JvmBinaryBasename,
        JvmBinaryDeployExcludes,
        JvmBinaryDeployJarRules,
        JvmBinaryManifestEntries,
        JvmBinaryShadingRules,
    )
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `jvm_prep_command` target
# -----------------------------------------------------------------------------------------------


class JvmPrepCommandMainClass(StringField):
    """The path to the executable that should be run."""

    alias = "mainclass"
    required = True


class JvmPrepCommandArgs(StringSequenceField):
    """A list of command-line args to the excutable."""

    alias = "args"


class JvmPrepCommandGoal(StringField):
    """Pants goal to run this command in, e.g. "test", "binary", or "compile"."""

    alias = "goal"
    default = "test"


class JvmPrepCommandOptions(ExtraJvmOptions):
    alias = "jvm_options"


class JvmPrepCommand(Target):
    """A command (defined in a Java target) that must be run before other tasks in a goal.

    For example, you can use `jvm_prep_command()` to execute a script that sets up tunnels to
    database servers. These tunnels could then be leveraged by integration tests.

    You can define a jvm_prep_command() target as follows:

      jvm_prep_command(
          name='foo',
          goal='test',
          mainclass='com.example.myproject.BeforeTestMain',
          args=['--foo', 'bar'],
          jvm_options=['-Xmx256M', '-Dmy.property=baz'],
          dependencies=[
              'myproject/src/main/java:lib',
          ],
      )

    Pants will execute the `jvm_prep_command()` when processing the specified goal. They will be
    triggered when running targets that depend on the `prep_command()` target or when the
    target is referenced from the command line.

    See also prep_command for running shell commands.
    """

    alias = "jvm_prep_command"
    core_fields = (
        *COMMON_JVM_FIELDS,
        JvmRuntimePlatform,
        JvmPrepCommandMainClass,
        JvmPrepCommandArgs,
        JvmPrepCommandGoal,
        JvmPrepCommandOptions,
    )
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `managed_jar_dependencies` target
# -----------------------------------------------------------------------------------------------


class ManagedJarDependenciesArtifacts(PrimitiveField):
    """List of `jar` objects or addresses of `jar_library` targets with pinned versions.

    Versions are pinned per (org, name, classifier, ext) artifact coordinate. Excludes et al. are
    ignored for the purposes of pinning).
    """

    alias = "artifacts"
    value: Union[Tuple[str, ...], Tuple[JarDependency]]
    required = True

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Union[Tuple[str, ...], Tuple[JarDependency]]], *, address: Address
    ) -> Union[Tuple[str, ...], Tuple[JarDependency]]:
        value = super().compute_value(raw_value, address=address)
        return tuple(value)


class ManagedJarDependencies(Target):
    """A set of pinned external artifact versions to apply transitively."""

    alias = "managed_jar_dependencies"
    core_fields = (*COMMON_TARGET_FIELDS, ManagedJarDependenciesArtifacts)
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `scala_library` target
# -----------------------------------------------------------------------------------------------


class ScalaSources(Sources):
    default = ("*.scala", "!*Test.scala", "!*Spec.scala")


class JavaSourcesForScala(StringSequenceField):
    """Java libraries this library has a *circular* dependency on.

    If you don't have the particular problem of circular dependencies forced by splitting
    interdependent Java and Scala into multiple targets, don't use this at all. Prefer using
    `dependencies` to express non-circular dependencies.
    """

    alias = "java_sources"


class ScalaLibrary(Target):
    """A Scala library."""

    alias = "scala_library"
    core_fields = (
        *COMMON_JVM_FIELDS,
        ScalacPluginsField,
        ScalacPluginArgs,
        ScalaSources,
        JavaSourcesForScala,
    )
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `javac_plugin` and `scalac_plugin` targets
# -----------------------------------------------------------------------------------------------


class JvmPluginClassname(StringField):
    """The fully qualified plugin class name."""

    alias = "classname"
    required = True


class JvmPluginName(StringField):
    """The name of the plugin.

    Defaults to the value of the `name` field if not supplied.
    """

    alias = "plugin"


class JavacPlugin(Target):
    """A Java compiler plugin."""

    alias = "javac_plugin"
    core_fields = (*JavaLibrary.core_fields, JvmPluginClassname, JvmPluginName)
    v1_only = True


class ScalacPlugin(Target):
    """A Scala compiler plugin."""

    alias = "scalac_plugin"
    core_fields = (*ScalaLibrary.core_fields, JvmPluginClassname, JvmPluginName)
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `unpacked_jars` target
# -----------------------------------------------------------------------------------------------


class UnpackedJarsRequestedLibraries(StringSequenceField):
    """Addresses of jar_library targets that specify the jars you want to unpack."""

    alias = "libraries"
    required = True


class UnpackedJarsIncludePatterns(StringSequenceField):
    """Fileset patterns to include from the archive."""

    alias = "include_patterns"


class UnpackedJarsExcludePatterns(StringSequenceField):
    """Fileset patterns to exclude from the archive.

    Exclude patterns are processed before include_patterns.
    """

    alias = "exclude_patterns"


class UnpackedJarsIntransitiveToggle(BoolField):
    """Whether to unpack all resolved dependencies of the JARs or just the JARs themselves."""

    alias = "intransitive"
    default = False


class UnpackedJars(Target):
    """A set of sources extracted from JAR files."""

    alias = "unpacked_jars"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        UnpackedJarsRequestedLibraries,
        UnpackedJarsIncludePatterns,
        UnpackedJarsExcludePatterns,
        UnpackedJarsIntransitiveToggle,
    )
    v1_only = True
