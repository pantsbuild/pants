// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::Write;

use pyo3::basic::CompareOp;
use pyo3::exceptions::PyValueError;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::PyType;

use crate::externs::address::Address;

pub fn register(m: &PyModule) -> PyResult<()> {
    m.add_class::<Field>()?;
    m.add_class::<NoFieldValue>()?;

    m.add("NO_VALUE", NoFieldValue)?;

    Ok(())
}

#[pyclass(name = "_NoValue")]
#[derive(Clone)]
struct NoFieldValue;

#[pymethods]
impl NoFieldValue {
    fn __bool__(&self) -> bool {
        false
    }

    fn __repr__(&self) -> &'static str {
        "<NO_VALUE>"
    }
}

#[pyclass(subclass)]
pub struct Field {
    value: PyObject,
}

#[pymethods]
impl Field {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<Self> {
        // NB: The deprecation check relies on the presence of NoFieldValue to detect if
        //  the field was explicitly set, so this must come before we coerce the raw_value
        //  to None below.
        Self::check_deprecated(cls, raw_value, &address, py)?;

        let raw_value = match raw_value {
            Some(value)
                if value.extract::<NoFieldValue>().is_ok()
                    && !Self::cls_none_is_valid_value(cls)? =>
            {
                None
            }
            rv => rv,
        };

        Ok(Self {
            value: cls
                .call_method(intern!(py, "compute_value"), (raw_value, address), None)?
                .into(),
        })
    }

    #[classattr]
    fn none_is_valid_value() -> bool {
        false
    }

    #[classattr]
    fn required() -> bool {
        false
    }

    #[classattr]
    fn removal_version() -> Option<String> {
        None
    }

    #[classattr]
    fn removal_hint() -> Option<String> {
        None
    }

    #[classattr]
    fn deprecated_alias() -> Option<String> {
        None
    }

    #[classattr]
    fn deprecated_alias_removal_version() -> Option<String> {
        None
    }

    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn compute_value<'py>(
        cls: &Bound<'py, PyType>,
        raw_value: Option<&Bound<'py, PyAny>>,
        address: PyRef<Address>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let default = || -> PyResult<Bound<'_, PyAny>> {
            if Self::cls_required(cls)? {
                // TODO: Should be `RequiredFieldMissingException`.
                Err(PyValueError::new_err(format!(
                    "The `{}` field in target {} must be defined.",
                    Self::cls_alias(cls)?,
                    *address,
                )))
            } else {
                Self::cls_default(cls)
            }
        };

        let none_is_valid_value = Self::cls_none_is_valid_value(cls)?;
        match raw_value {
            Some(value) if none_is_valid_value && value.extract::<NoFieldValue>().is_ok() => {
                default()
            }
            None if none_is_valid_value => Ok(py.None().into_bound(py)),
            None => default(),
            Some(value) => Ok(value.clone()),
        }
    }

    #[getter]
    fn value<'py>(&self, py: Python<'py>) -> Bound<'py, PyAny> {
        self.value.bind(py).clone()
    }

    fn __hash__(self_: &Bound<'_, Self>, py: Python) -> PyResult<isize> {
        Ok(self_.get_type().hash()? & self_.borrow().value.as_ref(py).hash()?)
    }

    fn __repr__(self_: &Bound<'_, Self>) -> PyResult<String> {
        let mut result = String::new();
        write!(
            result,
            "{}(alias={}, value={}",
            self_.get_type(),
            Self::cls_alias(self_)?,
            self_.borrow().value
        )
        .unwrap();
        if let Ok(default) = self_.getattr("default") {
            write!(result, ", default={})", default).unwrap();
        } else {
            write!(result, ")").unwrap();
        }
        Ok(result)
    }

    fn __str__(self_: &Bound<'_, Self>) -> PyResult<String> {
        Ok(format!(
            "{}={}",
            Self::cls_alias(self_)?,
            self_.borrow().value
        ))
    }

    fn __richcmp__(
        self_: &Bound<'_, Self>,
        other: &Bound<'_, PyAny>,
        op: CompareOp,
        py: Python,
    ) -> PyResult<PyObject> {
        let is_eq = self_.get_type().eq(other.get_type())?
            && self_
                .borrow()
                .value
                .as_ref(py)
                .eq(&other.extract::<PyRef<Field>>()?.value)?;
        match op {
            CompareOp::Eq => Ok(is_eq.into_py(py)),
            CompareOp::Ne => Ok((!is_eq).into_py(py)),
            _ => Ok(py.NotImplemented()),
        }
    }
}

impl Field {
    fn cls_none_is_valid_value(cls: &Bound<'_, PyAny>) -> PyResult<bool> {
        cls.getattr("none_is_valid_value")?.extract::<bool>()
    }

    fn cls_default<'py>(cls: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        cls.getattr("default")
    }

    fn cls_required(cls: &Bound<'_, PyAny>) -> PyResult<bool> {
        cls.getattr("required")?.extract()
    }

    fn cls_alias(cls: &Bound<'_, PyAny>) -> PyResult<String> {
        // TODO: All of these methods should use interned attr names.
        cls.getattr("alias")?.extract()
    }

    fn cls_removal_version(cls: &Bound<'_, PyAny>) -> PyResult<Option<String>> {
        cls.getattr("removal_version")?.extract()
    }

    fn cls_removal_hint(cls: &Bound<'_, PyAny>) -> PyResult<Option<String>> {
        cls.getattr("removal_hint")?.extract()
    }

    fn check_deprecated(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: &Bound<'_, Address>,
        py: Python,
    ) -> PyResult<()> {
        if address.borrow().is_generated_target() {
            return Ok(());
        }
        let Some(removal_version) = Self::cls_removal_version(cls)? else {
            return Ok(());
        };
        match raw_value {
            Some(value) if value.extract::<NoFieldValue>().is_ok() => return Ok(()),
            _ => (),
        }

        let Some(removal_hint) = Self::cls_removal_hint(cls)? else {
            return Err(PyValueError::new_err(
                "You specified `removal_version` for {cls:?}, but not the class \
             property `removal_hint`.",
            ));
        };

        let alias = Self::cls_alias(cls)?;
        let deprecated = PyModule::import_bound(py, "pants.base.deprecated")?;
        deprecated.getattr("warn_or_error")?.call(
            (
                removal_version,
                format!("the {alias} field"),
                format!("Using the `{alias}` field in the target {address}. {removal_hint}"),
            ),
            None,
        )?;
        Ok(())
    }
}
