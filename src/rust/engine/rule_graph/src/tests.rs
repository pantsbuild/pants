// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::fmt;

use indexmap::{indexset, IndexSet};

use crate::builder::combinations_of_one;
use crate::{DependencyKey, Palette, Query, RuleGraph, RuleId};

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
fn validation() {
    let rules = indexset![
        Rule::new("a", "get_a", vec![DependencyKey::new("b")]),
        Rule::new("a", "get_a", vec![DependencyKey::new("c")]),
        Rule::new("b", "get_b", vec![DependencyKey::new("c")]),
        Rule::new("t", "get_t", vec![DependencyKey::new("u")]),
        Rule::new("t", "get_t", vec![DependencyKey::new("v")])
    ];
    let queries = indexset![Query::new("a", vec!["b"])];
    assert!(RuleGraph::new(rules, queries)
        .err()
        .unwrap()
        .contains("The following rule ids were each used by more than one rule: get_a, get_t"));
}

#[test]
fn basic() {
    let rules = indexset![Rule::new("a", "a_from_b", vec![DependencyKey::new("b")])];
    let queries = indexset![Query::new("a", vec!["b"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["b"], "a").unwrap();
}

#[test]
fn singleton() {
    let rules = indexset![Rule::new("a", "a_singleton", vec![])];
    let queries = indexset![Query::new("a", vec![])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec![""], "a").unwrap();
}

#[test]
fn insufficient_query() {
    let rules = indexset![Rule::new("a", "a_from_b", vec![DependencyKey::new("b")])];
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
        Rule::new("a", "a_from_b", vec![DependencyKey::new("b")]),
        Rule::new("a", "a_from_c", vec![DependencyKey::new("c")]),
    ];
    let queries = indexset![Query::new("a", vec!["b", "c"])];

    assert!(RuleGraph::new(rules, queries)
        .err()
        .unwrap()
        .contains("Encountered 1 rule graph error:\n  Too many"));
}

#[test]
fn by_name_simple() {
    let rules = indexset![
        Rule::new(
            "a",
            "a_from_b",
            vec![DependencyKey::for_known_rule(RuleId::new("b_from_c"), "b")]
        ),
        Rule::new("b", "b_from_c", vec![DependencyKey::new("c")]),
        Rule::new("b", "b_from_d", vec![DependencyKey::new("d")]),
    ];
    let queries = indexset![Query::new("a", vec!["c", "d"])];
    let graph = RuleGraph::new(rules, queries).unwrap();
    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["c", "d"], "a").unwrap();
}

#[test]
fn masked_params() {
    // The middle rule masks "e", so even though the query provides it, construction should fail.
    let rules = indexset![
        Rule::new(
            "a",
            "a_from_b",
            vec![DependencyKey::new("b").provided_params(vec!["c"])]
        ),
        Rule::new(
            "b",
            "b_from_c",
            vec![
                DependencyKey::new("c"),
                DependencyKey::new("c").provided_params(vec!["d"])
            ],
        )
        .masked_params(vec!["e"]),
        Rule::new(
            "c",
            "c_from_d",
            vec![DependencyKey::new("d"), DependencyKey::new("e")],
        ),
    ];
    let queries = indexset![Query::new("a", vec!["e"])];

    let res = RuleGraph::new(rules, queries).err().unwrap();
    assert!(res.contains(
        "Encountered 1 rule graph error:\n  \
     Rule `b_from_c(2) -> b (for c+e)` masked the parameter type `e`, but it"
    ));
}

