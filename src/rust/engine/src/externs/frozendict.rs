// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::hash::{Hash, Hasher};
use std::sync::OnceLock;

use pyo3::exceptions::{PyKeyError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::{IntoPyObjectExt, intern};

use pyo3::types::iter::BoundListIterator;
use pyo3::types::{
    PyDict, PyIterator, PyList, PyMapping, PyNotImplemented, PySet, PyTuple, PyType,
};

static EMPTY_FROZEN_DICT: OnceLock<Py<FrozenDict>> = OnceLock::new();

#[pyclass(subclass, frozen, mapping, generic)]
#[derive(Debug)]
pub struct FrozenDict {
    data: Py<PyDict>,
    pub(crate) hash: isize,
}

impl Hash for FrozenDict {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.hash.hash(state);
    }
}

#[pymethods]
impl FrozenDict {
    #[new]
    #[pyo3(signature=(*py_args, **py_kwargs))]
    fn __new__(py_args: &Bound<PyTuple>, py_kwargs: Option<&Bound<PyDict>>) -> PyResult<Self> {
        Self::from_pyargs(py_args, py_kwargs)
    }

    #[classmethod]
    pub fn deep_freeze<'py>(
        cls: &Bound<'py, PyType>,
        data: &Bound<'py, PyMapping>,
    ) -> PyResult<Bound<'py, PyAny>> {
        fn _freeze<'py>(
            cls: &Bound<'py, PyType>,
            obj: Bound<'py, PyAny>,
        ) -> PyResult<Bound<'py, PyAny>> {
            Ok(if let Ok(dict) = obj.cast::<PyDict>() {
                FrozenDict::deep_freeze(cls, dict.as_mapping())?
            } else if let Ok(listlike) = obj.cast::<PyList>() {
                PyTuple::new(
                    listlike.py(),
                    listlike
                        .into_iter()
                        .map(|v| _freeze(cls, v))
                        .collect::<PyResult<Vec<_>>>()?,
                )?
                .into_any()
            } else if let Ok(setlike) = obj.cast::<PySet>() {
                PyTuple::new(
                    setlike.py(),
                    setlike
                        .into_iter()
                        .map(|v| _freeze(cls, v))
                        .collect::<PyResult<Vec<_>>>()?,
                )?
                .into_any()
            } else {
                obj
            })
        }
        let py = data.py();
        let frozen = PyDict::new(py);
        for (key, value) in KeyValueIter::new(data)? {
            frozen.set_item(key, _freeze(cls, value)?)?;
        }
        if cls.is(py.get_type::<FrozenDict>()) {
            Self::from_pyargs(&PyTuple::new(py, [frozen])?, None)?.into_bound_py_any(py)
        } else {
            cls.call1((frozen,))
        }
    }

    #[staticmethod]
    fn frozen<'py>(to_freeze: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        if to_freeze.is_instance_of::<FrozenDict>() {
            Ok(to_freeze.into_any())
        } else {
            let py = to_freeze.py();
            Self::from_pyargs(&PyTuple::new(py, [to_freeze])?, None)?.into_bound_py_any(py)
        }
    }

    fn __getitem__<'py>(&self, input: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        self.inner_get(input.as_borrowed(), None)
            .transpose()
            .unwrap_or_else(|| Err(PyKeyError::new_err(input.unbind())))
    }

    #[pyo3(signature = (input, default = None))]
    fn get<'py>(
        &self,
        input: Bound<'py, PyAny>,
        default: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Option<Bound<'py, PyAny>>> {
        self.inner_get(input.as_borrowed(), default)
    }

    fn __repr__(slf: &Bound<Self>) -> PyResult<String> {
        Ok(format!(
            "FrozenDict({})",
            slf.get().data.bind_borrowed(slf.py()).repr()?
        ))
    }

    fn __hash__(&self) -> isize {
        self.hash
    }

    fn __iter__<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyIterator>> {
        slf.get().data.as_any().bind_borrowed(slf.py()).try_iter()
    }

    fn __eq__(&self, other: &Bound<PyAny>) -> PyResult<bool> {
        self.data.bind_borrowed(other.py()).eq(other)
    }

    fn __len__(slf: PyRef<Self>) -> usize {
        slf.data.bind_borrowed(slf.py()).len()
    }

    fn __reversed__<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyIterator>> {
        let py = slf.py();
        let keys = slf.get().data.bind_borrowed(py).keys();
        keys.reverse()?;
        keys.try_iter()
    }

    fn __lt__<'py>(&self, other: &Bound<'py, PyAny>) -> PyResult<bool> {
        if !other.is_instance_of::<FrozenDict>() {
            return Err(PyTypeError::new_err(
                "FrozenDict can only be compared with FrozenDict",
            ));
        }
        let py = other.py();
        let self_dict = self.data.bind_borrowed(py);
        let other_fd = other.cast::<FrozenDict>()?;
        let other_dict = other_fd.get().data.bind_borrowed(py);

        let self_len = self_dict.len();
        let other_len = other_dict.len();

        let self_keys = self_dict.items();
        let other_keys = other_dict.items();
        self_keys.sort()?;
        other_keys.sort()?;

        for (k1, k2) in self_keys.iter().zip(other_keys.iter()) {
            if k1
                .rich_compare(k2.as_borrowed(), pyo3::basic::CompareOp::Lt)?
                .is_truthy()?
            {
                return Ok(true);
            }
            if k2
                .rich_compare(k1, pyo3::basic::CompareOp::Lt)?
                .is_truthy()?
            {
                return Ok(false);
            }
        }
        Ok(self_len < other_len)
    }

    fn __contains__(&self, input: &Bound<PyAny>) -> PyResult<bool> {
        self.data.bind_borrowed(input.py()).contains(input)
    }

    fn __or__<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let py = other.py();
        if let Some(other) = get_inner_or_mapping(&other)? {
            let py_args = PyTuple::new(py, [self.data.bind_borrowed(py).bitor(other)?])?;
            Self::from_pyargs(&py_args, None)?.into_bound_py_any(py)
        } else {
            Ok(PyNotImplemented::get(py).into_bound_py_any(py)?)
        }
    }

    fn __ror__<'py>(&self, other: Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let py = other.py();
        if let Some(other) = get_inner_or_mapping(&other)? {
            let py_args = PyTuple::new(py, [other.bitor(self.data.bind_borrowed(py))?])?;

            Self::from_pyargs(&py_args, None)?.into_bound_py_any(py)
        } else {
            Ok(PyNotImplemented::get(py).into_bound_py_any(py)?)
        }
    }

    fn keys<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyAny>> {
        Self::py_keys(slf)
    }

    fn values<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyAny>> {
        let dict = slf.get().data.bind_borrowed(slf.py());
        dict.call_method0(intern!(slf.py(), "values"))
    }

    fn items<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyAny>> {
        let dict = slf.get().data.bind_borrowed(slf.py());
        dict.call_method0(intern!(slf.py(), "items"))
    }

    pub fn __getnewargs__(&self) -> PyResult<(&Py<PyDict>,)> {
        Ok((&self.data,))
    }
}

