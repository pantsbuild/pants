// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyIterator, PyList, PyNotImplemented, PySet, PyTuple};
use pyo3::{IntoPyObjectExt, PyTypeInfo};

use super::collection::{self, FrozenCollectionData, LazyHash};

#[pyclass(
    subclass,
    frozen,
    sequence,
    generic,
    module = "pants.engine.internals.native_engine"
)]
#[derive(Debug)]
pub struct FrozenOrderedSet {
    inner: FrozenCollectionData<LazyHash>,
}

#[pymethods]
impl FrozenOrderedSet {
    #[new]
    #[pyo3(signature = (iterable=None))]
    fn __new__(iterable: Option<&Bound<PyAny>>) -> PyResult<Self> {
        Self::from_iterable(iterable)
    }

    fn __len__(slf: PyRef<Self>) -> usize {
        slf.inner.len(slf.py())
    }

    fn __contains__(&self, key: &Bound<PyAny>) -> PyResult<bool> {
        self.inner.contains(key)
    }

    fn __iter__<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyIterator>> {
        slf.get().inner.iter(slf.py())
    }

    fn __reversed__<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyIterator>> {
        slf.get().inner.reversed(slf.py())
    }

    fn __repr__(slf: &Bound<Self>) -> PyResult<String> {
        let py = slf.py();
        let name = slf.get_type().qualname()?;
        let data = slf.get().inner.data.bind_borrowed(py);
        if data.is_empty() {
            return Ok(format!("{name}()"));
        }
        let items: Vec<_> = data
            .keys()
            .into_iter()
            .map(|k| k.repr().map(|r| r.to_string()))
            .collect::<PyResult<_>>()?;
        Ok(format!("{name}([{}])", items.join(", ")))
    }

    fn __hash__(&self, py: Python) -> PyResult<isize> {
        self.inner.get_hash(py, collection::xor_hash_keys)
    }

    fn __eq__<'py>(
        self_: &Bound<'py, Self>,
        other: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = other.py();
        if !other.is_instance(&self_.get_type())? {
            return PyNotImplemented::get(py).into_bound_py_any(py);
        }
        let this = self_.get();
        let other_fos = other.cast::<FrozenOrderedSet>()?;
        let self_dict = this.inner.data.bind_borrowed(py);
        let other_dict = other_fos.get().inner.data.bind_borrowed(py);

