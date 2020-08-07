use crate::{Palette, RuleGraph};
use std::fmt;

use crate::builder::Powerset;

#[test]
fn valid() {
  let rules = vec![("a", vec![Rule("a_from_b", vec![DependencyKey("b", None)])])]
    .into_iter()
    .collect();
  let roots = vec!["b"];
  let graph = RuleGraph::new(&rules, roots);

  graph.validate().unwrap();
}

#[test]
fn singleton() {
  let rules = vec![("a", vec![Rule("a_singleton", vec![])])]
    .into_iter()
    .collect();
  let roots = vec!["b"];
  let graph = RuleGraph::new(&rules, roots);

  graph.validate().unwrap();
}

#[test]
fn no_root() {
  let rules = vec![("a", vec![Rule("a_from_b", vec![DependencyKey("b", None)])])]
    .into_iter()
    .collect();
  let roots = vec![];
  let graph = RuleGraph::new(&rules, roots);

  assert!(graph
    .validate()
    .err()
    .unwrap()
    .contains("No rule was able to compute DependencyKey(\"b\", None)."));
}

#[test]
fn self_cycle_simple() {
  let _logger = env_logger::try_init();
  let rules = vec![(
    "Fib",
    vec![Rule(
      "fib",
      vec![
        DependencyKey("int", None),
        DependencyKey("Fib", Some("int")),
      ],
    )],
  )]
  .into_iter()
  .collect();
  let roots = vec!["Fib", "int", "nonsense"];
  let graph = RuleGraph::new(&rules, roots);

  graph.validate().unwrap();
  graph.find_root_edges(vec!["int"], "Fib").unwrap();
  graph.find_root_edges(vec!["Fib"], "Fib").unwrap();
}

#[test]
fn self_cycle_with_external_dep() {
  let rules = vec![
    (
      "Thing",
      vec![Rule(
        "transitive_thing",
        vec![
          DependencyKey("int", None),
          // We expect this to be a self-cycle.
          DependencyKey("Thing", Some("int")),
          // And this to be satisfied by the second rule, even though we already have an int in scope.
          DependencyKey("int", Some("ExternalDep")),
        ],
      )],
    ),
    (
      "int",
      vec![Rule(
        "external_dep",
        vec![DependencyKey("ExternalDep", None)],
      )],
    ),
  ]
  .into_iter()
  .collect();
  let roots = vec!["int"];
  let graph = RuleGraph::new(&rules, roots);

  graph.validate().unwrap();
  graph.find_root_edges(vec!["int"], "Thing").unwrap();
}

#[test]
fn powerset_by_size() {
  assert_eq!(vec![0], Powerset::new(0).collect::<Vec<_>>());
  assert_eq!(vec![0, 1], Powerset::new(1).collect::<Vec<_>>());

  // And that they are in ascending order by size (ie popcount).
  let set_size = 8;
  let powerset_size = 2_i64.pow(set_size as u32);
  let mut powerset = Powerset::new(set_size).collect::<Vec<_>>();
  assert_eq!(powerset_size, powerset.len() as i64);
  let mut prev_popcount = 0;
  for x in &powerset {
    assert!(prev_popcount <= x.count_ones());
    prev_popcount = x.count_ones();
  }
  // And that all of the integers are present exactly once.
  powerset.sort();
  assert_eq!(
    (0i64..(powerset_size as i64))
      .into_iter()
      .collect::<Vec<_>>(),
    powerset
  );
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
struct Rule(&'static str, Vec<DependencyKey>);

impl super::Rule for Rule {
  type TypeId = &'static str;
  type DependencyKey = DependencyKey;

  fn dependency_keys(&self) -> Vec<Self::DependencyKey> {
    self.1.clone()
  }

  fn require_reachable(&self) -> bool {
    true
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
#[derive(Copy, Clone, Debug, Eq, Hash, PartialEq)]
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
