// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::basic::CompareOp;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::{PyIterator, PySequence, PySlice, PyTuple, PyType};

pub fn register(_py: Python, m: &PyModule) -> PyResult<()> {
  m.add_class::<Collection>()?;

  Ok(())
}

#[pyclass(subclass, sequence, weakref, frozen)]
pub struct Collection(Py<PyTuple>);

#[pymethods]
impl Collection {
  #[classmethod]
  fn __class_getitem__<'p>(cls: &'p PyType, _item: &'p PyAny) -> &'p PyType {
    cls
  }

  #[new]
  fn __new__(py: Python, input: Option<&PyAny>) -> PyResult<Self> {
    let Some(input) = input else {
      return Ok(Self(PyTuple::empty(py).into()));
    };

    if let Ok(seq) = input.downcast::<PySequence>() {
      return Ok(Self(seq.to_tuple()?.into()));
    }

    // A tuple can only be created from a collection of known size. We could technically attempt a
    // call to `len` here, and then manually create an `ExactSizeIterator` from it, but since
    // generators don't implement `len`, it wouldn't buy us much.
    let iterator = PyIterator::from_object(py, input)?;
    let items = iterator.collect::<Result<Vec<_>, _>>()?;
    Ok(Self(PyTuple::new(py, items).into()))
  }

  fn __len__(&self, py: Python) -> usize {
    self.0.as_ref(py).len()
  }

  fn __iter__<'p>(&'p self, py: Python<'p>) -> PyResult<&'p PyIterator> {
    let tuple: &PyAny = self.0.as_ref(py);
    tuple.iter()
  }

  fn __getitem__<'p>(self_: &'p PyCell<Self>, py: Python<'p>, key: &PyAny) -> PyResult<&'p PyAny> {
    if let Ok(idx) = key.extract::<isize>() {
      let tuple = self_.get().0.as_ref(py);
      let idx: usize = if idx < 0 {
        tuple.len().checked_add_signed(idx).ok_or_else(|| {
          PyException::new_err(format!(
            "Index out of range (with len {}): {key}",
            tuple.len()
          ))
        })?
      } else {
        idx as usize
      };
      tuple.get_item(idx)
    } else if let Ok(slice) = key.downcast::<PySlice>() {
      let tuple = self_.get().0.as_ref(py);
      let index = slice.indices(tuple.len() as i64).unwrap();
      // `indices` adapts negative arguments based on the passed length, so can safely cast to `usize`.
      let items = tuple.get_slice(
        index.start.try_into().unwrap(),
        index.stop.try_into().unwrap(),
      );
      self_.get_type().call((items,), None)
    } else {
      Err(PyException::new_err(format!(
        "Unsupported argument __getitem__: {key}"
      )))
    }
  }

  fn __concat__<'p>(
    self_: &'p PyCell<Self>,
    other: &'p PyAny,
    py: Python<'p>,
  ) -> PyResult<&'p PyAny> {
    if !self_.get_type().is(other.get_type()) {
      return Err(PyException::new_err(format!(
        "Collection types {} and {} may not be concatenated.",
        self_.get_type().name()?,
        other.get_type().name()?
      )));
    }
    let other = other.extract::<PyRef<Self>>()?;

    let left: &PyAny = self_.get().0.as_ref(py);
    let right: &PyAny = other.0.as_ref(py);
    let items = left
      .iter()?
      .chain(right.iter()?)
      .collect::<Result<Vec<_>, _>>()?;
    self_.get_type().call((items,), None)
  }

  fn __hash__(&self, py: Python) -> PyResult<isize> {
    // NB: The type is included in equality, but not in hash (for simplicity).
    self.0.as_ref(py).hash()
  }

  fn __str__(&self) -> String {
    format!("{}", self.0)
  }

  fn __repr__(self_: &PyCell<Self>) -> PyResult<String> {
    Ok(format!("{}({})", self_.get_type().name()?, self_.get().0))
  }

  fn __richcmp__(
    self_: &PyCell<Self>,
    other: &PyAny,
    op: CompareOp,
    py: Python,
  ) -> PyResult<PyObject> {
    if !self_.get_type().is(other.get_type()) {
      return Ok(py.NotImplemented());
    }
    let other = other.extract::<PyRef<Self>>()?;
    Ok(self_.get().0.as_ref(py).rich_compare(&other.0, op)?.into())
  }
}
