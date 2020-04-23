use crate::{Palette, RuleGraph};
use std::fmt;

#[test]
fn create_and_validate_valid() {
  let rules = vec![("a", vec![Rule("a_from_b", vec![DependencyKey("b", None)])])]
    .into_iter()
    .collect();
  let roots = vec!["b"];
  let graph = RuleGraph::new(&rules, roots);

  graph.validate().unwrap();
}

#[test]
fn create_and_validate_no_root() {
  let rules = vec![("a", vec![Rule("a_from_b", vec![DependencyKey("b", None)])])]
    .into_iter()
    .collect();
  let roots = vec![];
  let graph = RuleGraph::new(&rules, roots);

  assert!(graph
    .validate()
    .err()
    .unwrap()
    .contains("No rules can compute DependencyKey(\"b\", None)."));
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
  fn fmt_for_graph(&self) -> String {
    "???".to_string()
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
