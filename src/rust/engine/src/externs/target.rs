// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::Write;

use crate::externs::address::Address;
use pyo3::basic::CompareOp;
use pyo3::exceptions::PyValueError;
use pyo3::ffi;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::PyType;

pub fn register(m: &PyModule) -> PyResult<()> {
    m.add_class::<Field>()?;
    m.add_class::<NoFieldValue>()?;
    m.add_class::<FieldDefaultValue>()?;
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

#[pyclass]
#[derive(Clone)]
struct FieldDefaultValue {
    value: PyObject,
}

#[pymethods]
impl FieldDefaultValue {
    #[new]
    fn __new__(value: PyObject) -> Self {
        FieldDefaultValue { value }
    }

    fn __str__(self_: &PyCell<Self>) -> PyResult<String> {
        Ok(format!("default({})", self_.borrow().value))
    }

    fn __repr__(self_: &PyCell<Self>) -> PyResult<String> {
        Ok(format!("<FieldDefaultValue({})>", self_.borrow().value))
    }
}

#[pyclass(subclass)]
#[derive(Clone)]
pub struct Field {
    value: PyObject,
    // Overrides the class var default per instance when set.
    default: Option<PyObject>,
}

#[pymethods]
impl Field {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &PyType,
        raw_value: Option<PyObject>,
        address: PyRef<Address>,
        py: Python,
    ) -> PyResult<Self> {
        // NB: The deprecation check relies on the presence of NoFieldValue to detect if
        //  the field was explicitly set, so this must come before we coerce the raw_value
        //  to None below.
        Self::check_deprecated(cls, raw_value.as_ref(), &address, py)?;

        let raw_value = match raw_value {
            Some(value)
                if value.extract::<NoFieldValue>(py).is_ok()
                    && !Self::cls_none_is_valid_value(cls, py)? =>
            {
                None
            }
            rv => rv,
        };
        let maybe_default = match raw_value {
            Some(ref value) => {
                if let Ok(default) = value.extract::<FieldDefaultValue>(py) {
                    Some(default.value)
                } else {
                    None
                }
            }
            _ => None,
        };

        Ok(Self {
            value: cls
                .call_method(intern!(py, "compute_value"), (raw_value, address), None)?
                .into(),
            default: maybe_default,
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
    fn removal_version() -> Option<&'static str> {
        None
    }

    #[classattr]
    fn removal_hint() -> Option<&'static str> {
        None
    }

    #[classattr]
    fn deprecated_alias() -> Option<&'static str> {
        None
    }

    #[classattr]
    fn deprecated_alias_removal_version() -> Option<&'static str> {
        None
    }

    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn compute_value(
        cls: &PyType,
        raw_value: Option<PyObject>,
        address: PyRef<Address>,
        py: Python,
    ) -> PyResult<PyObject> {
        let default = || -> PyResult<PyObject> {
            if Self::cls_required(cls, py)? {
                // TODO: Should be `RequiredFieldMissingException`.
                Err(PyValueError::new_err(format!(
                    "The `{}` field in target {} must be defined.",
                    Self::cls_alias(cls, py)?,
                    *address,
                )))
            } else {
                Self::cls_default(cls, py)
            }
        };

        let none_is_valid_value = Self::cls_none_is_valid_value(cls, py)?;
        match raw_value {
            Some(value) if none_is_valid_value && value.extract::<NoFieldValue>(py).is_ok() => {
                default()
            }
            None if none_is_valid_value => Ok(py.None()),
            None => default(),
            Some(value) => {
                if let Ok(dyn_default) = value.extract::<FieldDefaultValue>(py) {
                    Ok(dyn_default.value)
                } else {
                    Ok(value)
                }
            }
        }
    }

    #[getter]
    fn value(&self) -> &PyObject {
        &self.value
    }

    fn __hash__(self_: &PyCell<Self>, py: Python) -> PyResult<isize> {
        Ok(self_.get_type().hash()? & self_.borrow().value.as_ref(py).hash()?)
    }

    fn __repr__(self_: &PyCell<Self>, py: Python) -> PyResult<String> {
        let mut result = String::new();
        write!(
            result,
            "{}(alias={}, value={}",
            self_.get_type(),
            Self::cls_alias(self_, py)?,
            self_.borrow().value
        )
        .unwrap();
        if let Ok(default) = self_.getattr(intern!(py, "default")) {
            write!(result, ", default={})", default).unwrap();
        } else {
            write!(result, ")").unwrap();
        }
        Ok(result)
    }

    fn __str__(self_: &PyCell<Self>, py: Python) -> PyResult<String> {
        Ok(format!(
            "{}={}",
            Self::cls_alias(self_, py)?,
            self_.borrow().value
        ))
    }

    fn __richcmp__(
        self_: &PyCell<Self>,
        other: &PyAny,
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

    fn __getattribute__<'a>(
        self_: &'a PyCell<Self>,
        name: String,
        py: Python<'a>,
    ) -> PyResult<*mut ffi::PyObject> {
        if name == "default" {
            if let Some(default) = &self_.extract::<Self>()?.default {
                // Return instance default, overriding the field class var default.
                return Ok(default.as_ptr());
            }
        }

        unsafe {
            // The ffi::PyObject_GenericGetAttr() call is unsafe, so we need to be in an unsafe
            // context to call it.
            let slf = self_.borrow_mut().into_ptr();
            let attr = name.into_py(py).into_ptr();
            let res = ffi::PyObject_GenericGetAttr(slf, attr);
            if res.is_null() {
                Err(PyErr::fetch(py))
            } else {
                Ok(res)
            }
        }
    }
}

impl Field {
    fn cls_none_is_valid_value(cls: &PyAny, py: Python) -> PyResult<bool> {
        cls.getattr(intern!(py, "none_is_valid_value"))?
            .extract::<bool>()
    }

    fn cls_default(cls: &PyAny, py: Python) -> PyResult<PyObject> {
        cls.getattr(intern!(py, "default"))?.extract()
    }

    fn cls_required(cls: &PyAny, py: Python) -> PyResult<bool> {
        cls.getattr(intern!(py, "required"))?.extract()
    }

    fn cls_alias<'a>(cls: &'a PyAny, py: Python<'a>) -> PyResult<&'a str> {
        cls.getattr(intern!(py, "alias"))?.extract()
    }

    fn cls_removal_version<'a>(cls: &'a PyAny, py: Python<'a>) -> PyResult<Option<&'a str>> {
        cls.getattr(intern!(py, "removal_version"))?.extract()
    }

    fn cls_removal_hint<'a>(cls: &'a PyAny, py: Python<'a>) -> PyResult<Option<&'a str>> {
        cls.getattr(intern!(py, "removal_hint"))?.extract()
    }

    fn check_deprecated(
        cls: &PyType,
        raw_value: Option<&PyObject>,
        address: &Address,
        py: Python,
    ) -> PyResult<()> {
        if address.is_generated_target() {
            return Ok(());
        }
        let Some(removal_version) = Self::cls_removal_version(cls, py)? else {
            return Ok(());
        };
        match raw_value {
            Some(value) if value.extract::<NoFieldValue>(py).is_ok() => return Ok(()),
            _ => (),
        }

        let Some(removal_hint) = Self::cls_removal_hint(cls, py)? else {
            return Err(PyValueError::new_err(
                "You specified `removal_version` for {cls:?}, but not the class \
             property `removal_hint`.",
            ));
        };

        let alias = Self::cls_alias(cls, py)?;
        let deprecated = PyModule::import(py, intern!(py, "pants.base.deprecated"))?;
        deprecated.getattr(intern!(py, "warn_or_error"))?.call(
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
