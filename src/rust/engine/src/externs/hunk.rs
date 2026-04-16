// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::basic::CompareOp;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::externs::target::util::combine_hashes;
use crate::python::PyComparedBool;

#[pyclass(frozen, module = "pants.engine.internals.native_engine")]
pub struct TextBlock {
    pub start: i64,
    pub count: i64,
}

#[pymethods]
impl TextBlock {
    #[new]
    fn __new__(start: i64, count: i64) -> PyResult<Self> {
        if count < 0 {
            return Err(PyValueError::new_err(format!(
                "self.count={count} can't be negative"
            )));
        }
        Ok(Self { start, count })
    }

    #[getter]
    fn start(&self) -> i64 {
        self.start
    }

    #[getter]
    fn count(&self) -> i64 {
        self.count
    }

    #[getter]
    fn end(&self) -> i64 {
        self.start + self.count
    }

    fn __hash__(&self) -> isize {
        combine_hashes(&[self.start as isize, self.count as isize])
    }

    fn __richcmp__(&self, other: &Self, op: CompareOp) -> PyComparedBool {
        PyComparedBool::eq_ne(op, self.start == other.start && self.count == other.count)
    }

    fn __repr__(&self) -> String {
        format!("TextBlock(start={}, count={})", self.start, self.count)
    }
}

#[pyclass(frozen, module = "pants.engine.internals.native_engine")]
pub struct Hunk {
    left: Option<Py<TextBlock>>,
    right: Option<Py<TextBlock>>,
}

fn text_blocks_eq(a: &Option<Py<TextBlock>>, b: &Option<Py<TextBlock>>) -> bool {
    match (a, b) {
        (Some(a), Some(b)) => {
            let a = a.get();
            let b = b.get();
            a.start == b.start && a.count == b.count
        }
        (None, None) => true,
        _ => false,
    }
}

fn text_block_hash(block: &Option<Py<TextBlock>>) -> isize {
    match block {
        Some(block) => {
            let block = block.get();
            combine_hashes(&[block.start as isize, block.count as isize])
        }
        None => 0,
    }
}

#[pymethods]
impl Hunk {
    #[new]
    #[pyo3(signature = (left, right))]
    fn __new__(left: Option<Bound<'_, TextBlock>>, right: Option<Bound<'_, TextBlock>>) -> Self {
        Self {
            left: left.map(|block| block.unbind()),
            right: right.map(|block| block.unbind()),
        }
    }

    #[getter]
    fn left<'py>(&self, py: Python<'py>) -> Option<Bound<'py, TextBlock>> {
        self.left.as_ref().map(|block| block.bind(py).clone())
    }

    #[getter]
    fn right<'py>(&self, py: Python<'py>) -> Option<Bound<'py, TextBlock>> {
        self.right.as_ref().map(|block| block.bind(py).clone())
    }

    fn __hash__(&self) -> isize {
        combine_hashes(&[text_block_hash(&self.left), text_block_hash(&self.right)])
    }

    fn __richcmp__(&self, other: &Self, op: CompareOp) -> PyComparedBool {
        let is_eq =
            text_blocks_eq(&self.left, &other.left) && text_blocks_eq(&self.right, &other.right);
        PyComparedBool::eq_ne(op, is_eq)
    }

    fn __repr__(&self) -> String {
        let left = match &self.left {
            Some(block) => {
                let block = block.get();
                format!("TextBlock(start={}, count={})", block.start, block.count)
            }
            None => "None".to_string(),
        };
        let right = match &self.right {
            Some(block) => {
                let block = block.get();
                format!("TextBlock(start={}, count={})", block.start, block.count)
            }
            None => "None".to_string(),
        };
        format!("Hunk(left={left}, right={right})")
    }
}

pub fn register(module: &Bound<'_, pyo3::types::PyModule>) -> PyResult<()> {
    module.add_class::<TextBlock>()?;
    module.add_class::<Hunk>()?;
    Ok(())
}
