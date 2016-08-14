use std::collections::HashMap;

use core::{Key, Selector, TypeId};

// TODO: coroutines as iterators probably.
pub type Step = bool;

pub enum State<'a> {
  Waiting {
    dependencies: Vec<&'a Node>,
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

pub trait Node {
  fn subject(&self) -> Key;
  fn product(&self) -> TypeId;
  fn variants(&self) -> HashMap<String, String>;
  fn step(&self) -> Step;
}

struct SelectNode {
  subject: Key,
  variants: HashMap<String, String>,
  selector: Selector,
}
