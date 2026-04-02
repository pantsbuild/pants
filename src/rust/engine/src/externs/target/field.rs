// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::Write;

use pyo3::basic::CompareOp;
use pyo3::exceptions::PyValueError;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::pyclass_init::PyClassInitializer;
use pyo3::types::PyType;

use crate::externs::address::Address;
use crate::python::PyComparedBool;

use super::util::{NoFieldValue, combine_hashes, raise_invalid_field_type, validate_choices};

#[pyclass(subclass, frozen, module = "pants.engine.internals.native_engine")]
pub struct Field {
    value: Py<PyAny>,
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

        let value = cls
            .call_method(intern!(py, "compute_value"), (raw_value, &address), None)?
            .into();

        Ok(Self { value })
    }

    #[classattr]
    fn _raw_value_type() -> &'static str {
        "Any | None"
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
        Ok(combine_hashes(&[
            self_.get_type().hash()?,
            self_.get().value.bind(py).hash()?,
        ]))
    }

    fn __repr__(self_: &Bound<'_, Self>) -> PyResult<String> {
        let mut result = String::new();
        write!(
            result,
            "{}(alias={}, value={}",
            self_.get_type(),
            Self::cls_alias(self_)?,
            self_.get().value
        )
        .unwrap();
        if let Ok(default) = self_.getattr("default") {
            write!(result, ", default={default})").unwrap();
        } else {
            write!(result, ")").unwrap();
        }
        Ok(result)
    }

    fn __str__(self_: &Bound<'_, Self>) -> PyResult<String> {
        Ok(format!("{}={}", Self::cls_alias(self_)?, self_.get().value))
    }

    fn __richcmp__<'py>(
        self_: &Bound<'py, Self>,
        other: &Bound<'py, PyAny>,
        op: CompareOp,
        py: Python,
    ) -> PyResult<PyComparedBool> {
        let is_eq = self_.get_type().eq(other.get_type())?
            && self_
                .get()
                .value
                .bind(py)
                .eq(other.cast::<Field>()?.get().value.bind(py))?;
        Ok(PyComparedBool(match op {
            CompareOp::Eq => Some(is_eq),
            CompareOp::Ne => Some(!is_eq),
            _ => None,
        }))
    }
}

impl Field {
    pub fn init(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Field>> {
        Ok(PyClassInitializer::from(Self::__new__(
            cls, raw_value, address, py,
        )?))
    }

    pub fn cls_none_is_valid_value(cls: &Bound<'_, PyAny>) -> PyResult<bool> {
        cls.getattr("none_is_valid_value")?.extract::<bool>()
    }

    pub fn cls_default<'py>(cls: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        cls.getattr("default")
    }

    pub fn cls_required(cls: &Bound<'_, PyAny>) -> PyResult<bool> {
        cls.getattr("required")?.extract()
    }

    pub fn cls_alias(cls: &Bound<'_, PyAny>) -> PyResult<String> {
        // TODO: All of these methods should use interned attr names.
        cls.getattr("alias")?.extract()
    }

    pub fn cls_removal_version(cls: &Bound<'_, PyAny>) -> PyResult<Option<String>> {
        cls.getattr("removal_version")?.extract()
    }

    pub fn cls_removal_hint(cls: &Bound<'_, PyAny>) -> PyResult<Option<String>> {
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
        let deprecated = PyModule::import(py, "pants.base.deprecated")?;
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

#[pyclass(subclass, frozen, extends = Field, generic, module = "pants.engine.internals.native_engine")]
pub struct ScalarField;

#[pymethods]
impl ScalarField {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Ok(Field::init(cls, raw_value, address, py)?.add_subclass(Self))
    }

    #[classattr]
    fn default<'py>(py: Python<'py>) -> Bound<'py, PyAny> {
        py.None().into_bound(py)
    }

    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn compute_value<'py>(
        cls: &Bound<'py, PyType>,
        raw_value: Option<&Bound<'py, PyAny>>,
        address: Bound<'py, Address>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let value_or_default = Field::compute_value(cls, raw_value, address.extract()?, py)?;
        if !value_or_default.is_none() {
            let expected_type = cls.getattr(intern!(py, "expected_type"))?;
            if !value_or_default.is_instance(&expected_type)? {
                let alias: String = Field::cls_alias(cls)?;
                let expected_type_desc: String = cls
                    .getattr(intern!(py, "expected_type_description"))?
                    .extract()?;
                return Err(raise_invalid_field_type(
                    py,
                    address.as_any(),
                    &alias,
                    raw_value,
                    &expected_type_desc,
                ));
            }
        }
        Ok(value_or_default)
    }
}

