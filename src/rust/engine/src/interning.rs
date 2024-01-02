// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::atomic;

use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::python::{Key, TypeId};

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
pub struct Interns {
    // A mapping between Python objects and integer ids.
    keys: Py<PyDict>,
    id_generator: atomic::AtomicU64,
}

impl Interns {
    pub fn new() -> Self {
        Self {
            keys: Python::with_gil(|py| PyDict::new(py).into()),
            id_generator: atomic::AtomicU64::default(),
        }
    }

    pub fn key_insert(&self, py: Python, v: PyObject) -> PyResult<Key> {
        let (id, type_id): (u64, TypeId) = {
            let v = v.as_ref(py);
            let keys = self.keys.as_ref(py);
            let id: u64 = if let Some(key) = keys.get_item(v) {
                key.extract()?
            } else {
                let id = self.id_generator.fetch_add(1, atomic::Ordering::Relaxed);
                keys.set_item(v, id)?;
                id
            };
            (id, v.get_type().into())
        };

        Ok(Key::new(id, type_id, v.into()))
    }
}