fn get_inner_or_mapping<'a, 'py>(
    obj: &'a Bound<'py, PyAny>,
) -> PyResult<Option<&'a Bound<'py, PyMapping>>> {
    let py = obj.py();
    Ok(if obj.is_instance_of::<FrozenDict>() {
        let fd: &Bound<FrozenDict> = obj.cast::<FrozenDict>()?;
        Some(fd.get().data.bind(py).cast::<PyMapping>()?)
    } else {
        obj.cast::<PyMapping>().ok()
    })
}

pub struct KeyValueIter<'py>(BoundListIterator<'py>);

impl<'py> KeyValueIter<'py> {
    fn new(mapping: &Bound<'py, PyMapping>) -> PyResult<Self> {
        Ok(Self(mapping.items()?.into_iter()))
    }
}

impl<'py> Iterator for KeyValueIter<'py> {
    type Item = (Bound<'py, PyAny>, Bound<'py, PyAny>);

    fn next(&mut self) -> Option<Self::Item> {
        self.0.next().map(|item| unsafe {
            let tuple = item.cast_unchecked::<PyTuple>();

            (tuple.get_item_unchecked(0), tuple.get_item_unchecked(1))
        })
    }
}

impl ExactSizeIterator for KeyValueIter<'_> {
    fn len(&self) -> usize {
        self.0.len()
    }
}