        if self_dict.len() != other_dict.len() {
            return false.into_bound_py_any(py);
        }
        for (a, b) in self_dict
            .keys()
            .into_iter()
            .zip(other_dict.keys().into_iter())
        {
            if !a.eq(&b)? {
                return false.into_bound_py_any(py);
            }
        }
        true.into_bound_py_any(py)
    }

    fn __or__<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let py = other.py();
        let merged = self.inner.data.bind_borrowed(py).copy()?;
        for item in other.try_iter()? {
            merged.set_item(item?, py.None())?;
        }
        Self::from_pydict(merged)?.into_bound_py_any(py)
    }

    #[pyo3(signature = (*others))]
    fn union<'py>(&self, others: &Bound<'py, PyTuple>) -> PyResult<Bound<'py, PyAny>> {
        let py = others.py();
        let merged = self.inner.data.bind_borrowed(py).copy()?;
        for other in others.iter() {
            for item in other.try_iter()? {
                merged.set_item(item?, py.None())?;
            }
        }
        Self::from_pydict(merged)?.into_bound_py_any(py)
    }

    fn __and__<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let py = other.py();
        let other_set = to_pyset(&other)?;
        filter_keys(self, py, |key| other_set.contains(key))
    }

    #[pyo3(signature = (*others))]
    fn intersection<'py>(&self, others: &Bound<'py, PyTuple>) -> PyResult<Bound<'py, PyAny>> {
        let py = others.py();
        if others.is_empty() {
            return Self::from_pydict(self.inner.data.bind_borrowed(py).copy()?)?
                .into_bound_py_any(py);
        }
        let sets = others
            .iter()
            .map(|o| to_pyset(&o))
            .collect::<PyResult<Vec<_>>>()?;
        filter_keys(self, py, |key| {
            Ok(sets.iter().all(|s| s.contains(key).unwrap_or(false)))
        })
    }

    fn __sub__<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let py = other.py();
        let other_set = to_pyset(&other)?;
        filter_keys(self, py, |key| other_set.contains(key).map(|b| !b))
    }

    #[pyo3(signature = (*others))]
    fn difference<'py>(&self, others: &Bound<'py, PyTuple>) -> PyResult<Bound<'py, PyAny>> {
        let py = others.py();
        if others.is_empty() {
            return Self::from_pydict(self.inner.data.bind_borrowed(py).copy()?)?
                .into_bound_py_any(py);
        }
        let excluded = PySet::empty(py)?;
        for other in others.iter() {
            for item in other.try_iter()? {
                excluded.add(item?)?;
            }
        }
        filter_keys(self, py, |key| excluded.contains(key).map(|b| !b))
    }

    fn __xor__<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        self.symmetric_difference(other)
    }

    fn symmetric_difference<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let py = other.py();
        let self_dict = self.inner.data.bind_borrowed(py);
        let other_dict = iter_to_pydict(&other)?;

        let result = PyDict::new(py);
        for key in self_dict.keys() {
            if !other_dict.contains(&key)? {
                result.set_item(&key, py.None())?;
            }
        }
        for key in other_dict.keys() {
            if !self_dict.contains(&key)? {
                result.set_item(&key, py.None())?;
            }
        }
        Self::from_pydict(result)?.into_bound_py_any(py)
    }

    fn __lt__(&self, other: &Bound<PyAny>) -> PyResult<bool> {
        Ok(self.issubset(other)? && self.inner.len(other.py()) != other.len()?)
    }

    fn __le__(&self, other: &Bound<PyAny>) -> PyResult<bool> {
        self.issubset(other)
    }

    fn __gt__(&self, other: &Bound<PyAny>) -> PyResult<bool> {
        Ok(self.issuperset(other)? && self.inner.len(other.py()) != other.len()?)
    }

    fn __ge__(&self, other: &Bound<PyAny>) -> PyResult<bool> {
        self.issuperset(other)
    }

    fn __rand__<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        self.__and__(other)
    }

    fn __ror__<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let py = other.py();
        let merged = iter_to_pydict(&other)?;
        for key in self.inner.data.bind_borrowed(py).keys() {
            merged.set_item(&key, py.None())?;
        }
        Self::from_pydict(merged)?.into_bound_py_any(py)
    }

    fn __rsub__<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let py = other.py();
        let self_dict = self.inner.data.bind_borrowed(py);
        let result = PyDict::new(py);
        for item in other.try_iter()? {
            let item = item?;
            if !self_dict.contains(&item)? {
                result.set_item(&item, py.None())?;
            }
        }
        Self::from_pydict(result)?.into_bound_py_any(py)
    }

    fn __rxor__<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        self.__xor__(other)
    }

    fn issubset(&self, other: &Bound<PyAny>) -> PyResult<bool> {
        let py = other.py();
        let self_dict = self.inner.data.bind_borrowed(py);
        if let Ok(other_fos) = other.cast::<FrozenOrderedSet>() {
            let other_dict = other_fos.get().inner.data.bind_borrowed(py);
            if self_dict.len() > other_dict.len() {
                return Ok(false);
            }
            for key in self_dict.keys() {
                if !other_dict.contains(&key)? {
                    return Ok(false);
                }
            }
        } else {
            let other_set = to_pyset(other)?;
            for key in self_dict.keys() {
                if !other_set.contains(&key)? {
                    return Ok(false);
                }
            }
        }
        Ok(true)
    }

    fn issuperset(&self, other: &Bound<PyAny>) -> PyResult<bool> {
        let py = other.py();
        let self_dict = self.inner.data.bind_borrowed(py);
        for item in other.try_iter()? {
            if !self_dict.contains(&item?)? {
                return Ok(false);
            }
        }
        Ok(true)
    }

    fn isdisjoint(&self, other: &Bound<PyAny>) -> PyResult<bool> {
        let py = other.py();
        let self_dict = self.inner.data.bind_borrowed(py);
        for item in other.try_iter()? {
            if self_dict.contains(&item?)? {
                return Ok(false);
            }
        }
        Ok(true)
    }

    fn __bool__(slf: PyRef<Self>) -> bool {
        !slf.inner.data.bind_borrowed(slf.py()).is_empty()
    }

    pub fn __getnewargs__<'py>(slf: &Bound<'py, Self>) -> PyResult<(Bound<'py, PyList>,)> {
        let py = slf.py();
        let keys = slf.get().inner.data.bind_borrowed(py).keys();
        Ok((keys,))
    }
}

fn iter_to_pydict<'py>(iterable: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    let py = iterable.py();
    let dict = PyDict::new(py);
    for item in iterable.try_iter()? {
        dict.set_item(item?, py.None())?;
    }
    Ok(dict)
}

fn to_pyset<'py>(iterable: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PySet>> {
    let py = iterable.py();
    let set = PySet::empty(py)?;
    for item in iterable.try_iter()? {
        set.add(item?)?;
    }
    Ok(set)
}

fn filter_keys<'py>(
    fos: &FrozenOrderedSet,
    py: Python<'py>,
    pred: impl Fn(&Bound<'py, PyAny>) -> PyResult<bool>,
) -> PyResult<Bound<'py, PyAny>> {
    let result = PyDict::new(py);
    for key in fos.inner.data.bind_borrowed(py).keys() {
        if pred(&key)? {
            result.set_item(&key, py.None())?;
        }
    }
    FrozenOrderedSet::from_pydict(result)?.into_bound_py_any(py)
}

impl FrozenOrderedSet {
    fn from_iterable(iterable: Option<&Bound<PyAny>>) -> PyResult<Self> {
        let Some(iterable) = iterable else {
            return Python::attach(|py| Self::from_pydict(PyDict::new(py)));
        };
        Self::from_pydict(iter_to_pydict(iterable)?)
    }

    fn from_pydict(dict: Bound<PyDict>) -> PyResult<Self> {
        Ok(Self {
            inner: FrozenCollectionData::new_lazy(dict),
        })
    }
}

pub fn register(py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<FrozenOrderedSet>()?;
    let abc = py.import("collections.abc")?;
    let set_abc = abc.getattr("Set")?;
    set_abc.call_method1("register", (FrozenOrderedSet::type_object(py),))?;
    let hashable_abc = abc.getattr("Hashable")?;
    hashable_abc.call_method1("register", (FrozenOrderedSet::type_object(py),))?;
    Ok(())
}
