// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::hash;
use std::sync::atomic;

use cpython::{ObjectProtocol, PyErr, PyType, Python, ToPyObject};
use parking_lot::{Mutex, RwLock};

use crate::core::{Key, Value, FNV};
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
/// To avoid deadlocks, methods of Interns require that the GIL is held, and then explicitly release
/// it before acquiring inner locks. That way we can guarantee that these locks are always acquired
/// before the GIL (Value equality in particular might re-acquire it).
///
#[derive(Default)]
pub struct Interns {
  forward_keys: Mutex<HashMap<InternKey, Key, FNV>>,
  reverse_keys: RwLock<HashMap<Key, Value, FNV>>,
  id_generator: atomic::AtomicU64,
}

impl Interns {
  pub fn new() -> Interns {
    Interns::default()
  }

  pub fn key_insert(&self, py: Python, v: Value) -> Result<Key, PyErr> {
    let (intern_key, type_id) = {
      let obj = v.to_py_object(py).into();
      (InternKey(v.hash(py)?, obj), (&v.get_type(py)).into())
    };

    py.allow_threads(|| {
      let (key, key_was_new) = {
        let mut forward_keys = self.forward_keys.lock();
        if let Some(key) = forward_keys.get(&intern_key) {
          (*key, false)
        } else {
          let id = self.id_generator.fetch_add(1, atomic::Ordering::SeqCst);
          let key = Key::new(id, type_id);
          forward_keys.insert(intern_key, key);
          (key, true)
        }
      };
      if key_was_new {
        self.reverse_keys.write().insert(key, v);
      }
      Ok(key)
    })
  }

  pub fn key_get(&self, k: &Key) -> Value {
    // NB: We do not need to acquire+release the GIL before getting a Value for a Key, because
    // neither `Key::eq` nor `Value::clone` acquire the GIL.
    self
      .reverse_keys
      .read()
      .get(&k)
      .cloned()
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