impl FrozenDict {
    fn from_pyargs(args: &Bound<PyTuple>, kwargs: Option<&Bound<PyDict>>) -> PyResult<Self> {
        let py = args.py();
        let dict = PyDict::new(py);

        if args.len() > 1 {
            return Err(PyValueError::new_err(format!(
                "FrozenDict was called with {} positional arguments {:?} but it expects one.",
                args.len(),
                args
            )));
        }
        if let Ok(arg) = args.get_borrowed_item(0) {
            if let Ok(mapping) = arg.cast::<PyMapping>() {
                for (k, v) in KeyValueIter::new(&mapping)? {
                    dict.set_item(k, v)?;
                }
            } else if let Ok(iterable) = arg.try_iter() {
                for item in iterable {
                    let item = item?;
                    let tuple = item.cast::<PyTuple>();
                    let tuple = match tuple {
                        Ok(tuple) if tuple.len() == 2 => tuple,
                        _ => {
                            return Err(PyTypeError::new_err(
                                "iterator elements must be 2-item tuples",
                            ));
                        }
                    };
                    unsafe {
                        dict.set_item(
                            tuple.get_borrowed_item_unchecked(0),
                            tuple.get_borrowed_item_unchecked(1),
                        )?;
                    }
                }
            } else {
                return Err(PyTypeError::new_err(
                    "argument must be a mapping or iterable of key-value pairs",
                ));
            }
        }
        if let Some(kwargs) = kwargs {
            for (k, v) in kwargs {
                dict.set_item(k, v)?;
            }
        }

        Self::from_pydict(dict)
    }

    pub fn from_pydict(dict: Bound<PyDict>) -> PyResult<Self> {
        let hash = compute_frozendict_hash(&dict)?;

        Ok(Self {
            data: dict.unbind(),
            hash,
        })
    }

    pub fn py_keys<'py>(slf: &Bound<'py, Self>) -> PyResult<Bound<'py, PyAny>> {
        let dict = slf.get().data.bind_borrowed(slf.py());
        dict.call_method0(intern!(slf.py(), "keys"))
    }

    pub fn contains(&self, key: &Bound<PyAny>) -> PyResult<bool> {
        self.data.bind_borrowed(key.py()).contains(key)
    }

    pub fn iter(slf: Bound<Self>) -> PyResult<KeyValueIter> {
        KeyValueIter::new(slf.get().data.bind_borrowed(slf.py()).as_mapping())
    }

    pub fn empty<'py>(py: Python<'py>) -> Bound<'py, FrozenDict> {
        EMPTY_FROZEN_DICT
            .get_or_init(|| {
                let fd = Self {
                    data: PyDict::new(py).unbind(),
                    hash: 0,
                };
                Py::new(py, fd).expect("failed to create empty FrozenDict")
            })
            .bind(py)
            .clone()
    }

    pub fn eq(&self, other: &Self, py: Python) -> PyResult<bool> {
        if self.hash != other.hash {
            return Ok(false);
        }
        self.data.bind_borrowed(py).eq(other.data.bind_borrowed(py))
    }

    fn inner_get<'a, 'py>(
        &self,
        input: Borrowed<'a, 'py, PyAny>,
        default: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Option<Bound<'py, PyAny>>> {
        self.data
            .bind_borrowed(input.py())
            .get_item(input)
            .transpose()
            .or(default.map(Ok))
            .transpose()
    }
}

/// Compute a commutative hash for a dictionary
fn compute_frozendict_hash(dict: &Bound<PyDict>) -> PyResult<isize> {
    let mut h: isize = 0;
    for (k, v) in dict {
        let pair = PyTuple::new(dict.py(), [k, v])?;
        let pair_hash = pair.hash()?;
        h ^= pair_hash;
    }
    Ok(h)
}

pub fn register(py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<FrozenDict>()?;
    PyMapping::register::<FrozenDict>(py)
}
