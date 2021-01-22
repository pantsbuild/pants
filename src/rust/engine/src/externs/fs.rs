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
  clippy::manual_strip,
  clippy::used_underscore_binding,
  clippy::transmute_ptr_to_ptr,
  clippy::zero_ptr
)]

use std::borrow::Cow;

use cpython::{
  exc, py_class, CompareOp, PyErr, PyObject, PyResult, PyString, PyTuple, Python, PythonObject,
  ToPyObject,
};
use fs::PathStat;
use hashing::{Digest, Fingerprint};
use store::Snapshot;

///
/// Data members and `create_instance` methods are module-private by default, so we expose them
/// with public top-level functions.
///
/// TODO: See https://github.com/dgrunwald/rust-cpython/issues/242
///

pub fn to_py_digest(digest: Digest) -> PyResult<PyDigest> {
  let gil = Python::acquire_gil();
  PyDigest::create_instance(gil.python(), digest)
}

pub fn from_py_digest(digest: &PyObject) -> PyResult<Digest> {
  let gil = Python::acquire_gil();
  let py = gil.python();
  let py_digest = digest.extract::<PyDigest>(py)?;
  Ok(*py_digest.digest(py))
}

py_class!(pub class PyDigest |py| {
    data digest: Digest;
    def __new__(_cls, fingerprint: Cow<str>, serialized_bytes_length: usize) -> PyResult<Self> {
      let fingerprint = Fingerprint::from_hex_string(&fingerprint)
        .map_err(|e| {
          PyErr::new::<exc::Exception, _>(py, format!("Invalid digest hex: {}", e))
        })?;
      Self::create_instance(py, Digest::new(fingerprint, serialized_bytes_length))
    }

    @property def fingerprint(&self) -> PyResult<String> {
      Ok(self.digest(py).fingerprint.to_hex())
    }

    @property def serialized_bytes_length(&self) -> PyResult<usize> {
      Ok(self.digest(py).size)
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
      Ok(self.digest(py).fingerprint.prefix_hash())
    }
});

pub fn to_py_snapshot(snapshot: Snapshot) -> PyResult<PySnapshot> {
  let gil = Python::acquire_gil();
  PySnapshot::create_instance(gil.python(), snapshot)
}

py_class!(pub class PySnapshot |py| {
    data snapshot: Snapshot;
    def __new__(_cls) -> PyResult<Self> {
      Self::create_instance(py, Snapshot::empty())
    }

    @property def digest(&self) -> PyResult<PyDigest> {
      to_py_digest(self.snapshot(py).digest)
    }

    @property def files(&self) -> PyResult<PyTuple> {
      let files = self.snapshot(py).path_stats.iter().filter_map(|ps| match ps {
        PathStat::File { path, .. } => path.to_str(),
        _ => None,
      }).map(|ps| PyString::new(py, ps).into_object()).collect::<Vec<_>>();
      Ok(PyTuple::new(py, &files))
    }

    @property def dirs(&self) -> PyResult<PyTuple> {
      let dirs = self.snapshot(py).path_stats.iter().filter_map(|ps| match ps {
        PathStat::Dir { path, .. } => path.to_str(),
        _ => None,
      }).map(|ps| PyString::new(py, ps).into_object()).collect::<Vec<_>>();
      Ok(PyTuple::new(py, &dirs))
    }

    def __richcmp__(&self, other: PySnapshot, op: CompareOp) -> PyResult<PyObject> {
      match op {
        CompareOp::Eq => {
          let res = self.snapshot(py).digest == other.snapshot(py).digest;
          Ok(res.to_py_object(py).into_object())
        },
        CompareOp::Ne => {
          let res = self.snapshot(py).digest != other.snapshot(py).digest;
          Ok(res.to_py_object(py).into_object())
        }
        _ => Ok(py.NotImplemented()),
      }
    }

    def __hash__(&self) -> PyResult<u64> {
      Ok(self.snapshot(py).digest.fingerprint.prefix_hash())
    }
});