#[test]
fn nested_single() {
    let rules = indexset![
        Rule::new(
            "a",
            "a_from_b",
            vec![DependencyKey::new("b").provided_params(vec!["c"])]
        ),
        Rule::new(
            "b",
            "b_from_c",
            vec![DependencyKey::new("c"), DependencyKey::new("d")],
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
        Rule::new(
            "a",
            "a_from_b",
            vec![DependencyKey::new("b").provided_params(vec!["c"])]
        ),
        Rule::new(
            "b",
            "b_from_c",
            vec![DependencyKey::new("c"), DependencyKey::new("d")],
        ),
        Rule::new(
            "b",
            "b_from_other_unreachable",
            vec![DependencyKey::new("d")],
        ),
    ];
    let queries = indexset![Query::new("a", vec!["d"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["d"], "a").unwrap();
}

#[test]
fn self_cycle_simple() {
    let rules = indexset![Rule::new(
        "Fib",
        "fib",
        vec![
            DependencyKey::new("int"),
            DependencyKey::new("Fib").provided_params(vec!["int"]),
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
        Rule::new(
            "Thing",
            "transitive_thing",
            vec![
                DependencyKey::new("int"),
                // We expect this to be a self-cycle.
                DependencyKey::new("Thing").provided_params(vec!["int"]),
                // And this to be satisfied by the second rule, even though we already have an int in scope.
                DependencyKey::new("int").provided_params(vec!["ExternalDep"]),
            ],
        ),
        Rule::new(
            "int",
            "external_dep",
            vec![DependencyKey::new("ExternalDep")],
        ),
    ];
    let queries = indexset![Query::new("Thing", vec!["int"])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["int"], "Thing").unwrap();
}

#[test]
fn multiple_provided() {
    let rules = indexset![
        Rule::new(
            "a",
            "a_from_b",
            vec![DependencyKey::new("b").provided_params(vec!["c", "d"])]
        ),
        Rule::new(
            "b",
            "b_from_c_and_d",
            vec![DependencyKey::new("c"), DependencyKey::new("d"),],
        ),
    ];
    let queries = indexset![Query::new("a", vec![])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec![], "a").unwrap();
}

#[test]
fn in_scope_basic() {
    let rules = indexset![
        Rule::new(
            "a",
            "a_from_b",
            vec![DependencyKey::new("b")
                .provided_params(vec!["c"])
                .in_scope_params(vec!["d"])]
        ),
        Rule::new("b", "b_from_c_and_d", vec![DependencyKey::new("c")],),
    ];

    // Valid when the param is in scope at the callsite (even if it isn't consumed).
    let queries = indexset![Query::new("a", vec!["d"])];
    let graph = RuleGraph::new(rules.clone(), queries).unwrap();
    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec!["d"], "a").unwrap();

    // Invalid otherwise when the param is not in scope.
    let queries = indexset![Query::new("a", vec![])];
    RuleGraph::new(rules, queries).err().unwrap();
}

#[test]
fn in_scope_filtered() {
    let rules = indexset![
        Rule::new(
            "a",
            "a_from_b",
            vec![DependencyKey::new("b")
                .provided_params(vec!["c"])
                .in_scope_params(vec!["d"])]
        ),
        Rule::new(
            "b",
            "b_from_c_and_d",
            vec![DependencyKey::new("c"), DependencyKey::new("e")],
        ),
    ];

    // Even though both "d" and "e" are in scope at the Query, only "c" and "d" are in scope
    // below `a_from_b`.
    let queries = indexset![Query::new("a", vec!["d", "e"])];
    RuleGraph::new(rules, queries).err().unwrap();
}

#[test]
fn in_scope_computed() {
    let _logger = env_logger::try_init();
    let rules = indexset![
        Rule::new(
            "a",
            "a_from_b",
            vec![DependencyKey::new("b")
                .provided_params(vec!["c"])
                .in_scope_params(vec!["d"])]
        ),
        Rule::new("b", "b_from_c", vec![DependencyKey::new("c")],),
        Rule::new("d", "d", vec![],),
    ];

    // Valid when the `in_scope` param can be computed or is a singleton.
    let queries = indexset![Query::new("a", vec![])];
    let graph = RuleGraph::new(rules, queries).unwrap();
    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec![], "a").unwrap();
}

#[test]
fn in_scope_provided() {
    let _logger = env_logger::try_init();
    let rules = indexset![
        Rule::new(
            "a",
            "a_from_b",
            vec![DependencyKey::new("b")
                .provided_params(vec!["c", "d"])
                .in_scope_params(vec!["d"])]
        ),
        Rule::new(
            "b",
            "b_from_c",
            vec![DependencyKey::new("c"), DependencyKey::new("d")],
        ),
    ];

    // Valid when the `in_scope` param can be computed or is a singleton.
    let queries = indexset![Query::new("a", vec![])];
    let graph = RuleGraph::new(rules, queries).unwrap();
    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec![], "a").unwrap();
}

#[test]
fn ambiguous_cycle() {
    let _logger = env_logger::try_init();
    let rules = indexset![
        Rule::new(
            "Root",
            "me1",
            vec![
                DependencyKey::new("ME").provided_params(vec!["P"]),
                DependencyKey::new("ME").provided_params(vec!["MPP"]),
            ],
        ),
        Rule::new("ME", "me2", vec![DependencyKey::new("FERR")]),
        Rule::new(
            "FERR",
            "ferr",
            vec![DependencyKey::new("PD"), DependencyKey::new("FPR")],
        ),
        Rule::new("PD", "pd_for_p", vec![DependencyKey::new("P")]),
        Rule::new("PD", "pd_for_mpp", vec![DependencyKey::new("MPP")]),
        Rule::new("FPR", "fpr_for_p", vec![DependencyKey::new("P")]),
        Rule::new("FPR", "fpr_for_mpp", vec![DependencyKey::new("MPP")]),
    ];
    let queries = indexset![Query::new("Root", vec![])];
    let graph = RuleGraph::new(rules, queries).unwrap();

    graph.validate_reachability().unwrap();
    graph.find_root_edges(vec![], "Root").unwrap();
}

#[test]
fn natural_loop() {
    let rules = indexset![
        Rule::new(
            "A",
            "a",
            vec![
                DependencyKey::new("D"),
                DependencyKey::new("B").provided_params(vec!["E"])
            ],
        ),
        Rule::new(
            "B",
            "b",
            vec![
                DependencyKey::new("E"),
                DependencyKey::new("C").provided_params(vec!["F"])
            ],
        ),
        Rule::new(
            "C",
            "c",
            vec![
                DependencyKey::new("F"),
                DependencyKey::new("A").provided_params(vec!["D"])
            ],
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
        Rule::new(
            "A",
            "sao",
            vec![
                DependencyKey::new("AWO").provided_params(vec!["AS"]),
                DependencyKey::new("AWO").provided_params(vec!["FS"]),
            ],
        ),
        Rule::new("AWO", "awofs", vec![DependencyKey::new("FS")]),
        Rule::new(
            "AWO",
            "awoas",
            vec![DependencyKey::new("AS"), DependencyKey::new("A")],
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
        Rule::new(
            "IsEven",
            "is_even",
            vec![
                DependencyKey::new("int"),
                DependencyKey::new("IsOdd").provided_params(vec!["int"]),
            ],
        ),
        Rule::new(
            "IsOdd",
            "is_odd",
            vec![
                DependencyKey::new("int"),
                DependencyKey::new("IsEven").provided_params(vec!["int"]),
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
        Rule::new(
            "Output",
            "one",
            vec![DependencyKey::new("Output").provided_params(vec!["A"])]
        ),
        Rule::new(
            "Output",
            "two",
            vec![
                DependencyKey::new("A"),
                DependencyKey::new("Output").provided_params(vec!["B"])
            ],
        ),
        Rule::new(
            "Output",
            "three",
            vec![
                DependencyKey::new("B"),
                DependencyKey::new("Output").provided_params(vec!["C"])
            ],
        ),
        Rule::new(
            "Output",
            "four",
            vec![DependencyKey::new("C"), DependencyKey::new("D")],
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
        Rule::new("SourceRootConfig", "construct_scope_source", vec![]),
        Rule::new(
            "OptionalSourceRootsResult",
            "get_optional_source_roots",
            vec![
                DependencyKey::new("SourceRootsRequest"),
                DependencyKey::new("OptionalSourceRoot").provided_params(vec!["SourceRootRequest"]),
            ],
        ),
        Rule::new(
            "Digest",
            "remove_digest_prefix",
            vec![DependencyKey::new("RemovePrefix")],
        ),
        Rule::new(
            "Snapshot",
            "snapshot_from_digest",
            vec![DependencyKey::new("Digest")],
        ),
        Rule::new(
            "Digest",
            "digest_subset",
            vec![DependencyKey::new("DigestSubset")],
        ),
        Rule::new(
            "Digest",
            "digest_from_pathglobs",
            vec![DependencyKey::new("PathGlobs")],
        ),
        Rule::new(
            "Digest",
            "merge_digests",
            vec![DependencyKey::new("MergeDigests")],
        ),
        Rule::new(
            "SourceRootsResult",
            "get_source_roots",
            vec![
                DependencyKey::new("SourceRootsRequest"),
                DependencyKey::new("OptionalSourceRootsResult")
                    .provided_params(vec!["SourceRootsRequest"]),
            ],
        ),
        Rule::new(
            "OptionalSourceRoot",
            "get_optional_source_root",
            vec![
                DependencyKey::new("SourceRootRequest"),
                DependencyKey::new("SourceRootConfig"),
                DependencyKey::new("Snapshot").provided_params(vec!["PathGlobs"]),
                DependencyKey::new("OptionalSourceRoot").provided_params(vec!["SourceRootRequest"]),
            ],
        ),
        Rule::new(
            "StrippedSourceFiles",
            "strip_source_roots",
            vec![
                DependencyKey::new("SourceFiles"),
                DependencyKey::new("Snapshot").provided_params(vec!["DigestSubset"]),
                DependencyKey::new("SourceRootsResult").provided_params(vec!["SourceRootsRequest"]),
                DependencyKey::new("Snapshot").provided_params(vec!["RemovePrefix"]),
                DependencyKey::new("Digest").provided_params(vec!["DigestSubset"]),
                DependencyKey::new("Digest").provided_params(vec!["RemovePrefix"]),
                DependencyKey::new("Snapshot").provided_params(vec!["MergeDigests"]),
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
        Rule::new(
            "Process",
            "setup_pex_cli_process",
            vec![
                DependencyKey::new("PexCliProcess"),
                DependencyKey::new("ProcessResult").provided_params(vec!["Process"]),
            ],
        ),
        Rule::new(
            "ProcessResult",
            "fallible_to_exec_result_or_raise",
            vec![
                DependencyKey::new("FallibleProcessResult"),
                DependencyKey::new("ProductDescription"),
            ],
        ),
        Rule::new(
            "MultiPlatformProcess",
            "upcast_process",
            vec![DependencyKey::new("Process")],
        ),
        Rule::new(
            "ProductDescription",
            "get_multi_platform_request_description",
            vec![DependencyKey::new("MultiPlatformProcess")],
        ),
        Rule::new(
            "FallibleProcessResult",
            "remove_platform_information",
            vec![DependencyKey::new("MultiPlatformProcess")],
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
        Rule::new(
            "InferredDependencies",
            "infer_python_conftest_dependencies",
            vec![
                DependencyKey::new("InferConftestDependencies"),
                DependencyKey::new("HydratedSources")
                    .provided_params(vec!["HydrateSourcesRequest"]),
                DependencyKey::new("AncestorFiles").provided_params(vec!["AncestorFilesRequest"]),
                DependencyKey::new("Owners").provided_params(vec!["OwnersRequest"]),
            ],
        ),
        Rule::new(
            "ThirdPartyModuleToAddressMapping",
            "map_third_party_modules_to_addresses",
            vec![DependencyKey::new("Targets").provided_params(vec!["AddressSpecs"])],
        ),
        Rule::new(
            "Targets",
            "resolve_targets",
            vec![
                DependencyKey::new("UnexpandedTargets"),
                DependencyKey::new("Subtargets").provided_params(vec!["Address"]),
            ],
        ),
        Rule::new(
            "Owners",
            "find_owners",
            vec![
                DependencyKey::new("OwnersRequest"),
                DependencyKey::new("Targets").provided_params(vec!["AddressSpecs"]),
                DependencyKey::new("UnexpandedTargets").provided_params(vec!["AddressSpecs"]),
                DependencyKey::new("BuildFileAddress").provided_params(vec!["Address"]),
            ],
        ),
        Rule::new(
            "AddressesWithOrigins",
            "resolve_addresses_with_origins",
            vec![
                DependencyKey::new("Specs"),
                DependencyKey::new("AddressesWithOrigins").provided_params(vec!["AddressSpecs"]),
                DependencyKey::new("AddressesWithOrigins").provided_params(vec!["FilesystemSpecs"]),
            ],
        ),
        Rule::new(
            "InferredDependencies",
            "infer_python_dependencies",
            vec![
                DependencyKey::new("InferPythonDependencies"),
                DependencyKey::new("StrippedSourceFiles")
                    .provided_params(vec!["SourceFilesRequest"]),
                DependencyKey::for_known_rule(
                    RuleId::new("map_module_to_address"),
                    "PythonModuleOwner"
                )
                .provided_params(vec!["PythonModule"]),
            ],
        ),
        Rule::new(
            "InferredDependencies",
            "infer_python_init_dependencies",
            vec![
                DependencyKey::new("InferInitDependencies"),
                DependencyKey::new("HydratedSources")
                    .provided_params(vec!["HydrateSourcesRequest"]),
                DependencyKey::new("AncestorFiles").provided_params(vec!["AncestorFilesRequest"]),
                DependencyKey::new("Owners").provided_params(vec!["OwnersRequest"]),
            ],
        ),
        Rule::new(
            "PythonModuleOwner",
            "map_module_to_address",
            vec![
                DependencyKey::new("PythonModule"),
                DependencyKey::new("FirstPartyModuleToAddressMapping"),
                DependencyKey::new("ThirdPartyModuleToAddressMapping"),
            ],
        ),
        Rule::new(
            "DownloadedExternalTool",
            "download_external_tool",
            vec![
                DependencyKey::new("ExternalToolRequest"),
                DependencyKey::new("Digest").provided_params(vec!["DownloadFile"]),
                DependencyKey::new("ExtractedDigest").provided_params(vec!["MaybeExtractable"]),
            ],
        ),
        Rule::new(
            "GlobalOptions",
            "construct_scope_",
            vec![DependencyKey::new("ScopedOptions").provided_params(vec!["Scope"])],
        ),
        Rule::new(
            "PexEnvironment",
            "find_pex_python",
            vec![DependencyKey::new("BinaryPaths").provided_params(vec!["BinaryPathRequest"])],
        ),
        Rule::new(
            "ProcessResult",
            "fallible_to_exec_result_or_raise",
            vec![
                DependencyKey::new("FallibleProcessResult"),
                DependencyKey::new("ProductDescription"),
            ],
        ),
        Rule::new(
            "HydratedSources",
            "hydrate_sources",
            vec![
                DependencyKey::new("HydrateSourcesRequest"),
                DependencyKey::new("WrappedTarget").provided_params(vec!["Address"]),
                DependencyKey::new("GeneratedSources")
                    .provided_params(vec!["GeneratePythonFromProtobufRequest"],),
            ],
        ),
        Rule::new(
            "Digest",
            "merge_digests",
            vec![DependencyKey::new("MergeDigests")],
        ),
        Rule::new(
            "SourceFiles",
            "determine_source_files",
            vec![
                DependencyKey::new("SourceFilesRequest"),
                DependencyKey::new("HydratedSources")
                    .provided_params(vec!["HydrateSourcesRequest"]),
            ],
        ),
        Rule::new(
            "UnexpandedTargets",
            "resolve_unexpanded_targets",
            vec![
                DependencyKey::new("Addresses"),
                DependencyKey::new("WrappedTarget").provided_params(vec!["Address"]),
            ],
        ),
        Rule::new(
            "ExtractedDigest",
            "maybe_extract",
            vec![
                DependencyKey::new("MaybeExtractable"),
                DependencyKey::new("ProcessResult").provided_params(vec!["Process"]),
            ],
        ),
        Rule::new(
            "AddressesWithOrigins",
            "addresses_with_origins_from_address_specs",
            vec![
                DependencyKey::new("AddressSpecs"),
                DependencyKey::new("Address").provided_params(vec!["AddressInput"]),
                DependencyKey::new("TargetAdaptor").provided_params(vec!["Address"]),
                DependencyKey::new("UnexpandedTargets").provided_params(vec!["Addresses"]),
                DependencyKey::new("AddressFamily").provided_params(vec!["Dir"]),
            ],
        ),
        Rule::new(
            "BuildFileAddress",
            "find_build_file",
            vec![
                DependencyKey::new("Address"),
                DependencyKey::new("AddressFamily").provided_params(vec!["Dir"]),
            ],
        ),
        Rule::new(
            "AncestorFiles",
            "find_missing_ancestor_files",
            vec![DependencyKey::new("AncestorFilesRequest")],
        ),
        Rule::new(
            "Digest",
            "download_file",
            vec![DependencyKey::new("DownloadFile")],
        ),
        Rule::new(
            "BinaryPaths",
            "find_binary",
            vec![
                DependencyKey::new("BinaryPathRequest"),
                DependencyKey::new("FallibleProcessResult").provided_params(vec!["Process"]),
            ],
        ),
        Rule::new(
            "OptionalSourceRootsResult",
            "get_optional_source_roots",
            vec![
                DependencyKey::new("SourceRootsRequest"),
                DependencyKey::new("OptionalSourceRoot").provided_params(vec!["SourceRootRequest"]),
            ],
        ),
        Rule::new(
            "AddressesWithOrigins",
            "addresses_with_origins_from_filesystem_specs",
            vec![
                DependencyKey::new("FilesystemSpecs"),
                DependencyKey::new("Owners").provided_params(vec!["OwnersRequest"]),
            ],
        ),
        Rule::new(
            "RegisteredTargetTypes",
            "registered_target_types_singleton",
            vec![],
        ),
        Rule::new(
            "Addresses",
            "strip_address_origins",
            vec![DependencyKey::new("AddressesWithOrigins")],
        ),
        Rule::new(
            "FallibleProcessResult",
            "remove_platform_information",
            vec![DependencyKey::new("FallibleProcessResultWithPlatform")],
        ),
        Rule::new(
            "ScopedOptions",
            "scope_options",
            vec![DependencyKey::new("Scope"), DependencyKey::new("_Options"),],
        ),
        Rule::new(
            "TransitiveTargets",
            "transitive_targets",
            vec![
                DependencyKey::new("Targets"),
                DependencyKey::new("Targets").provided_params(vec!["DependenciesRequest"]),
            ],
        ),
        Rule::new(
            "FirstPartyModuleToAddressMapping",
            "map_first_party_modules_to_addresses",
            vec![
                DependencyKey::new("Targets").provided_params(vec!["AddressSpecs"]),
                DependencyKey::new("StrippedSourceFiles")
                    .provided_params(vec!["SourceFilesRequest"]),
            ],
        ),
        Rule::new(
            "Digest",
            "digest_subset",
            vec![DependencyKey::new("DigestSubset")],
        ),
        Rule::new(
            "_Options",
            "parse_options",
            vec![DependencyKey::new("OptionsBootstrapper")],
        ),
        Rule::new(
            "GeneratedSources",
            "generate_python_from_protobuf",
            vec![
                DependencyKey::new("GeneratePythonFromProtobufRequest"),
                DependencyKey::new("DownloadedExternalTool")
                    .provided_params(vec!["ExternalToolRequest"]),
                DependencyKey::new("ProcessResult").provided_params(vec!["Process"]),
                DependencyKey::new("TransitiveTargets").provided_params(vec!["Addresses"]),
                DependencyKey::new("StrippedSourceFiles")
                    .provided_params(vec!["SourceFilesRequest"]),
                DependencyKey::new("Digest").provided_params(vec!["MergeDigests"]),
                DependencyKey::new("SourceRoot").provided_params(vec!["SourceRootRequest"]),
            ],
        ),
        Rule::new(
            "SourceRoot",
            "get_source_root",
            vec![
                DependencyKey::new("SourceRootRequest"),
                DependencyKey::new("OptionalSourceRoot").provided_params(vec!["SourceRootRequest"]),
            ],
        ),
        Rule::new(
            "MultiPlatformProcess",
            "upcast_process",
            vec![DependencyKey::new("Process")],
        ),
        Rule::new(
            "TargetAdaptor",
            "find_target_adaptor",
            vec![
                DependencyKey::new("Address"),
                DependencyKey::new("AddressFamily").provided_params(vec!["Dir"]),
            ],
        ),
        Rule::new(
            "Address",
            "resolve_address",
            vec![DependencyKey::new("AddressInput")],
        ),
        Rule::new(
            "FallibleProcessResultWithPlatform",
            "run_multiplaform_process",
            vec![DependencyKey::new("MultiPlatformProcess")],
        ),
        Rule::new(
            "SourceRootsResult",
            "get_source_roots",
            vec![
                DependencyKey::new("SourceRootsRequest"),
                DependencyKey::new("OptionalSourceRootsResult")
                    .provided_params(vec!["SourceRootsRequest"]),
            ],
        ),
        Rule::new(
            "OptionalSourceRoot",
            "get_optional_source_root",
            vec![
                DependencyKey::new("SourceRootRequest"),
                DependencyKey::new("OptionalSourceRoot").provided_params(vec!["SourceRootRequest"]),
            ],
        ),
        Rule::new(
            "StrippedSourceFiles",
            "strip_source_roots",
            vec![
                DependencyKey::new("SourceFiles"),
                DependencyKey::new("SourceRootsResult").provided_params(vec!["SourceRootsRequest"]),
                DependencyKey::new("Digest").provided_params(vec!["DigestSubset"]),
            ],
        ),
        Rule::new(
            "Subtargets",
            "generate_subtargets",
            vec![
                DependencyKey::new("Address"),
                DependencyKey::new("WrappedTarget").provided_params(vec!["Address"]),
            ],
        ),
        Rule::new(
            "ProductDescription",
            "get_multi_platform_request_description",
            vec![DependencyKey::new("MultiPlatformProcess")],
        ),
        Rule::new(
            "Addresses",
            "resolve_dependencies",
            vec![
                DependencyKey::new("DependenciesRequest"),
                DependencyKey::new("RegisteredTargetTypes"),
                DependencyKey::new("Address").provided_params(vec!["AddressInput"]),
                DependencyKey::new("WrappedTarget").provided_params(vec!["Address"]),
                DependencyKey::new("InferredDependencies")
                    .provided_params(vec!["InferPythonDependencies"]),
                DependencyKey::new("InferredDependencies")
                    .provided_params(vec!["InferInitDependencies"]),
                DependencyKey::new("InferredDependencies")
                    .provided_params(vec!["InferConftestDependencies"]),
                DependencyKey::new("Subtargets").provided_params(vec!["Address"]),
            ],
        ),
        Rule::new(
            "WrappedTarget",
            "resolve_target",
            vec![
                DependencyKey::new("Address"),
                DependencyKey::new("RegisteredTargetTypes"),
                DependencyKey::new("WrappedTarget").provided_params(vec!["Address"]),
                DependencyKey::new("TargetAdaptor").provided_params(vec!["Address"]),
            ],
        ),
        Rule::new(
            "AddressFamily",
            "parse_address_family",
            vec![
                DependencyKey::new("GlobalOptions"),
                DependencyKey::new("Dir"),
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

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct Rule {
    id: RuleId,
    product: &'static str,
    name: &'static str,
    dependency_keys: Vec<DependencyKey<&'static str>>,
    masked_params: Vec<&'static str>,
}

impl Rule {
    fn new(
        product: &'static str,
        name: &'static str,
        dependency_keys: Vec<DependencyKey<&'static str>>,
    ) -> Self {
        Self {
            id: RuleId::new(name),
            product,
            name,
            dependency_keys,
            masked_params: vec![],
        }
    }

    fn masked_params(mut self, masked_params: Vec<&'static str>) -> Self {
        self.masked_params = masked_params;
        self
    }
}

impl super::Rule for Rule {
    type TypeId = &'static str;

    fn id(&self) -> &RuleId {
        &self.id
    }

    fn product(&self) -> Self::TypeId {
        self.product
    }

    fn dependency_keys(&self) -> Vec<&DependencyKey<Self::TypeId>> {
        self.dependency_keys.iter().collect()
    }

    fn masked_params(&self) -> Vec<Self::TypeId> {
        self.masked_params.clone()
    }

    fn require_reachable(&self) -> bool {
        !self.name.ends_with("_unreachable")
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
        write!(
            f,
            "{}({}) -> {}",
            self.name,
            self.dependency_keys.len(),
            self.product
        )
    }
}