#[pyclass(subclass, frozen, extends = ScalarField, module = "pants.engine.internals.native_engine")]
pub struct BoolField;

#[pymethods]
impl BoolField {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Ok(Field::init(cls, raw_value, address, py)?
            .add_subclass(ScalarField)
            .add_subclass(Self))
    }

    #[classattr]
    fn _raw_value_type() -> &'static str {
        "bool"
    }

    #[classattr]
    fn expected_type<'py>(py: Python<'py>) -> Bound<'py, PyType> {
        py.get_type::<pyo3::types::PyBool>()
    }

    #[classattr]
    fn expected_type_description() -> &'static str {
        "a boolean"
    }
}

#[pyclass(subclass, frozen, extends = ScalarField, module = "pants.engine.internals.native_engine")]
pub struct TriBoolField;

#[pymethods]
impl TriBoolField {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Ok(Field::init(cls, raw_value, address, py)?
            .add_subclass(ScalarField)
            .add_subclass(Self))
    }

    #[classattr]
    fn _raw_value_type() -> &'static str {
        "bool | None"
    }

    #[classattr]
    fn expected_type<'py>(py: Python<'py>) -> Bound<'py, PyType> {
        py.get_type::<pyo3::types::PyBool>()
    }

    #[classattr]
    fn expected_type_description() -> &'static str {
        "a boolean or None"
    }
}

#[pyclass(subclass, frozen, extends = ScalarField, module = "pants.engine.internals.native_engine")]
pub struct StringField;

#[pymethods]
impl StringField {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Ok(Field::init(cls, raw_value, address, py)?
            .add_subclass(ScalarField)
            .add_subclass(Self))
    }

    #[classattr]
    fn _raw_value_type() -> &'static str {
        "str | None"
    }

    #[classattr]
    fn expected_type<'py>(py: Python<'py>) -> Bound<'py, PyType> {
        py.get_type::<pyo3::types::PyString>()
    }

    #[classattr]
    fn expected_type_description() -> &'static str {
        "a string"
    }

    #[classattr]
    fn valid_choices<'py>(py: Python<'py>) -> Bound<'py, PyAny> {
        py.None().into_bound(py)
    }

    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn compute_value<'py>(
        cls: &Bound<'py, PyType>,
        raw_value: Option<&Bound<'py, PyAny>>,
        address: Bound<'py, Address>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let value_or_default = ScalarField::compute_value(cls, raw_value, address.clone(), py)?;
        if !value_or_default.is_none() {
            let valid_choices = cls.getattr(intern!(py, "valid_choices"))?;
            if !valid_choices.is_none() {
                let as_list = pyo3::types::PyList::new(py, [&value_or_default])?;
                validate_choices(
                    py,
                    address.as_any(),
                    &Field::cls_alias(cls)?,
                    as_list.as_any(),
                    &valid_choices,
                )?;
            }
        }
        Ok(value_or_default)
    }
}

#[pyclass(subclass, frozen, extends = Field, generic, module = "pants.engine.internals.native_engine")]
pub struct SequenceField;

#[pymethods]
impl SequenceField {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Ok(Field::init(cls, raw_value, address, py)?.add_subclass(Self))
    }

    #[classattr]
    fn _raw_value_type() -> &'static str {
        "Iterable[Any] | None"
    }

    #[classattr]
    fn default<'py>(py: Python<'py>) -> Bound<'py, PyAny> {
        py.None().into_bound(py)
    }

    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn compute_value<'py>(
        cls: &Bound<'py, PyType>,
        raw_value: Option<&Bound<'py, PyAny>>,
        address: Bound<'py, Address>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let value_or_default = Field::compute_value(cls, raw_value, address.extract()?, py)?;
        if value_or_default.is_none() {
            return Ok(value_or_default);
        }
        let expected_element_type = cls.getattr(intern!(py, "expected_element_type"))?;
        if value_or_default.is_instance(&expected_element_type)? {
            let alias = Field::cls_alias(cls)?;
            let desc: String = cls
                .getattr(intern!(py, "expected_type_description"))?
                .extract()?;
            return Err(raise_invalid_field_type(
                py,
                address.as_any(),
                &alias,
                raw_value,
                &desc,
            ));
        }
        let iter = match value_or_default.try_iter() {
            Ok(iter) => iter,
            Err(_) => {
                let alias = Field::cls_alias(cls)?;
                let desc: String = cls
                    .getattr(intern!(py, "expected_type_description"))?
                    .extract()?;
                return Err(raise_invalid_field_type(
                    py,
                    address.as_any(),
                    &alias,
                    raw_value,
                    &desc,
                ));
            }
        };
        let mut elements: Vec<Bound<'py, PyAny>> = Vec::new();
        for item in iter {
            let item = item?;
            if !item.is_instance(&expected_element_type)? {
                let alias = Field::cls_alias(cls)?;
                let desc: String = cls
                    .getattr(intern!(py, "expected_type_description"))?
                    .extract()?;
                return Err(raise_invalid_field_type(
                    py,
                    address.as_any(),
                    &alias,
                    raw_value,
                    &desc,
                ));
            }
            elements.push(item);
        }
        Ok(pyo3::types::PyTuple::new(py, &elements)?.into_any())
    }
}

