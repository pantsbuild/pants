use std::fmt;

use indexmap::{indexset, IndexSet};

use crate::builder::combinations_of_one;
use crate::{DependencyKey, Palette, Query, RuleGraph};

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
  let rules = indexset![Rule("a", "a_from_b", vec![DependencyKey::new("b")])];
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
  let rules = indexset![Rule("a", "a_from_b", vec![DependencyKey::new("b")])];
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
    Rule("a", "a_from_b", vec![DependencyKey::new("b")]),
    Rule("a", "a_from_c", vec![DependencyKey::new("c")]),
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
    Rule(
      "a",
      "a_from_b",
      vec![DependencyKey::new_with_params("b", vec!["c"])]
    ),
    Rule(
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
    Rule(
      "a",
      "a_from_b",
      vec![DependencyKey::new_with_params("b", vec!["c"])]
    ),
    Rule(
      "b",
      "b_from_c",
      vec![DependencyKey::new("c"), DependencyKey::new("d")],
    ),
    Rule(
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
  let rules = indexset![Rule(
    "Fib",
    "fib",
    vec![
      DependencyKey::new("int"),
      DependencyKey::new_with_params("Fib", vec!["int"]),
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
        DependencyKey::new("int"),
        // We expect this to be a self-cycle.
        DependencyKey::new_with_params("Thing", vec!["int"]),
        // And this to be satisfied by the second rule, even though we already have an int in scope.
        DependencyKey::new_with_params("int", vec!["ExternalDep"]),
      ],
    ),
    Rule(
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
fn ambiguous_cycle() {
  let _logger = env_logger::try_init();
  let rules = indexset![
    Rule(
      "Root",
      "me",
      vec![
        DependencyKey::new_with_params("ME", vec!["P"]),
        DependencyKey::new_with_params("ME", vec!["MPP"]),
      ],
    ),
    Rule("ME", "me", vec![DependencyKey::new("FERR")]),
    Rule(
      "FERR",
      "ferr",
      vec![DependencyKey::new("PD"), DependencyKey::new("FPR")],
    ),
    Rule("PD", "pd_for_p", vec![DependencyKey::new("P")]),
    Rule("PD", "pd_for_mpp", vec![DependencyKey::new("MPP")]),
    Rule("FPR", "fpr_for_p", vec![DependencyKey::new("P")]),
    Rule("FPR", "fpr_for_mpp", vec![DependencyKey::new("MPP")]),
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
      vec![
        DependencyKey::new("D"),
        DependencyKey::new_with_params("B", vec!["E"])
      ],
    ),
    Rule(
      "B",
      "b",
      vec![
        DependencyKey::new("E"),
        DependencyKey::new_with_params("C", vec!["F"])
      ],
    ),
    Rule(
      "C",
      "c",
      vec![
        DependencyKey::new("F"),
        DependencyKey::new_with_params("A", vec!["D"])
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
    Rule(
      "A",
      "sao",
      vec![
        DependencyKey::new_with_params("AWO", vec!["AS"]),
        DependencyKey::new_with_params("AWO", vec!["FS"]),
      ],
    ),
    Rule("AWO", "awofs", vec![DependencyKey::new("FS")]),
    Rule(
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
    Rule(
      "IsEven",
      "is_even",
      vec![
        DependencyKey::new("int"),
        DependencyKey::new_with_params("IsOdd", vec!["int"]),
      ],
    ),
    Rule(
      "IsOdd",
      "is_odd",
      vec![
        DependencyKey::new("int"),
        DependencyKey::new_with_params("IsEven", vec!["int"]),
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
    Rule(
      "Output",
      "one",
      vec![DependencyKey::new_with_params("Output", vec!["A"])]
    ),
    Rule(
      "Output",
      "two",
      vec![
        DependencyKey::new("A"),
        DependencyKey::new_with_params("Output", vec!["B"])
      ],
    ),
    Rule(
      "Output",
      "three",
      vec![
        DependencyKey::new("B"),
        DependencyKey::new_with_params("Output", vec!["C"])
      ],
    ),
    Rule(
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
    Rule("SourceRootConfig", "construct_scope_source", vec![]),
    Rule(
      "OptionalSourceRootsResult",
      "get_optional_source_roots",
      vec![
        DependencyKey::new("SourceRootsRequest"),
        DependencyKey::new_with_params("OptionalSourceRoot", vec!["SourceRootRequest"]),
      ],
    ),
    Rule(
      "Digest",
      "<intrinsic>",
      vec![DependencyKey::new("RemovePrefix")],
    ),
    Rule(
      "Snapshot",
      "<intrinsic>",
      vec![DependencyKey::new("Digest")],
    ),
    Rule(
      "Digest",
      "<intrinsic>",
      vec![DependencyKey::new("DigestSubset")],
    ),
    Rule(
      "Digest",
      "<intrinsic>",
      vec![DependencyKey::new("PathGlobs")],
    ),
    Rule(
      "Digest",
      "<intrinsic>",
      vec![DependencyKey::new("MergeDigests")],
    ),
    Rule(
      "SourceRootsResult",
      "get_source_roots",
      vec![
        DependencyKey::new("SourceRootsRequest"),
        DependencyKey::new_with_params("OptionalSourceRootsResult", vec!["SourceRootsRequest"]),
      ],
    ),
    Rule(
      "OptionalSourceRoot",
      "get_optional_source_root",
      vec![
        DependencyKey::new("SourceRootRequest"),
        DependencyKey::new("SourceRootConfig"),
        DependencyKey::new_with_params("Snapshot", vec!["PathGlobs"]),
        DependencyKey::new_with_params("OptionalSourceRoot", vec!["SourceRootRequest"]),
      ],
    ),
    Rule(
      "StrippedSourceFiles",
      "strip_source_roots",
      vec![
        DependencyKey::new("SourceFiles"),
        DependencyKey::new_with_params("Snapshot", vec!["DigestSubset"]),
        DependencyKey::new_with_params("SourceRootsResult", vec!["SourceRootsRequest"]),
        DependencyKey::new_with_params("Snapshot", vec!["RemovePrefix"]),
        DependencyKey::new_with_params("Digest", vec!["DigestSubset"]),
        DependencyKey::new_with_params("Digest", vec!["RemovePrefix"]),
        DependencyKey::new_with_params("Snapshot", vec!["MergeDigests"]),
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
        DependencyKey::new("PexCliProcess"),
        DependencyKey::new_with_params("ProcessResult", vec!["Process"]),
      ],
    ),
    Rule(
      "ProcessResult",
      "fallible_to_exec_result_or_raise",
      vec![
        DependencyKey::new("FallibleProcessResult"),
        DependencyKey::new("ProductDescription"),
      ],
    ),
    Rule(
      "MultiPlatformProcess",
      "upcast_process",
      vec![DependencyKey::new("Process")],
    ),
    Rule(
      "ProductDescription",
      "get_multi_platform_request_description",
      vec![DependencyKey::new("MultiPlatformProcess")],
    ),
    Rule(
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
    Rule(
      "InferredDependencies",
      "infer_python_conftest_dependencies",
      vec![
        DependencyKey::new("InferConftestDependencies"),
        DependencyKey::new_with_params("HydratedSources", vec!["HydrateSourcesRequest"]),
        DependencyKey::new_with_params("AncestorFiles", vec!["AncestorFilesRequest"]),
        DependencyKey::new_with_params("Owners", vec!["OwnersRequest"]),
      ],
    ),
    Rule(
      "ThirdPartyModuleToAddressMapping",
      "map_third_party_modules_to_addresses",
      vec![DependencyKey::new_with_params(
        "Targets",
        vec!["AddressSpecs"]
      )],
    ),
    Rule(
      "Targets",
      "resolve_targets",
      vec![
        DependencyKey::new("UnexpandedTargets"),
        DependencyKey::new_with_params("Subtargets", vec!["Address"]),
      ],
    ),
    Rule(
      "Owners",
      "find_owners",
      vec![
        DependencyKey::new("OwnersRequest"),
        DependencyKey::new_with_params("Targets", vec!["AddressSpecs"]),
        DependencyKey::new_with_params("UnexpandedTargets", vec!["AddressSpecs"]),
        DependencyKey::new_with_params("BuildFileAddress", vec!["Address"]),
      ],
    ),
    Rule(
      "AddressesWithOrigins",
      "resolve_addresses_with_origins",
      vec![
        DependencyKey::new("Specs"),
        DependencyKey::new_with_params("AddressesWithOrigins", vec!["AddressSpecs"]),
        DependencyKey::new_with_params("AddressesWithOrigins", vec!["FilesystemSpecs"]),
      ],
    ),
    Rule(
      "InferredDependencies",
      "infer_python_dependencies",
      vec![
        DependencyKey::new("InferPythonDependencies"),
        DependencyKey::new_with_params("StrippedSourceFiles", vec!["SourceFilesRequest"]),
        DependencyKey::new_with_params("PythonModuleOwner", vec!["PythonModule"]),
      ],
    ),
    Rule(
      "InferredDependencies",
      "infer_python_init_dependencies",
      vec![
        DependencyKey::new("InferInitDependencies"),
        DependencyKey::new_with_params("HydratedSources", vec!["HydrateSourcesRequest"]),
        DependencyKey::new_with_params("AncestorFiles", vec!["AncestorFilesRequest"]),
        DependencyKey::new_with_params("Owners", vec!["OwnersRequest"]),
      ],
    ),
    Rule(
      "PythonModuleOwner",
      "map_module_to_address",
      vec![
        DependencyKey::new("PythonModule"),
        DependencyKey::new("FirstPartyModuleToAddressMapping"),
        DependencyKey::new("ThirdPartyModuleToAddressMapping"),
      ],
    ),
    Rule(
      "DownloadedExternalTool",
      "download_external_tool",
      vec![
        DependencyKey::new("ExternalToolRequest"),
        DependencyKey::new_with_params("Digest", vec!["DownloadFile"]),
        DependencyKey::new_with_params("ExtractedDigest", vec!["MaybeExtractable"]),
      ],
    ),
    Rule(
      "GlobalOptions",
      "construct_scope_",
      vec![DependencyKey::new_with_params(
        "ScopedOptions",
        vec!["Scope"]
      )],
    ),
    Rule(
      "PexEnvironment",
      "find_pex_python",
      vec![DependencyKey::new_with_params(
        "BinaryPaths",
        vec!["BinaryPathRequest"]
      )],
    ),
    Rule(
      "ProcessResult",
      "fallible_to_exec_result_or_raise",
      vec![
        DependencyKey::new("FallibleProcessResult"),
        DependencyKey::new("ProductDescription"),
      ],
    ),
    Rule(
      "HydratedSources",
      "hydrate_sources",
      vec![
        DependencyKey::new("HydrateSourcesRequest"),
        DependencyKey::new_with_params("WrappedTarget", vec!["Address"]),
        DependencyKey::new_with_params(
          "GeneratedSources",
          vec!["GeneratePythonFromProtobufRequest"],
        ),
      ],
    ),
    Rule(
      "Digest",
      "<intrinsic>",
      vec![DependencyKey::new("MergeDigests")],
    ),
    Rule(
      "SourceFiles",
      "determine_source_files",
      vec![
        DependencyKey::new("SourceFilesRequest"),
        DependencyKey::new_with_params("HydratedSources", vec!["HydrateSourcesRequest"]),
      ],
    ),
    Rule(
      "UnexpandedTargets",
      "resolve_unexpanded_targets",
      vec![
        DependencyKey::new("Addresses"),
        DependencyKey::new_with_params("WrappedTarget", vec!["Address"]),
      ],
    ),
    Rule(
      "ExtractedDigest",
      "maybe_extract",
      vec![
        DependencyKey::new("MaybeExtractable"),
        DependencyKey::new_with_params("ProcessResult", vec!["Process"]),
      ],
    ),
    Rule(
      "AddressesWithOrigins",
      "addresses_with_origins_from_address_specs",
      vec![
        DependencyKey::new("AddressSpecs"),
        DependencyKey::new_with_params("Address", vec!["AddressInput"]),
        DependencyKey::new_with_params("TargetAdaptor", vec!["Address"]),
        DependencyKey::new_with_params("UnexpandedTargets", vec!["Addresses"]),
        DependencyKey::new_with_params("AddressFamily", vec!["Dir"]),
      ],
    ),
    Rule(
      "BuildFileAddress",
      "find_build_file",
      vec![
        DependencyKey::new("Address"),
        DependencyKey::new_with_params("AddressFamily", vec!["Dir"]),
      ],
    ),
    Rule(
      "AncestorFiles",
      "find_missing_ancestor_files",
      vec![DependencyKey::new("AncestorFilesRequest")],
    ),
    Rule(
      "Digest",
      "<intrinsic>",
      vec![DependencyKey::new("DownloadFile")],
    ),
    Rule(
      "BinaryPaths",
      "find_binary",
      vec![
        DependencyKey::new("BinaryPathRequest"),
        DependencyKey::new_with_params("FallibleProcessResult", vec!["Process"]),
      ],
    ),
    Rule(
      "OptionalSourceRootsResult",
      "get_optional_source_roots",
      vec![
        DependencyKey::new("SourceRootsRequest"),
        DependencyKey::new_with_params("OptionalSourceRoot", vec!["SourceRootRequest"]),
      ],
    ),
    Rule(
      "AddressesWithOrigins",
      "addresses_with_origins_from_filesystem_specs",
      vec![
        DependencyKey::new("FilesystemSpecs"),
        DependencyKey::new_with_params("Owners", vec!["OwnersRequest"]),
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
      vec![DependencyKey::new("AddressesWithOrigins")],
    ),
    Rule(
      "FallibleProcessResult",
      "remove_platform_information",
      vec![DependencyKey::new("FallibleProcessResultWithPlatform")],
    ),
    Rule(
      "ScopedOptions",
      "scope_options",
      vec![DependencyKey::new("Scope"), DependencyKey::new("_Options"),],
    ),
    Rule(
      "TransitiveTargets",
      "transitive_targets",
      vec![
        DependencyKey::new("Targets"),
        DependencyKey::new_with_params("Targets", vec!["DependenciesRequest"]),
      ],
    ),
    Rule(
      "FirstPartyModuleToAddressMapping",
      "map_first_party_modules_to_addresses",
      vec![
        DependencyKey::new_with_params("Targets", vec!["AddressSpecs"]),
        DependencyKey::new_with_params("StrippedSourceFiles", vec!["SourceFilesRequest"]),
      ],
    ),
    Rule(
      "Digest",
      "<intrinsic>",
      vec![DependencyKey::new("DigestSubset")],
    ),
    Rule(
      "_Options",
      "parse_options",
      vec![DependencyKey::new("OptionsBootstrapper")],
    ),
    Rule(
      "GeneratedSources",
      "generate_python_from_protobuf",
      vec![
        DependencyKey::new("GeneratePythonFromProtobufRequest"),
        DependencyKey::new_with_params("DownloadedExternalTool", vec!["ExternalToolRequest"]),
        DependencyKey::new_with_params("ProcessResult", vec!["Process"]),
        DependencyKey::new_with_params("TransitiveTargets", vec!["Addresses"]),
        DependencyKey::new_with_params("StrippedSourceFiles", vec!["SourceFilesRequest"]),
        DependencyKey::new_with_params("Digest", vec!["MergeDigests"]),
        DependencyKey::new_with_params("SourceRoot", vec!["SourceRootRequest"]),
      ],
    ),
    Rule(
      "SourceRoot",
      "get_source_root",
      vec![
        DependencyKey::new("SourceRootRequest"),
        DependencyKey::new_with_params("OptionalSourceRoot", vec!["SourceRootRequest"]),
      ],
    ),
    Rule(
      "MultiPlatformProcess",
      "upcast_process",
      vec![DependencyKey::new("Process")],
    ),
    Rule(
      "TargetAdaptor",
      "find_target_adaptor",
      vec![
        DependencyKey::new("Address"),
        DependencyKey::new_with_params("AddressFamily", vec!["Dir"]),
      ],
    ),
    Rule(
      "Address",
      "resolve_address",
      vec![DependencyKey::new("AddressInput")],
    ),
    Rule(
      "FallibleProcessResultWithPlatform",
      "<intrinsic>",
      vec![DependencyKey::new("MultiPlatformProcess")],
    ),
    Rule(
      "SourceRootsResult",
      "get_source_roots",
      vec![
        DependencyKey::new("SourceRootsRequest"),
        DependencyKey::new_with_params("OptionalSourceRootsResult", vec!["SourceRootsRequest"]),
      ],
    ),
    Rule(
      "OptionalSourceRoot",
      "get_optional_source_root",
      vec![
        DependencyKey::new("SourceRootRequest"),
        DependencyKey::new_with_params("OptionalSourceRoot", vec!["SourceRootRequest"]),
      ],
    ),
    Rule(
      "StrippedSourceFiles",
      "strip_source_roots",
      vec![
        DependencyKey::new("SourceFiles"),
        DependencyKey::new_with_params("SourceRootsResult", vec!["SourceRootsRequest"]),
        DependencyKey::new_with_params("Digest", vec!["DigestSubset"]),
      ],
    ),
    Rule(
      "Subtargets",
      "generate_subtargets",
      vec![
        DependencyKey::new("Address"),
        DependencyKey::new_with_params("WrappedTarget", vec!["Address"]),
      ],
    ),
    Rule(
      "ProductDescription",
      "get_multi_platform_request_description",
      vec![DependencyKey::new("MultiPlatformProcess")],
    ),
    Rule(
      "Addresses",
      "resolve_dependencies",
      vec![
        DependencyKey::new("DependenciesRequest"),
        DependencyKey::new("RegisteredTargetTypes"),
        DependencyKey::new_with_params("Address", vec!["AddressInput"]),
        DependencyKey::new_with_params("WrappedTarget", vec!["Address"]),
        DependencyKey::new_with_params("InferredDependencies", vec!["InferPythonDependencies"]),
        DependencyKey::new_with_params("InferredDependencies", vec!["InferInitDependencies"]),
        DependencyKey::new_with_params("InferredDependencies", vec!["InferConftestDependencies"]),
        DependencyKey::new_with_params("Subtargets", vec!["Address"]),
      ],
    ),
    Rule(
      "WrappedTarget",
      "resolve_target",
      vec![
        DependencyKey::new("Address"),
        DependencyKey::new("RegisteredTargetTypes"),
        DependencyKey::new_with_params("WrappedTarget", vec!["Address"]),
        DependencyKey::new_with_params("TargetAdaptor", vec!["Address"]),
      ],
    ),
    Rule(
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

// A name and vec of DependencyKeys. Abbreviated for simpler construction and matching.
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct Rule(&'static str, &'static str, Vec<DependencyKey<&'static str>>);

impl super::Rule for Rule {
  type TypeId = &'static str;

  fn product(&self) -> Self::TypeId {
    self.0
  }

  fn dependency_keys(&self) -> Vec<&DependencyKey<&'static str>> {
    self.2.iter().collect()
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
