// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::unseparated_literal_suffix,
// TODO: Falsely triggers for async/await:
//   see https://github.com/rust-lang/rust-clippy/issues/5360
// clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]
// File-specific allowances to silence internal warnings of `py_class!`.
#![allow(
  unused_braces,
  clippy::used_underscore_binding,
  clippy::transmute_ptr_to_ptr,
  clippy::zero_ptr
)]

use std::borrow::Cow;

use cpython::{
  exc, py_class, py_class_call_slot_impl_with_ref, py_class_prop_getter, CompareOp, PyErr,
  PyObject, PyResult, Python, PythonObject, ToPyObject,
};
use hashing::{Digest, Fingerprint};

/// TODO: See https://github.com/dgrunwald/rust-cpython/issues/242
pub fn new_py_digest(digest: Digest) -> PyResult<PyDigest> {
  let gil = Python::acquire_gil();
  PyDigest::create_instance(gil.python(), digest)
}

py_class!(pub class PyDigest |py| {
    data digest: Digest;
    def __new__(_cls, fingerprint: Cow<str>, serialized_bytes_length: usize) -> PyResult<Self> {
      let fingerprint = Fingerprint::from_hex_string(&fingerprint)
        .map_err(|e| {
          PyErr::new::<exc::Exception, _>(py, format!("Invalid digest hex: {}", e))
        })?;
      Self::create_instance(py, Digest(fingerprint, serialized_bytes_length))
    }

    @property def fingerprint(&self) -> PyResult<String> {
      Ok(self.digest(py).0.to_hex())
    }

    @property def serialized_bytes_length(&self) -> PyResult<usize> {
      Ok(self.digest(py).1)
    }

    def __richcmp__(&self, other: PyDigest, op: CompareOp) -> PyResult<PyObject> {
      match op {
        CompareOp::Eq => {
          let res = self.digest(py) == other.digest(py);
          Ok(res.to_py_object(py).into_object())
        },
        CompareOp::Ne => {
          let res = self.digest(py) != other.digest(py);
          Ok(res.to_py_object(py).into_object())
        }
        _ => Ok(py.NotImplemented()),
      }
    }

    def __hash__(&self) -> PyResult<u64> {
      Ok(self.digest(py).0.prefix_hash())
    }
});
