use std::collections::HashMap;

use core::{Key, Selector, TypeId, Variants};

// TODO: coroutines as iterators probably.
pub type Step = bool;

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
  Runnable {
    func: Key,
    args: Vec<Key>,
  },
}

#[derive(Debug, Eq, Hash, PartialEq)]
pub enum Node {
  Select {
    subject: Key,
    variants: Variants,
    selector: Selector,
  },
  SelectVariant {
    subject: Key,
    variants: Variants,
    selector: Selector,
  },
  Dependencies {
    subject: Key,
    variants: Variants,
    selector: Selector,
  },
  Projection {
    subject: Key,
    variants: Variants,
    selector: Selector,
  },
  Task {
    subject: Key,
    product: TypeId,
    variants: Variants,
    func: Key,
    clause: Vec<Selector>,
  },
  Filesystem {
    subject: Key,
    product: TypeId,
    variants: Variants,
  },
}

impl Node {
  /*
  fn subject(&self) -> Key {
    match self {

    }
  }

  fn product(&self) -> TypeId {
    self.selector.product
  }

  fn variants(&self) -> Variants {
    self.variants
  }
  */
}
