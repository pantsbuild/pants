use std::fmt;

use indexmap::{indexset, IndexSet};

use crate::builder::combinations_of_one;
use crate::{Palette, Query, RuleGraph};

#[test]
fn combinations_of_one_test() {
    let combo = |input: Vec<Vec<usize>>| -> Vec<Vec<usize>> {
        combinations_of_one(&input)
            .map(|output| output.into_iter().cloned().collect())
            .collect()
    };
    let empty: Vec<Vec<usize>> = vec![];

    // Any empty set means the whole result is empty.
    assert_eq!(empty, combo(vec![]));
    assert_eq!(empty, combo(vec![vec![1, 2], vec![]]));
    assert_eq!(empty, combo(vec![vec![], vec![1, 2]]));

    assert_eq!(vec![vec![1]], combo(vec![vec![1]]));
    assert_eq!(
        vec![vec![1, 3], vec![2, 3]],
        combo(vec![vec![1, 2], vec![3]])
    );
    assert_eq!(
        vec![vec![1, 2, 4], vec![1, 3, 4]],
        combo(vec![vec![1], vec![2, 3], vec![4]])
    );
}

#[test]
fn basic() {
    let rules = indexset![Rule("a", "a_from_b", vec![DependencyKey("b", None)])];
    let queries = indexset![Query::new("a", vec!["b"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["b"], "a").unwrap();
}

#[test]
fn singleton() {
    let rules = indexset![Rule("a", "a_singleton", vec![])];
    let queries = indexset![Query::new("a", vec![])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec![""], "a").unwrap();
}

#[test]
fn insufficient_query() {
    let rules = indexset![Rule("a", "a_from_b", vec![DependencyKey("b", None)])];
    let queries = indexset![Query::new("a", vec![])];

    assert!(RuleGraph::new(rules, queries)
        .err()
        .unwrap()
        .contains("No installed rules return the type b"));
}

#[test]
fn no_rules() {
    let rules: IndexSet<Rule> = indexset![];
    let queries = indexset![Query::new("a", vec![])];

    assert!(RuleGraph::new(rules, queries)
        .err()
        .unwrap()
        .contains("No installed rules return the type a"));
}

#[test]
fn ambiguity() {
    let rules = indexset![
        Rule("a", "a_from_b", vec![DependencyKey("b", None)]),
        Rule("a", "a_from_c", vec![DependencyKey("c", None)]),
    ];
    let queries = indexset![Query::new("a", vec!["b", "c"])];

    assert!(RuleGraph::new(rules, queries)
        .err()
        .unwrap()
        .contains("Encountered 1 rule graph error:\n  Too many"));
}

#[test]
fn nested_single() {
    let rules = indexset![
        Rule("a", "a_from_b", vec![DependencyKey("b", Some("c"))]),
        Rule(
            "b",
            "b_from_c",
            vec![DependencyKey("c", None), DependencyKey("d", None)],
        ),
    ];
    let queries = indexset![Query::new("a", vec!["d"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["d"], "a").unwrap();
}

#[test]
fn nested_multiple() {
    let rules = indexset![
        Rule("a", "a_from_b", vec![DependencyKey("b", Some("c"))]),
        Rule(
            "b",
            "b_from_c",
            vec![DependencyKey("c", None), DependencyKey("d", None)],
        ),
        Rule(
            "b",
            "b_from_other_unreachable",
            vec![DependencyKey("d", None)],
        ),
    ];
    let queries = indexset![Query::new("a", vec!["d"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["d"], "a").unwrap();
}

#[test]
fn self_cycle_simple() {
    let rules = indexset![Rule(
        "Fib",
        "fib",
        vec![
            DependencyKey("int", None),
            DependencyKey("Fib", Some("int")),
        ],
    )];
    let queries = indexset![
        Query::new("Fib", vec!["int"]),
        Query::new("Fib", vec!["Fib"]),
    ];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["int"], "Fib").unwrap();
    graph.find_root_edges(vec!["Fib"], "Fib").unwrap();
}

#[test]
fn self_cycle_with_external_dep() {
    let rules = indexset![
        Rule(
            "Thing",
            "transitive_thing",
            vec![
                DependencyKey("int", None),
                // We expect this to be a self-cycle.
                DependencyKey("Thing", Some("int")),
                // And this to be satisfied by the second rule, even though we already have an int in scope.
                DependencyKey("int", Some("ExternalDep")),
            ],
        ),
        Rule(
            "int",
            "external_dep",
            vec![DependencyKey("ExternalDep", None)],
        ),
    ];
    let queries = indexset![Query::new("Thing", vec!["int"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["int"], "Thing").unwrap();
}

#[test]
fn ambiguous_cycle() {
    let _logger = env_logger::try_init();
    let rules = indexset![
        Rule(
            "Root",
            "me",
            vec![
                DependencyKey("ME", Some("P")),
                DependencyKey("ME", Some("MPP")),
            ],
        ),
        Rule("ME", "me", vec![DependencyKey("FERR", None)]),
        Rule(
            "FERR",
            "ferr",
            vec![DependencyKey("PD", None), DependencyKey("FPR", None)],
        ),
        Rule("PD", "pd_for_p", vec![DependencyKey("P", None)]),
        Rule("PD", "pd_for_mpp", vec![DependencyKey("MPP", None)]),
        Rule("FPR", "fpr_for_p", vec![DependencyKey("P", None)]),
        Rule("FPR", "fpr_for_mpp", vec![DependencyKey("MPP", None)]),
    ];
    let queries = indexset![Query::new("Root", vec![])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec![], "Root").unwrap();
}

#[test]
fn natural_loop() {
    let rules = indexset![
        Rule(
            "A",
            "a",
            vec![DependencyKey("D", None), DependencyKey("B", Some("E"))],
        ),
        Rule(
            "B",
            "b",
            vec![DependencyKey("E", None), DependencyKey("C", Some("F"))],
        ),
        Rule(
            "C",
            "c",
            vec![DependencyKey("F", None), DependencyKey("A", Some("D"))],
        ),
    ];
    let queries = indexset![Query::new("A", vec!["D"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["D"], "A").unwrap();
}

#[test]
fn multi_path_cycle() {
    let _logger = env_logger::try_init();
    let rules = indexset![
        Rule(
            "A",
            "sao",
            vec![
                DependencyKey("AWO", Some("AS")),
                DependencyKey("AWO", Some("FS")),
            ],
        ),
        Rule("AWO", "awofs", vec![DependencyKey("FS", None)]),
        Rule(
            "AWO",
            "awoas",
            vec![DependencyKey("AS", None), DependencyKey("A", None)],
        ),
    ];
    let queries = indexset![Query::new("A", vec![])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec![], "A").unwrap();
}

#[test]
fn mutual_recursion() {
    let rules = indexset![
        Rule(
            "IsEven",
            "is_even",
            vec![
                DependencyKey("int", None),
                DependencyKey("IsOdd", Some("int")),
            ],
        ),
        Rule(
            "IsOdd",
            "is_odd",
            vec![
                DependencyKey("int", None),
                DependencyKey("IsEven", Some("int")),
            ],
        ),
    ];
    let queries = indexset![
        Query::new("IsEven", vec!["int"]),
        Query::new("IsOdd", vec!["int"]),
    ];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["int"], "IsEven").unwrap();
    graph.find_root_edges(vec!["int"], "IsOdd").unwrap();
}

#[test]
fn wide() {
    let _logger = env_logger::try_init();
    let rules = indexset![
        Rule("Output", "one", vec![DependencyKey("Output", Some("A"))]),
        Rule(
            "Output",
            "two",
            vec![DependencyKey("A", None), DependencyKey("Output", Some("B"))],
        ),
        Rule(
            "Output",
            "three",
            vec![DependencyKey("B", None), DependencyKey("Output", Some("C"))],
        ),
        Rule(
            "Output",
            "four",
            vec![DependencyKey("C", None), DependencyKey("D", None)],
        ),
    ];
    let queries = indexset![Query::new("Output", vec!["D"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["D"], "Output").unwrap();
}

#[test]
fn reduced_source_roots() {
    let _logger = env_logger::try_init();
    let rules = indexset![
        Rule("SourceRootConfig", "construct_scope_source", vec![]),
        Rule(
            "OptionalSourceRootsResult",
            "get_optional_source_roots",
            vec![
                DependencyKey("SourceRootsRequest", None),
                DependencyKey("OptionalSourceRoot", Some("SourceRootRequest")),
            ],
        ),
        Rule(
            "Digest",
            "<intrinsic>",
            vec![DependencyKey("RemovePrefix", None)],
        ),
        Rule(
            "Snapshot",
            "<intrinsic>",
            vec![DependencyKey("Digest", None)],
        ),
        Rule(
            "Digest",
            "<intrinsic>",
            vec![DependencyKey("DigestSubset", None)],
        ),
        Rule(
            "Digest",
            "<intrinsic>",
            vec![DependencyKey("PathGlobs", None)],
        ),
        Rule(
            "Digest",
            "<intrinsic>",
            vec![DependencyKey("MergeDigests", None)],
        ),
        Rule(
            "SourceRootsResult",
            "get_source_roots",
            vec![
                DependencyKey("SourceRootsRequest", None),
                DependencyKey("OptionalSourceRootsResult", Some("SourceRootsRequest")),
            ],
        ),
        Rule(
            "OptionalSourceRoot",
            "get_optional_source_root",
            vec![
                DependencyKey("SourceRootRequest", None),
                DependencyKey("SourceRootConfig", None),
                DependencyKey("Snapshot", Some("PathGlobs")),
                DependencyKey("OptionalSourceRoot", Some("SourceRootRequest")),
            ],
        ),
        Rule(
            "StrippedSourceFiles",
            "strip_source_roots",
            vec![
                DependencyKey("SourceFiles", None),
                DependencyKey("Snapshot", Some("DigestSubset")),
                DependencyKey("SourceRootsResult", Some("SourceRootsRequest")),
                DependencyKey("Snapshot", Some("RemovePrefix")),
                DependencyKey("Digest", Some("DigestSubset")),
                DependencyKey("Digest", Some("RemovePrefix")),
                DependencyKey("Snapshot", Some("MergeDigests")),
            ],
        ),
    ];
    let queries = indexset![Query::new("StrippedSourceFiles", vec!["SourceFiles"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
}

#[test]
fn reduced_codegen_cycle() {
    let _logger = env_logger::try_init();
    let rules = indexset![
        Rule(
            "Process",
            "setup_pex_cli_process",
            vec![
                DependencyKey("PexCliProcess", None),
                DependencyKey("ProcessResult", Some("Process")),
            ],
        ),
        Rule(
            "ProcessResult",
            "fallible_to_exec_result_or_raise",
            vec![
                DependencyKey("FallibleProcessResult", None),
                DependencyKey("ProductDescription", None),
            ],
        ),
        Rule(
            "MultiPlatformProcess",
            "upcast_process",
            vec![DependencyKey("Process", None)],
        ),
        Rule(
            "ProductDescription",
            "get_multi_platform_request_description",
            vec![DependencyKey("MultiPlatformProcess", None)],
        ),
        Rule(
            "FallibleProcessResult",
            "remove_platform_information",
            vec![DependencyKey("MultiPlatformProcess", None)],
        ),
    ];
    let queries = indexset![Query::new("Process", vec!["PexCliProcess"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
}

#[test]
fn full_scale_target() {
    let _logger = env_logger::try_init();
    let rules = indexset![
        Rule(
            "InferredDependencies",
            "infer_python_conftest_dependencies",
            vec![
                DependencyKey("InferConftestDependencies", None),
                DependencyKey("HydratedSources", Some("HydrateSourcesRequest")),
                DependencyKey("AncestorFiles", Some("AncestorFilesRequest")),
                DependencyKey("Owners", Some("OwnersRequest")),
            ],
        ),
        Rule(
            "ThirdPartyModuleToAddressMapping",
            "map_third_party_modules_to_addresses",
            vec![DependencyKey("Targets", Some("AddressSpecs"))],
        ),
        Rule(
            "Targets",
            "resolve_targets",
            vec![
                DependencyKey("UnexpandedTargets", None),
                DependencyKey("Subtargets", Some("Address")),
            ],
        ),
        Rule(
            "Owners",
            "find_owners",
            vec![
                DependencyKey("OwnersRequest", None),
                DependencyKey("Targets", Some("AddressSpecs")),
                DependencyKey("UnexpandedTargets", Some("AddressSpecs")),
                DependencyKey("BuildFileAddress", Some("Address")),
            ],
        ),
        Rule(
            "AddressesWithOrigins",
            "resolve_addresses_with_origins",
            vec![
                DependencyKey("Specs", None),
                DependencyKey("AddressesWithOrigins", Some("AddressSpecs")),
                DependencyKey("AddressesWithOrigins", Some("FilesystemSpecs")),
            ],
        ),
        Rule(
            "InferredDependencies",
            "infer_python_dependencies",
            vec![
                DependencyKey("InferPythonDependencies", None),
                DependencyKey("StrippedSourceFiles", Some("SourceFilesRequest")),
                DependencyKey("PythonModuleOwner", Some("PythonModule")),
            ],
        ),
        Rule(
            "InferredDependencies",
            "infer_python_init_dependencies",
            vec![
                DependencyKey("InferInitDependencies", None),
                DependencyKey("HydratedSources", Some("HydrateSourcesRequest")),
                DependencyKey("AncestorFiles", Some("AncestorFilesRequest")),
                DependencyKey("Owners", Some("OwnersRequest")),
            ],
        ),
        Rule(
            "PythonModuleOwner",
            "map_module_to_address",
            vec![
                DependencyKey("PythonModule", None),
                DependencyKey("FirstPartyModuleToAddressMapping", None),
                DependencyKey("ThirdPartyModuleToAddressMapping", None),
            ],
        ),
        Rule(
            "DownloadedExternalTool",
            "download_external_tool",
            vec![
                DependencyKey("ExternalToolRequest", None),
                DependencyKey("Digest", Some("DownloadFile")),
                DependencyKey("ExtractedDigest", Some("MaybeExtractable")),
            ],
        ),
        Rule(
            "GlobalOptions",
            "construct_scope_",
            vec![DependencyKey("ScopedOptions", Some("Scope"))],
        ),
        Rule(
            "PexEnvironment",
            "find_pex_python",
            vec![DependencyKey("BinaryPaths", Some("BinaryPathRequest"))],
        ),
        Rule(
            "ProcessResult",
            "fallible_to_exec_result_or_raise",
            vec![
                DependencyKey("FallibleProcessResult", None),
                DependencyKey("ProductDescription", None),
            ],
        ),
        Rule(
            "HydratedSources",
            "hydrate_sources",
            vec![
                DependencyKey("HydrateSourcesRequest", None),
                DependencyKey("WrappedTarget", Some("Address")),
                DependencyKey(
                    "GeneratedSources",
                    Some("GeneratePythonFromProtobufRequest"),
                ),
            ],
        ),
        Rule(
            "Digest",
            "<intrinsic>",
            vec![DependencyKey("MergeDigests", None)],
        ),
        Rule(
            "SourceFiles",
            "determine_source_files",
            vec![
                DependencyKey("SourceFilesRequest", None),
                DependencyKey("HydratedSources", Some("HydrateSourcesRequest")),
            ],
        ),
        Rule(
            "UnexpandedTargets",
            "resolve_unexpanded_targets",
            vec![
                DependencyKey("Addresses", None),
                DependencyKey("WrappedTarget", Some("Address")),
            ],
        ),
        Rule(
            "ExtractedDigest",
            "maybe_extract",
            vec![
                DependencyKey("MaybeExtractable", None),
                DependencyKey("ProcessResult", Some("Process")),
            ],
        ),
        Rule(
            "AddressesWithOrigins",
            "addresses_with_origins_from_address_specs",
            vec![
                DependencyKey("AddressSpecs", None),
                DependencyKey("Address", Some("AddressInput")),
                DependencyKey("TargetAdaptor", Some("Address")),
                DependencyKey("UnexpandedTargets", Some("Addresses")),
                DependencyKey("AddressFamily", Some("Dir")),
            ],
        ),
        Rule(
            "BuildFileAddress",
            "find_build_file",
            vec![
                DependencyKey("Address", None),
                DependencyKey("AddressFamily", Some("Dir")),
            ],
        ),
        Rule(
            "AncestorFiles",
            "find_missing_ancestor_files",
            vec![DependencyKey("AncestorFilesRequest", None)],
        ),
        Rule(
            "Digest",
            "<intrinsic>",
            vec![DependencyKey("DownloadFile", None)],
        ),
        Rule(
            "BinaryPaths",
            "find_binary",
            vec![
                DependencyKey("BinaryPathRequest", None),
                DependencyKey("FallibleProcessResult", Some("Process")),
            ],
        ),
        Rule(
            "OptionalSourceRootsResult",
            "get_optional_source_roots",
            vec![
                DependencyKey("SourceRootsRequest", None),
                DependencyKey("OptionalSourceRoot", Some("SourceRootRequest")),
            ],
        ),
        Rule(
            "AddressesWithOrigins",
            "addresses_with_origins_from_filesystem_specs",
            vec![
                DependencyKey("FilesystemSpecs", None),
                DependencyKey("Owners", Some("OwnersRequest")),
            ],
        ),
        Rule(
            "RegisteredTargetTypes",
            "registered_target_types_singleton",
            vec![],
        ),
        Rule(
            "Addresses",
            "strip_address_origins",
            vec![DependencyKey("AddressesWithOrigins", None)],
        ),
        Rule(
            "FallibleProcessResult",
            "remove_platform_information",
            vec![DependencyKey("FallibleProcessResultWithPlatform", None)],
        ),
        Rule(
            "ScopedOptions",
            "scope_options",
            vec![
                DependencyKey("Scope", None),
                DependencyKey("_Options", None),
            ],
        ),
        Rule(
            "TransitiveTargets",
            "transitive_targets",
            vec![
                DependencyKey("Targets", None),
                DependencyKey("Targets", Some("DependenciesRequest")),
            ],
        ),
        Rule(
            "FirstPartyModuleToAddressMapping",
            "map_first_party_modules_to_addresses",
            vec![
                DependencyKey("Targets", Some("AddressSpecs")),
                DependencyKey("StrippedSourceFiles", Some("SourceFilesRequest")),
            ],
        ),
        Rule(
            "Digest",
            "<intrinsic>",
            vec![DependencyKey("DigestSubset", None)],
        ),
        Rule(
            "_Options",
            "parse_options",
            vec![DependencyKey("OptionsBootstrapper", None)],
        ),
        Rule(
            "GeneratedSources",
            "generate_python_from_protobuf",
            vec![
                DependencyKey("GeneratePythonFromProtobufRequest", None),
                DependencyKey("DownloadedExternalTool", Some("ExternalToolRequest")),
                DependencyKey("ProcessResult", Some("Process")),
                DependencyKey("TransitiveTargets", Some("Addresses")),
                DependencyKey("StrippedSourceFiles", Some("SourceFilesRequest")),
                DependencyKey("Digest", Some("MergeDigests")),
                DependencyKey("SourceRoot", Some("SourceRootRequest")),
            ],
        ),
        Rule(
            "SourceRoot",
            "get_source_root",
            vec![
                DependencyKey("SourceRootRequest", None),
                DependencyKey("OptionalSourceRoot", Some("SourceRootRequest")),
            ],
        ),
        Rule(
            "MultiPlatformProcess",
            "upcast_process",
            vec![DependencyKey("Process", None)],
        ),
        Rule(
            "TargetAdaptor",
            "find_target_adaptor",
            vec![
                DependencyKey("Address", None),
                DependencyKey("AddressFamily", Some("Dir")),
            ],
        ),
        Rule(
            "Address",
            "resolve_address",
            vec![DependencyKey("AddressInput", None)],
        ),
        Rule(
            "FallibleProcessResultWithPlatform",
            "<intrinsic>",
            vec![DependencyKey("MultiPlatformProcess", None)],
        ),
        Rule(
            "SourceRootsResult",
            "get_source_roots",
            vec![
                DependencyKey("SourceRootsRequest", None),
                DependencyKey("OptionalSourceRootsResult", Some("SourceRootsRequest")),
            ],
        ),
        Rule(
            "OptionalSourceRoot",
            "get_optional_source_root",
            vec![
                DependencyKey("SourceRootRequest", None),
                DependencyKey("OptionalSourceRoot", Some("SourceRootRequest")),
            ],
        ),
        Rule(
            "StrippedSourceFiles",
            "strip_source_roots",
            vec![
                DependencyKey("SourceFiles", None),
                DependencyKey("SourceRootsResult", Some("SourceRootsRequest")),
                DependencyKey("Digest", Some("DigestSubset")),
            ],
        ),
        Rule(
            "Subtargets",
            "generate_subtargets",
            vec![
                DependencyKey("Address", None),
                DependencyKey("WrappedTarget", Some("Address")),
            ],
        ),
        Rule(
            "ProductDescription",
            "get_multi_platform_request_description",
            vec![DependencyKey("MultiPlatformProcess", None)],
        ),
        Rule(
            "Addresses",
            "resolve_dependencies",
            vec![
                DependencyKey("DependenciesRequest", None),
                DependencyKey("RegisteredTargetTypes", None),
                DependencyKey("Address", Some("AddressInput")),
                DependencyKey("WrappedTarget", Some("Address")),
                DependencyKey("InferredDependencies", Some("InferPythonDependencies")),
                DependencyKey("InferredDependencies", Some("InferInitDependencies")),
                DependencyKey("InferredDependencies", Some("InferConftestDependencies")),
                DependencyKey("Subtargets", Some("Address")),
            ],
        ),
        Rule(
            "WrappedTarget",
            "resolve_target",
            vec![
                DependencyKey("Address", None),
                DependencyKey("RegisteredTargetTypes", None),
                DependencyKey("WrappedTarget", Some("Address")),
                DependencyKey("TargetAdaptor", Some("Address")),
            ],
        ),
        Rule(
            "AddressFamily",
            "parse_address_family",
            vec![
                DependencyKey("GlobalOptions", None),
                DependencyKey("Dir", None),
            ],
        ),
    ];
    let queries = indexset![
        Query::new("AddressesWithOrigins", vec!["OptionsBootstrapper", "Specs"]),
        Query::new("UnexpandedTargets", vec!["OptionsBootstrapper", "Specs"]),
        Query::new("Addresses", vec!["OptionsBootstrapper", "Specs"]),
        Query::new("Owners", vec!["OptionsBootstrapper", "OwnersRequest"]),
        Query::new("Targets", vec!["OptionsBootstrapper", "Specs"]),
        Query::new("TransitiveTargets", vec!["OptionsBootstrapper", "Specs"]),
        Query::new(
            "HydratedSources",
            vec!["OptionsBootstrapper", "HydrateSourcesRequest"],
        ),
        Query::new(
            "SourceFiles",
            vec!["OptionsBootstrapper", "SourceFilesRequest"],
        ),
        Query::new(
            "StrippedSourceFiles",
            vec!["OptionsBootstrapper", "SourceFiles"],
        ),
    ];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
}

impl super::TypeId for &'static str {
    fn display<I>(type_ids: I) -> String
    where
        I: Iterator<Item = Self>,
    {
        type_ids.collect::<Vec<_>>().join("+")
    }
}

// A name and vec of DependencyKeys. Abbreviated for simpler construction and matching.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct Rule(&'static str, &'static str, Vec<DependencyKey>);

impl super::Rule for Rule {
    type TypeId = &'static str;
    type DependencyKey = DependencyKey;

    fn product(&self) -> Self::TypeId {
        self.0
    }

    fn dependency_keys(&self) -> Vec<Self::DependencyKey> {
        self.2.clone()
    }

    fn require_reachable(&self) -> bool {
        !self.1.ends_with("_unreachable")
    }

    fn color(&self) -> Option<Palette> {
        None
    }
}

impl super::DisplayForGraph for Rule {
    fn fmt_for_graph(&self, _: super::DisplayForGraphArgs) -> String {
        self.to_string()
    }
}

impl fmt::Display for Rule {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        write!(f, "{}({}) -> {}", self.1, self.2.len(), self.0)
    }
}

// A product and a param. Abbreviated for simpler construction and matching.
#[derive(Copy, Clone, Debug, Ord, PartialOrd, Eq, Hash, PartialEq)]
struct DependencyKey(&'static str, Option<&'static str>);

impl super::DependencyKey for DependencyKey {
    type TypeId = &'static str;

    fn new_root(product: Self::TypeId) -> Self {
        DependencyKey(product, None)
    }

    fn product(&self) -> Self::TypeId {
        self.0
    }

    fn provided_param(&self) -> Option<Self::TypeId> {
        self.1
    }
}

impl fmt::Display for DependencyKey {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        write!(f, "{:?}", self)
    }
}
