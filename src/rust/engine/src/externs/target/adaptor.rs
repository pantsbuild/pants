// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::hash::{Hash, Hasher};

use fnv::FnvHasher;
use pyo3::basic::CompareOp;
use pyo3::exceptions::PyTypeError;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;
use pyo3::types::{PyDict, PyType};

use crate::externs::frozendict::FrozenDict;
use crate::externs::hunk::TextBlock;
use crate::python::PyComparedBool;

use super::util::combine_hashes;

fn deep_freeze_kwargs<'py>(
    kwargs: Option<&Bound<'py, PyDict>>,
    py: Python<'py>,
) -> PyResult<Py<FrozenDict>> {
    match kwargs {
        Some(dict) if !dict.is_empty() => {
            let cls = py.get_type::<FrozenDict>();
            let frozen = FrozenDict::deep_freeze(&cls, dict.as_mapping())?;
            Ok(frozen.extract::<Py<FrozenDict>>()?)
        }
        _ => Ok(FrozenDict::empty(py).unbind()),
    }
}

#[pyclass(frozen, module = "pants.engine.internals.native_engine")]
pub struct SourceBlock {
    start: i64,
    end: i64,
}

#[pymethods]
impl SourceBlock {
    #[new]
    fn __new__(start: i64, end: i64) -> PyResult<Self> {
        if start >= end {
            return Err(PyValueError::new_err(format!(
                "self.start={start} must be less than self.end={end}"
            )));
        }
        Ok(Self { start, end })
    }

    #[getter]
    fn start(&self) -> i64 {
        self.start
    }

    #[getter]
    fn end(&self) -> i64 {
        self.end
    }

    fn __len__(&self) -> usize {
        (self.end - self.start) as usize
    }

    fn __hash__(&self) -> isize {
        combine_hashes(&[self.start as isize, self.end as isize])
    }

    fn __richcmp__(&self, other: &Self, op: CompareOp) -> PyComparedBool {
        PyComparedBool::eq_ne(op, self.start == other.start && self.end == other.end)
    }

    fn is_touched_by(&self, other: PyRef<'_, TextBlock>) -> bool {
        let (start, end) = if other.count == 0 {
            let adjusted = other.start + 1;
            (adjusted, adjusted)
        } else {
            (other.start, other.start + other.count)
        };

        self.end >= start && end >= self.start
    }

    #[classmethod]
    fn from_text_block(
        _cls: &Bound<'_, PyType>,
        text_block: PyRef<'_, TextBlock>,
    ) -> PyResult<Self> {
        Self::__new__(text_block.start, text_block.start + text_block.count)
    }

    fn __repr__(&self) -> String {
        format!("SourceBlock(start={}, end={})", self.start, self.end)
    }
}

#[pyclass(frozen, module = "pants.engine.internals.native_engine")]
pub struct TargetAdaptor {
    type_alias: PyBackedStr,
    name: Option<PyBackedStr>,
    kwargs: Py<FrozenDict>,
    description_of_origin: PyBackedStr,
    origin_sources_blocks: Py<FrozenDict>,
}

#[pymethods]
impl TargetAdaptor {
    #[new]
    #[pyo3(signature = (type_alias, name, __description_of_origin__, __origin_sources_blocks__=None, **kwargs))]
    fn __new__(
        type_alias: PyBackedStr,
        name: Option<PyBackedStr>,
        __description_of_origin__: PyBackedStr,
        __origin_sources_blocks__: Option<Bound<'_, FrozenDict>>,
        kwargs: Option<&Bound<'_, PyDict>>,
        py: Python,
    ) -> PyResult<Self> {
        let frozen_kwargs = match deep_freeze_kwargs(kwargs, py) {
            Ok(frozen) => frozen,
            Err(error) if error.is_instance_of::<PyTypeError>(py) => {
                return Err(PyTypeError::new_err(format!(
                    "In {}: {}",
                    &*__description_of_origin__,
                    error.value(py)
                )));
            }
            Err(error) => return Err(error),
        };

        let origin_sources_blocks = match __origin_sources_blocks__ {
            Some(blocks) => blocks.unbind(),
            None => FrozenDict::empty(py).unbind(),
        };

        Ok(Self {
            type_alias,
            name,
            kwargs: frozen_kwargs,
            description_of_origin: __description_of_origin__,
            origin_sources_blocks,
        })
    }

    #[getter]
    fn type_alias(&self, py: Python) -> PyBackedStr {
        self.type_alias.clone_ref(py)
    }

    #[getter]
    fn name(&self, py: Python) -> Option<PyBackedStr> {
        self.name.as_ref().map(|name| name.clone_ref(py))
    }

    #[getter]
    fn kwargs(&self) -> &Py<FrozenDict> {
        &self.kwargs
    }

    #[getter]
    fn description_of_origin(&self, py: Python) -> PyBackedStr {
        self.description_of_origin.clone_ref(py)
    }

    #[getter]
    fn origin_sources_blocks(&self) -> &Py<FrozenDict> {
        &self.origin_sources_blocks
    }

    #[getter]
    fn name_explicitly_set(&self) -> bool {
        self.name.is_some()
    }

    #[pyo3(signature = (**kwargs))]
    fn with_new_kwargs(&self, kwargs: Option<&Bound<'_, PyDict>>, py: Python) -> PyResult<Self> {
        let frozen_kwargs = deep_freeze_kwargs(kwargs, py)?;

        Ok(Self {
            type_alias: self.type_alias.clone_ref(py),
            name: self.name.as_ref().map(|name| name.clone_ref(py)),
            kwargs: frozen_kwargs,
            description_of_origin: self.description_of_origin.clone_ref(py),
            origin_sources_blocks: self.origin_sources_blocks.clone_ref(py),
        })
    }

    fn __repr__(&self, py: Python) -> String {
        let origin_blocks = self.origin_sources_blocks.bind(py);
        let maybe_blocks = if origin_blocks.as_any().is_truthy().unwrap_or(false) {
            format!(", {}", origin_blocks.as_any())
        } else {
            String::new()
        };
        let name = match &self.name {
            Some(name) => &**name,
            None => "None",
        };
        format!(
            "TargetAdaptor(type_alias={}, name={name}, origin={}{})",
            &*self.type_alias, &*self.description_of_origin, maybe_blocks
        )
    }

    fn __richcmp__(
        &self,
        other: &Bound<'_, PyAny>,
        op: CompareOp,
        py: Python,
    ) -> PyResult<PyComparedBool> {
        if !other.is_instance_of::<TargetAdaptor>() {
            return Ok(PyComparedBool::eq_ne(op, false));
        }
        let other = other.extract::<PyRef<TargetAdaptor>>()?;
        let is_eq = *self.type_alias == *other.type_alias
            && self.name == other.name
            && self.kwargs.get().eq(other.kwargs.get(), py)?;
        Ok(PyComparedBool::eq_ne(op, is_eq))
    }

    fn __hash__(&self) -> isize {
        let mut hasher = FnvHasher::default();
        (*self.type_alias).hash(&mut hasher);
        self.name.as_deref().hash(&mut hasher);
        self.kwargs.get().hash(&mut hasher);
        hasher.finish() as isize
    }
}
