use crate::builder::combinations_of_one;
use crate::{Palette, Query, RuleGraph};
use std::fmt;

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
  let rules = vec![Rule("a", "a_from_b", vec![DependencyKey("b", None)])];
  let queries = vec![Query::new("a", vec!["b"])];
  let graph = RuleGraph::new(rules, queries).unwrap();

  graph.validate_reachability().unwrap();
  graph.find_root_edges(vec!["b"], "a").unwrap();
}

#[test]
fn singleton() {
  let rules = vec![Rule("a", "a_singleton", vec![])];
  let queries = vec![Query::new("a", vec![])];
  let graph = RuleGraph::new(rules, queries).unwrap();

  graph.validate_reachability().unwrap();
  graph.find_root_edges(vec![""], "a").unwrap();
}

#[test]
fn insufficient_query() {
  let rules = vec![Rule("a", "a_from_b", vec![DependencyKey("b", None)])];
  let queries = vec![Query::new("a", vec![])];

  assert!(RuleGraph::new(rules, queries)
    .err()
    .unwrap()
    .contains("No installed rules return the type b"));
}

#[test]
fn ambiguity() {
  let rules = vec![
    Rule("a", "a_from_b", vec![DependencyKey("b", None)]),
    Rule("a", "a_from_c", vec![DependencyKey("c", None)]),
  ];
  let queries = vec![Query::new("a", vec!["b", "c"])];

  assert!(RuleGraph::new(rules, queries)
    .err()
    .unwrap()
    .contains("Encountered 1 rule graph error:\n  Too many"));
}

#[test]
fn nested_basic() {
  let rules = vec![
    Rule("a", "a_from_b", vec![DependencyKey("b", Some("c"))]),
    Rule(
      "b",
      "b_from_c",
      vec![DependencyKey("c", None), DependencyKey("d", None)],
    ),
  ];
  let queries = vec![Query::new("a", vec!["d"])];
  let graph = RuleGraph::new(rules, queries).unwrap();

  graph.validate_reachability().unwrap();
  graph.find_root_edges(vec!["d"], "a").unwrap();
}

#[test]
fn nested_multiple() {
  let rules = vec![
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
  let queries = vec![Query::new("a", vec!["d"])];
  let graph = RuleGraph::new(rules, queries).unwrap();

  graph.validate_reachability().unwrap();
  graph.find_root_edges(vec!["d"], "a").unwrap();
}

#[test]
fn self_cycle_simple() {
  let rules = vec![Rule(
    "Fib",
    "fib",
    vec![
      DependencyKey("int", None),
      DependencyKey("Fib", Some("int")),
    ],
  )];
  let queries = vec![
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
  let rules = vec![
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
  let queries = vec![Query::new("Thing", vec!["int"])];
  let graph = RuleGraph::new(rules, queries).unwrap();

  graph.validate_reachability().unwrap();
  graph.find_root_edges(vec!["int"], "Thing").unwrap();
}

#[test]
fn ambiguous_cycle() {
  let _logger = env_logger::try_init();
  let rules = vec![
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
  let queries = vec![Query::new("Root", vec![])];
  let graph = RuleGraph::new(rules, queries).unwrap();

  graph.validate_reachability().unwrap();
  graph.find_root_edges(vec![], "Root").unwrap();
}

#[test]
fn natural_loop() {
  let rules = vec![
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
  let queries = vec![Query::new("A", vec!["D"])];
  let graph = RuleGraph::new(rules, queries).unwrap();

  graph.validate_reachability().unwrap();
  graph.find_root_edges(vec!["D"], "A").unwrap();
}

/// TODO: Possibly related to https://github.com/pantsbuild/pants/issues/10683.
#[ignore]
#[test]
fn wide_cycle() {
  let _logger = env_logger::try_init();
  let rules = vec![
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
  let queries = vec![Query::new("A", vec![])];
  let graph = RuleGraph::new(rules, queries).unwrap();

  graph.validate_reachability().unwrap();
  graph.find_root_edges(vec![], "A").unwrap();
}

#[test]
fn mutual_recursion() {
  let rules = vec![
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
  let queries = vec![
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
  let rules = vec![
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
  let queries = vec![Query::new("Output", vec!["D"])];
  let graph = RuleGraph::new(rules, queries).unwrap();

  graph.validate_reachability().unwrap();
  graph.find_root_edges(vec!["D"], "Output").unwrap();
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
    write!(f, "{:?}", self)
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
