// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::hash;

use core::{FNV, Id, Key, Value};
use externs;

#[derive(Default)]
pub struct Interns {
  forward: HashMap<InternKey, Key, FNV>,
  reverse: HashMap<Id, Value, FNV>,
  id_generator: u64,
}

impl Interns {
  pub fn new() -> Interns {
    Default::default()
  }

  pub fn insert(&mut self, v: Value) -> Key {
    let ident = externs::identify(&v);
    let type_id = ident.type_id;
    let mut maybe_id = self.id_generator;
    let key = self
      .forward
      .entry(InternKey(ident.hash, ident.value))
      .or_insert_with(|| {
        maybe_id += 1;
        Key::new(maybe_id, type_id)
      })
      .clone();
    if maybe_id != self.id_generator {
      self.id_generator = maybe_id;
      self.reverse.insert(maybe_id, v);
    }
    key
  }

  pub fn get(&self, k: &Key) -> &Value {
    self.reverse.get(&k.id()).unwrap_or_else(|| {
      panic!("Previously memoized object disappeared for {:?}", k)
    })
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
