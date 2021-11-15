// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

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
use either::Either;
use fs::PathStat;
use hashing::{Digest, Fingerprint};
use itertools::Itertools;
use store::Snapshot;

///
/// Data members and `create_instance` methods are module-private by default, so we expose them
/// with public top-level functions.
///
/// TODO: See https://github.com/dgrunwald/rust-cpython/issues/242
///

pub fn to_py_digest(py: Python, digest: Digest) -> PyResult<PyDigest> {
  PyDigest::create_instance(py, digest)
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
      Ok(self.digest(py).hash.to_hex())
    }

    @property def serialized_bytes_length(&self) -> PyResult<usize> {
      Ok(self.digest(py).size_bytes)
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
      Ok(self.digest(py).hash.prefix_hash())
    }

    def __repr__(&self) -> PyResult<String> {
      Ok(format!("Digest('{}', {})", self.digest(py).hash.to_hex(), self.digest(py).size_bytes))
    }
});

pub fn to_py_snapshot(py: Python, snapshot: Snapshot) -> PyResult<PySnapshot> {
  PySnapshot::create_instance(py, snapshot)
}

py_class!(pub class PySnapshot |py| {
    data snapshot: Snapshot;
    def __new__(_cls) -> PyResult<Self> {
      Self::create_instance(py, Snapshot::empty())
    }

    @classmethod def _create_for_testing(
      _cls,
      py_digest: PyDigest,
      files: Vec<String>,
      dirs: Vec<String>,
    ) -> PyResult<Self> {
      let snapshot = unsafe {
        Snapshot::create_for_testing_ffi(*py_digest.digest(py), files, dirs)
      };
      Self::create_instance(py, snapshot)
    }

    @property def digest(&self) -> PyResult<PyDigest> {
      to_py_digest(py, self.snapshot(py).digest)
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
      Ok(self.snapshot(py).digest.hash.prefix_hash())
    }

    def __repr__(&self) -> PyResult<String> {
      let (dirs, files): (Vec<_>, Vec<_>) = self.snapshot(py).path_stats.iter().partition_map(|ps| match ps {
        PathStat::Dir { path, .. } => Either::Left(path.to_string_lossy()),
        PathStat::File { path, .. } => Either::Right(path.to_string_lossy()),
      });

      Ok(format!(
        "Snapshot(digest=({}, {}), dirs=({}), files=({}))",
        self.snapshot(py).digest.hash.to_hex(),
        self.snapshot(py).digest.size_bytes,
        dirs.join(","),
        files.join(",")
      ))
    }
});
