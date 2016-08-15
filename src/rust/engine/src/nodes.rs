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
pub enum Node {
  Select {
    subject: Key,
    variants: Variants,
    selector: selectors::Select,
  },
  SelectLiteral {
    subject: Key,
    variants: Variants,
    selector: selectors::SelectLiteral,
  },
  SelectVariant {
    subject: Key,
    variants: Variants,
    selector: selectors::SelectVariant,
  },
  Dependencies {
    subject: Key,
    variants: Variants,
    selector: selectors::SelectDependencies,
  },
  Projection {
    subject: Key,
    variants: Variants,
    selector: selectors::SelectProjection,
  },
  Task {
    subject: Key,
    product: TypeId,
    variants: Variants,
    func: Key,
    clause: Vec<selectors::Selector>,
  },
  Filesystem {
    subject: Key,
    product: TypeId,
    variants: Variants,
  },
}

pub impl Node {
  pub fn create(selector: Selector, subject: Key, variants: Variants) -> Node {
    match selector {
      Selector::Select(s) =>
        Node::Select {
          subject: subject,
          variants: variants,
          selector: s,
        },
      Selector::SelectVariant(s) =>
        Node::SelectVariant {
          subject: subject,
          variants: variants,
          selector: s,
        },
      Selector::SelectLiteral(s) =>
        // Intentionally ignores subject parameter to provide a literal subject.
        Node::SelectLiteral {
          subject: s.subject,
          variants: variants,
          selector: s,
        },
      Selector::SelectDependencies(s) =>
        Node::Dependencies {
          subject: subject,
          variants: variants,
          selector: s,
        },
      Selector::SelectProjection(s) =>
        Node::Projection {
          subject: subject,
          variants: variants,
          selector: s,
        },
    }
  }
}
