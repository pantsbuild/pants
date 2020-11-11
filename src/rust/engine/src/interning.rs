// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::hash;

use cpython::{ObjectProtocol, PyClone, PyErr, PyType, Python, PythonObject, ToPyObject};

use crate::core::{Key, TypeId, Value, FNV};
use crate::externs;

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
  forward_keys: HashMap<InternKey, Key, FNV>,
  reverse_keys: HashMap<Key, Value, FNV>,
  forward_types: HashMap<InternType, TypeId, FNV>,
  reverse_types: HashMap<TypeId, PyType, FNV>,
  id_generator: u64,
}

impl Interns {
  pub fn new() -> Interns {
    Interns::default()
  }

  pub fn key_insert(&mut self, py: Python, v: Value) -> Result<Key, PyErr> {
    let intern_key = InternKey(v.hash(py)?, v.to_py_object(py).into());

    let key = if let Some(key) = self.forward_keys.get(&intern_key) {
      *key
    } else {
      let id = self.id_generator;
      self.id_generator += 1;
      let key = Key::new(id, self.type_insert(py, v.get_type(py)));
      self.forward_keys.insert(intern_key, key);
      self.reverse_keys.insert(key, v);
      key
    };
    Ok(key)
  }

  pub fn key_get(&self, k: &Key) -> &Value {
    self
      .reverse_keys
      .get(&k)
      .unwrap_or_else(|| panic!("Previously memoized object disappeared for {:?}", k))
  }

  pub fn type_insert(&mut self, py: Python, v: PyType) -> TypeId {
    let intern_type = InternType(v.as_object().hash(py).unwrap(), v.clone_ref(py));

    if let Some(type_id) = self.forward_types.get(&intern_type) {
      *type_id
    } else {
      let id = self.id_generator;
      self.id_generator += 1;
      let type_id = TypeId(id);
      self.forward_types.insert(intern_type, type_id);
      self.reverse_types.insert(type_id, v);
      type_id
    }
  }

  pub fn type_get(&self, k: &TypeId) -> &PyType {
    self
      .reverse_types
      .get(&k)
      .unwrap_or_else(|| panic!("Previously memoized object disappeared for {:?}", k))
  }
}

struct InternKey(isize, Value);

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

struct InternType(isize, PyType);

impl Eq for InternType {}

impl PartialEq for InternType {
  fn eq(&self, other: &InternType) -> bool {
    self.1 == other.1
  }
}

impl hash::Hash for InternType {
  fn hash<H: hash::Hasher>(&self, state: &mut H) {
    self.0.hash(state);
  }
}
