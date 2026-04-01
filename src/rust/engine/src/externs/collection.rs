// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::Debug;
use std::sync::OnceLock;

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyIterator};

pub trait HashCache: Debug + Send + Sync {
    fn new_eager(hash: isize) -> Self;
    fn new_lazy() -> Self;
    fn get(
        &self,
        dict: &Bound<PyDict>,
        compute: fn(&Bound<PyDict>) -> PyResult<isize>,
    ) -> PyResult<isize>;
}

#[derive(Debug)]
pub struct EagerHash(isize);

impl HashCache for EagerHash {
    fn new_eager(hash: isize) -> Self {
        Self(hash)
    }
    fn new_lazy() -> Self {
        panic!("EagerHash requires a value at construction")
    }
    fn get(
        &self,
        _dict: &Bound<PyDict>,
        _compute: fn(&Bound<PyDict>) -> PyResult<isize>,
    ) -> PyResult<isize> {
        Ok(self.0)
    }
}

#[derive(Debug)]
pub struct LazyHash(OnceLock<isize>);

impl HashCache for LazyHash {
    fn new_eager(hash: isize) -> Self {
        let lock = OnceLock::new();
        let _ = lock.set(hash);
        Self(lock)
    }
    fn new_lazy() -> Self {
        Self(OnceLock::new())
    }
    fn get(
        &self,
        dict: &Bound<PyDict>,
        compute: fn(&Bound<PyDict>) -> PyResult<isize>,
    ) -> PyResult<isize> {
        if let Some(&h) = self.0.get() {
            return Ok(h);
        }
        let h = compute(dict)?;
        let _ = self.0.set(h);
        Ok(h)
    }
}

#[derive(Debug)]
pub struct FrozenCollectionData<H: HashCache = EagerHash> {
    pub data: Py<PyDict>,
    hash: H,
}

impl<H: HashCache> FrozenCollectionData<H> {
    pub fn new(dict: Bound<PyDict>, hash: isize) -> Self {
        Self {
            data: dict.unbind(),
            hash: H::new_eager(hash),
        }
    }

    pub fn new_lazy(dict: Bound<PyDict>) -> Self {
        Self {
            data: dict.unbind(),
            hash: H::new_lazy(),
        }
    }

    pub fn get_hash(
        &self,
        py: Python,
        compute: fn(&Bound<PyDict>) -> PyResult<isize>,
    ) -> PyResult<isize> {
        self.hash.get(&self.data.bind_borrowed(py), compute)
    }

    pub fn len(&self, py: Python) -> usize {
        self.data.bind_borrowed(py).len()
    }

    pub fn contains(&self, key: &Bound<PyAny>) -> PyResult<bool> {
        self.data.bind_borrowed(key.py()).contains(key)
    }

    pub fn iter<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyIterator>> {
        self.data.as_any().bind_borrowed(py).try_iter()
    }

    pub fn reversed<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyIterator>> {
        let keys = self.data.bind_borrowed(py).keys();
        keys.reverse()?;
        keys.try_iter()
    }
}

pub fn xor_hash_keys(dict: &Bound<PyDict>) -> PyResult<isize> {
    let mut h: isize = 0;
    for key in dict.keys() {
        h ^= key.hash()?;
    }
    Ok(h)
}
