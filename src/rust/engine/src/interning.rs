// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::hash;

use core::{Key, Value, FNV};
use externs;

///
/// A struct that encapsulates interning of python `Value`s as comparable `Key`s.
///
/// To minimize the total amount of time spent in python code comparing objects (represented on
/// the rust side of the FFI boundary as `Value` instances) to one another, this API supports
/// memoizing `Value`s as `Key`s.
///
/// Creating a `Key` involves interning a `Value` under a (private) `InternKey` struct which
/// implements `Hash` and `Eq` using the precomputed python `__hash__` for the `Value` and
/// delegating to python's `__eq__`, respectively.
///
/// Currently `Value`s are interned indefinitely as `Key`s, meaning that they can never
/// be collected: it's possible that this can eventually be improved by either:
///
///   1) switching to directly linking-against or embedding python, such that the `Value`
///      type goes away in favor of direct usage of a python object wrapper struct.
///   2) This structure might begin storing weak-references to `Key`s and/or `Value`s, which
///      would allow the associated `Value` handles to be dropped when they were no longer used.
///      The challenge to this approach is that it would make it more difficult to pass
///      `Key`/`Value` instances across the FFI boundary.
///   3) `Value` could implement `Eq`/`Hash` directly via extern calls to python (although we've
///      avoided doing this so far because it would hide a relatively expensive operation behind
///      those usually-inexpensive traits).
///
#[derive(Default)]
pub struct Interns {
  forward: HashMap<InternKey, Key, FNV>,
  reverse: HashMap<Key, Value, FNV>,
  id_generator: u64,
}

impl Interns {
  pub fn new() -> Interns {
    Interns::default()
  }

  pub fn insert(&mut self, v: Value) -> Key {
    let ident = externs::identify(&v);
    let type_id = ident.type_id;
    let mut inserted = false;
    let id_generator = self.id_generator;
    let key = *self
      .forward
      .entry(InternKey(ident.hash, v.clone()))
      .or_insert_with(|| {
        inserted = true;
        Key::new(id_generator, type_id)
      });
    if inserted {
      self.reverse.insert(key, v);
      self.id_generator += 1;
    }
    key
  }

  pub fn get(&self, k: &Key) -> &Value {
    self
      .reverse
      .get(&k)
      .unwrap_or_else(|| panic!("Previously memoized object disappeared for {:?}", k))
  }
}

struct InternKey(i64, Value);

impl Eq for InternKey {}

impl PartialEq for InternKey {
  fn eq(&self, other: &InternKey) -> bool {
    externs::equals(&self.1, &other.1)
  }
}

impl hash::Hash for InternKey {
  fn hash<H: hash::Hasher>(&self, state: &mut H) {
    self.0.hash(state);
  }
}