#[pyclass(subclass, frozen, extends = SequenceField, module = "pants.engine.internals.native_engine")]
pub struct StringSequenceField;

#[pymethods]
impl StringSequenceField {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Ok(Field::init(cls, raw_value, address, py)?
            .add_subclass(SequenceField)
            .add_subclass(Self))
    }

    #[classattr]
    fn _raw_value_type() -> &'static str {
        "Iterable[str] | None"
    }

    #[classattr]
    fn expected_element_type<'py>(py: Python<'py>) -> Bound<'py, PyType> {
        py.get_type::<pyo3::types::PyString>()
    }

    #[classattr]
    fn expected_type_description() -> &'static str {
        "an iterable of strings (e.g. a list of strings)"
    }

    #[classattr]
    fn valid_choices<'py>(py: Python<'py>) -> Bound<'py, PyAny> {
        py.None().into_bound(py)
    }

    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn compute_value<'py>(
        cls: &Bound<'py, PyType>,
        raw_value: Option<&Bound<'py, PyAny>>,
        address: Bound<'py, Address>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let value_or_default = SequenceField::compute_value(cls, raw_value, address.clone(), py)?;
        if !value_or_default.is_none() {
            let valid_choices = cls.getattr(intern!(py, "valid_choices"))?;
            if !valid_choices.is_none() {
                validate_choices(
                    py,
                    address.as_any(),
                    &Field::cls_alias(cls)?,
                    &value_or_default,
                    &valid_choices,
                )?;
            }
        }
        Ok(value_or_default)
    }
}

#[pyclass(subclass, frozen, extends = Field, module = "pants.engine.internals.native_engine")]
pub struct AsyncFieldMixin {
    address: Py<Address>,
}

#[pymethods]
impl AsyncFieldMixin {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Ok(
            Field::init(cls, raw_value, address.clone(), py)?.add_subclass(Self {
                address: address.unbind(),
            }),
        )
    }

    #[getter]
    fn address<'py>(&self, py: Python<'py>) -> Bound<'py, Address> {
        self.address.bind(py).clone()
    }

    fn __repr__(self_: &Bound<Self>) -> PyResult<String> {
        let py = self_.py();
        let cls = self_.get_type();
        let alias: String = Field::cls_alias(&cls)?;
        let value = self_.getattr(intern!(py, "value"))?;
        let address = self_.get().address.bind(py);
        let mut result = String::new();
        write!(
            result,
            "{cls}(alias='{alias}', address={address}, value={value}"
        )
        .unwrap();
        if let Ok(default) = cls.getattr(intern!(py, "default")) {
            write!(result, ", default={default}").unwrap();
        }
        result.push(')');
        Ok(result)
    }

    fn __hash__(self_: &Bound<Self>, py: Python) -> PyResult<isize> {
        Ok(combine_hashes(&[
            self_.get_type().hash()?,
            self_.getattr(intern!(py, "value"))?.hash()?,
            self_.get().address.bind(py).hash()?,
        ]))
    }

    fn __richcmp__<'py>(
        self_: &Bound<'py, Self>,
        other: &Bound<'py, PyAny>,
        op: CompareOp,
        py: Python,
    ) -> PyResult<PyComparedBool> {
        let is_eq = if other.is_instance_of::<AsyncFieldMixin>() {
            let other_afm = other.cast::<AsyncFieldMixin>()?;
            self_.get_type().eq(other.get_type())?
                && self_
                    .getattr(intern!(py, "value"))?
                    .eq(other.getattr(intern!(py, "value"))?)?
                && self_
                    .get()
                    .address
                    .bind(py)
                    .eq(other_afm.get().address.bind(py))?
        } else {
            false
        };
        Ok(PyComparedBool(match op {
            CompareOp::Eq => Some(is_eq),
            CompareOp::Ne => Some(!is_eq),
            _ => None,
        }))
    }
}
