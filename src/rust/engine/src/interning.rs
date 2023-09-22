// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::atomic;

use pyo3::exceptions::PyKeyError;
use pyo3::prelude::*;
use pyo3::types::PyMapping;

use crate::python::{Key, TypeId};

///
/// A struct that encapsulates interning of python `Value`s as comparable `Key`s.
///
/// To minimize the total amount of time spent in python code comparing objects (represented on
/// the rust side of the FFI boundary as `Value` instances) to one another, this API supports
/// memoizing `Value`s as `Key`s, which can be compared for equality without acquiring the GIL.
///
pub struct Interns {
  // A mapping between weakly referenced Python objects and integer ids.
  keys: Py<PyMapping>,
  id_generator: atomic::AtomicU64,
}

impl Interns {
  pub fn new() -> Self {
    Self {
      keys: Python::with_gil(|py| {
        let weak_key_dict = py
          .import("weakref")?
          .getattr("WeakKeyDictionary")?
          .call((), None)?;
        Ok::<_, PyErr>(weak_key_dict.downcast::<PyMapping>()?.into())
      })
      .unwrap(),
      id_generator: atomic::AtomicU64::default(),
    }
  }

  pub fn key_insert(&self, py: Python, v: PyObject) -> PyResult<Key> {
    let (id, type_id): (u64, TypeId) = {
      let v = v.as_ref(py);
      let keys = self.keys.as_ref(py);
      let id: u64 = match keys.get_item(v) {
        Err(e) if e.is_instance_of::<PyKeyError>(py) => {
          // NB: Because we're under the GIL, we're not racing other threads to insert a new key
          // here. If that changes (e.g. via https://github.com/PyO3/pyo3/pull/2885), we would need
          // a lock added to this lookup.
          let id = self.id_generator.fetch_add(1, atomic::Ordering::Relaxed);
          keys.set_item(v, id)?;
          id
        }
        Ok(id) => id.extract()?,
        Err(e) => return Err(e),
      };
      (id, v.get_type().into())
    };

    Ok(Key::new(id, type_id, v.into()))
  }
}
