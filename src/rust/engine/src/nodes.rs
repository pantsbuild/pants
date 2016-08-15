use std::collections::HashMap;

use core::{Key, TypeId, Variants};
use selectors;
use selectors::Selector;

// TODO: coroutines as iterators probably.
pub type Step = bool;

#[derive(Debug, Eq, Hash, PartialEq)]
pub struct Runnable {
  func: Key,
  args: Vec<Key>,
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub enum State {
  Waiting {
    dependencies: Vec<Node>,
  },
  Noop {
    msg: Key,
  },
  Return {
    value: Key,
  },
  Throw {
    exc: Key,
  },
  Runnable(Runnable),
}

#[derive(Debug, Eq, Hash, PartialEq)]
struct Select {
  subject: Key,
  variants: Variants,
  selector: selectors::Select,
}

#[derive(Debug, Eq, Hash, PartialEq)]
struct SelectLiteral {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectLiteral,
}

#[derive(Debug, Eq, Hash, PartialEq)]
struct SelectVariant {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectVariant,
}

#[derive(Debug, Eq, Hash, PartialEq)]
struct SelectDependencies {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectDependencies,
}

#[derive(Debug, Eq, Hash, PartialEq)]
struct SelectProjection {
  subject: Key,
  variants: Variants,
  selector: selectors::SelectProjection,
}

#[derive(Debug, Eq, Hash, PartialEq)]
struct Task {
  subject: Key,
  product: TypeId,
  variants: Variants,
  func: Key,
  clause: Vec<selectors::Selector>,
}

#[derive(Debug, Eq, Hash, PartialEq)]
struct Filesystem {
  subject: Key,
  product: TypeId,
  variants: Variants,
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub enum Node {
  Select(Select),
  SelectLiteral(SelectLiteral),
  SelectVariant(SelectVariant),
  SelectDependencies(SelectDependencies),
  SelectProjection(SelectProjection),
  Task(Task),
  Filesystem(Filesystem),
}

pub impl Node {
  pub fn create(selector: Selector, subject: Key, variants: Variants) -> Node {
    match selector {
      Selector::Select(s) =>
        Node::Select(Select {
          subject: subject,
          variants: variants,
          selector: s,
        }),
      Selector::SelectVariant(s) =>
        Node::SelectVariant(SelectVariant {
          subject: subject,
          variants: variants,
          selector: s,
        }),
      Selector::SelectLiteral(s) =>
        // Intentionally ignores subject parameter to provide a literal subject.
        Node::SelectLiteral(SelectLiteral {
          subject: s.subject,
          variants: variants,
          selector: s,
        }),
      Selector::SelectDependencies(s) =>
        Node::SelectDependencies(SelectDependencies {
          subject: subject,
          variants: variants,
          selector: s,
        }),
      Selector::SelectProjection(s) =>
        Node::SelectProjection(SelectProjection {
          subject: subject,
          variants: variants,
          selector: s,
        }),
    }
  }
}
