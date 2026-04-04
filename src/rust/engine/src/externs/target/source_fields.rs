// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::OnceLock;

use fs::{GlobExpansionConjunction, StrictGlobMatching};
use pyo3::exceptions::PyValueError;
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;
use pyo3::pyclass_init::PyClassInitializer;
use pyo3::types::{PyRange, PyString, PyTuple, PyType};

use crate::externs::address::Address;
use crate::externs::fs::{PyFilespec, PyFilespecMatcher, PyPathGlobs};
use crate::externs::unions::UnionMembership;

use super::field::{AsyncFieldMixin, Field};
use super::util::{
    GENERATE_SOURCES_REQUEST, PyRepr, PyReprList, import_target_attr, join_path, prefix_glob,
    raise_invalid_field, raise_invalid_field_type, validate_choices,
};

/// Returns (includes, excludes) with paths prefixed by spec_path.
fn split_globs(self_: &Bound<'_, SourcesField>) -> PyResult<(Vec<String>, Vec<String>)> {
    let py = self_.py();
    let globs = self_.getattr(intern!(py, "globs"))?;
    let globs = globs.cast::<PyTuple>()?;
    let async_field_mixin = self_.as_any().cast::<AsyncFieldMixin>()?.get();
    let spec_path = async_field_mixin.address.bind(py).get().spec_path_str();
    let mut includes = Vec::with_capacity(globs.len());
    let mut excludes = Vec::new();
    for item in globs {
        let g = item.cast::<PyString>()?.to_str()?;
        match g.strip_prefix('!') {
            Some(rest) => excludes.push(join_path(spec_path, rest)),
            None => includes.push(join_path(spec_path, g)),
        }
    }
    Ok((includes, excludes))
}

#[pyclass(subclass, frozen, extends = AsyncFieldMixin, module = "pants.engine.internals.native_engine")]
pub struct SourcesField {
    split_globs_cache: OnceLock<(Vec<String>, Vec<String>)>,
    filespec_cache: OnceLock<Py<PyFilespec>>,
    filespec_matcher_cache: OnceLock<Py<PyFilespecMatcher>>,
}

impl SourcesField {
    pub fn init(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<SourcesField>> {
        Ok(
            AsyncFieldMixin::init(cls, raw_value, address, py)?.add_subclass(Self {
                split_globs_cache: OnceLock::new(),
                filespec_cache: OnceLock::new(),
                filespec_matcher_cache: OnceLock::new(),
            }),
        )
    }

    fn cached_split_globs<'py>(
        self_: &'py Bound<'py, Self>,
    ) -> PyResult<&'py (Vec<String>, Vec<String>)> {
        let inner = self_.get();
        if let Some(cached) = inner.split_globs_cache.get() {
            return Ok(cached);
        }
        let result = split_globs(self_)?;
        let _ = inner.split_globs_cache.set(result);
        Ok(inner.split_globs_cache.get().unwrap())
    }
}

#[pymethods]
impl SourcesField {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Self::init(cls, raw_value, address, py)
    }

    #[classattr]
    fn expected_file_extensions<'py>(py: Python<'py>) -> Bound<'py, PyAny> {
        py.None().into_bound(py)
    }

    #[classattr]
    fn expected_num_files<'py>(py: Python<'py>) -> Bound<'py, PyAny> {
        py.None().into_bound(py)
    }

    #[classattr]
    fn uses_source_roots() -> bool {
        true
    }

    #[classattr]
    fn default<'py>(py: Python<'py>) -> Bound<'py, PyAny> {
        py.None().into_bound(py)
    }

    #[classattr]
    fn default_glob_match_error_behavior<'py>(py: Python<'py>) -> Bound<'py, PyAny> {
        py.None().into_bound(py)
    }

    #[getter]
    fn globs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        Ok(PyTuple::empty(py))
    }

    fn validate_resolved_files(self_: &Bound<'_, Self>, files: Vec<PyBackedStr>) -> PyResult<()> {
        let py = self_.py();
        let cls = self_.get_type();
        let afm = self_.as_any().cast::<AsyncFieldMixin>()?.get();
        let address = afm.address.bind(py);

        let ext_obj = cls.getattr(intern!(py, "expected_file_extensions"))?;
        if !ext_obj.is_none() {
            let extensions: Vec<PyBackedStr> = ext_obj.extract()?;
            let mut bad_files: Vec<&str> = files
                .iter()
                .filter(|fp| {
                    let suffix = fp.rfind('.').map(|i| &fp[i..]).unwrap_or("");
                    !extensions.iter().any(|e| &**e == suffix)
                })
                .map(|s| s.as_ref())
                .collect();
            if !bad_files.is_empty() {
                bad_files.sort();
                let alias = Field::cls_alias(&cls)?;
                let alias_repr = PyRepr(&alias);
                let expected = if extensions.len() > 1 {
                    let mut sorted: Vec<&str> = extensions.iter().map(|e| e.as_ref()).collect();
                    sorted.sort();
                    format!("one of {}", PyReprList(&sorted))
                } else {
                    format!("{}", PyRepr(extensions[0].as_ref()))
                };
                return Err(raise_invalid_field(
                    py,
                    format!(
                        "The {alias_repr} field in target {address} can only contain \
                         files that end in {expected}, but it had these files: {}.\n\n\
                         Maybe create a `resource`/`resources` or `file`/`files` target and \
                         include it in the `dependencies` field?",
                        PyReprList(&bad_files),
                    ),
                ));
            }
        }

        let num_obj = cls.getattr(intern!(py, "expected_num_files"))?;
        if !num_obj.is_none() {
            let num_files = files.len();
            let expected_str = if num_obj.is_instance_of::<pyo3::types::PyInt>() {
                let expected: usize = num_obj.extract()?;
                if num_files == expected {
                    None
                } else {
                    let pluralize = py.import("pants.util.strutil")?.getattr("pluralize")?;
                    Some(pluralize.call1((expected, "file"))?.extract::<String>()?)
                }
            } else if num_obj.contains(num_files)? {
                None
            } else {
                let range_len: usize = num_obj.len()?;
                Some(if range_len == 2 {
                    let items: Vec<usize> = num_obj
                        .try_iter()?
                        .map(|i| i?.extract())
                        .collect::<PyResult<_>>()?;
                    format!("{} or {} files", items[0], items[1])
                } else {
                    format!("a number of files in the range `{num_obj}`")
                })
            };
            if let Some(expected_str) = expected_str {
                let alias = Field::cls_alias(&cls)?;
                let alias_repr = PyRepr(&alias);
                let pluralize = py.import("pants.util.strutil")?.getattr("pluralize")?;
                let num_str: String = pluralize.call1((num_files, "file"))?.extract()?;
                return Err(raise_invalid_field(
                    py,
                    format!(
                        "The {alias_repr} field in target {address} must have \
                         {expected_str}, but it had {num_str}.",
                    ),
                ));
            }
        }

        Ok(())
    }

    #[staticmethod]
    fn prefix_glob_with_dirpath(dirpath: &str, glob: &str) -> String {
        prefix_glob(dirpath, glob)
    }

    fn _prefix_glob_with_address(self_: &Bound<'_, Self>, glob: &str) -> PyResult<String> {
        let afm = self_.as_any().cast::<AsyncFieldMixin>()?.get();
        let sp = afm.address.bind(self_.py()).get().spec_path_str();
        Ok(prefix_glob(sp, glob))
    }

    fn path_globs<'py>(
        self_: &Bound<'py, Self>,
        unmatched_build_file_globs: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyPathGlobs>> {
        let py = self_.py();
        let globs: Vec<PyBackedStr> = self_.getattr(intern!(py, "globs"))?.extract()?;

        if globs.is_empty() {
            return Bound::new(
                py,
                PyPathGlobs::new(
                    Vec::new(),
                    StrictGlobMatching::Ignore,
                    GlobExpansionConjunction::AnyMatch,
                ),
            );
        }

        let cls = self_.get_type();

        let default_obj = cls.getattr(intern!(py, "default"))?;
        let using_default_globs = if default_obj.is_none() {
            false
        } else {
            let set_type = py.get_type::<pyo3::types::PySet>();
            let globs_obj = self_.getattr(intern!(py, "globs"))?;
            let globs_set = set_type.call1((&globs_obj,))?;
            let default_set = if default_obj.is_instance_of::<PyString>() {
                set_type.call1(((default_obj,),))?
            } else {
                set_type.call1((&default_obj,))?
            };
            globs_set.eq(&default_set)?
        };

        let default_gmeb = cls.getattr(intern!(py, "default_glob_match_error_behavior"))?;
        let error_behavior = if !using_default_globs || default_gmeb.is_none() {
            unmatched_build_file_globs.getattr(intern!(py, "error_behavior"))?
        } else {
            default_gmeb
        };

        let behavior_value: PyBackedStr =
            error_behavior.getattr(intern!(py, "value"))?.extract()?;
        let afm = self_.as_any().cast::<AsyncFieldMixin>()?.get();
        let sp = afm.address.bind(py).get().spec_path_str();
        let prefixed: Vec<String> = globs.iter().map(|g| prefix_glob(sp, g)).collect();

        let description_of_origin = if &*behavior_value == "ignore" {
            None
        } else {
            let alias = Field::cls_alias(&cls)?;
            let address = afm.address.bind(py);
            Some(format!("{address}'s `{alias}` field"))
        };

        let strict = StrictGlobMatching::create(&behavior_value, description_of_origin)
            .map_err(PyValueError::new_err)?;

        Bound::new(
            py,
            PyPathGlobs::new(prefixed, strict, GlobExpansionConjunction::AnyMatch),
        )
    }

    #[getter]
    fn filespec<'py>(self_: &Bound<'py, Self>, py: Python<'py>) -> PyResult<Py<PyFilespec>> {
        let inner = self_.get();
        if let Some(cached) = inner.filespec_cache.get() {
            return Ok(cached.clone_ref(py));
        }

        let (includes, excludes) = Self::cached_split_globs(self_)?;
        let result = Py::new(py, PyFilespec::new(includes.clone(), excludes.clone()))?;
        let _ = inner.filespec_cache.set(result.clone_ref(py));
        Ok(result)
    }

    #[getter]
    fn filespec_matcher<'py>(
        self_: &Bound<'py, Self>,
        py: Python<'py>,
    ) -> PyResult<Py<PyFilespecMatcher>> {
        let inner = self_.get();
        if let Some(cached) = inner.filespec_matcher_cache.get() {
            return Ok(cached.clone_ref(py));
        }

        let (includes, excludes) = Self::cached_split_globs(self_)?;
        let result = Py::new(
            py,
            PyFilespecMatcher::from_vecs(includes.clone(), excludes.clone(), py)?,
        )?;
        let _ = inner.filespec_matcher_cache.set(result.clone_ref(py));
        Ok(result)
    }

    #[classmethod]
    fn can_generate(
        cls: &Bound<'_, PyType>,
        output_type: &Bound<'_, PyType>,
        union_membership: &Bound<'_, UnionMembership>,
    ) -> PyResult<bool> {
        let py = cls.py();
        let gsr: Bound<'_, PyType> =
            import_target_attr(py, &GENERATE_SOURCES_REQUEST, "GenerateSourcesRequest")?
                .extract()?;
        let Some(members) = union_membership.get().get_members(&gsr) else {
            return Ok(false);
        };
        for member in members?.try_iter()? {
            let member = member?;
            let input: Bound<'_, PyType> = member.getattr(intern!(py, "input"))?.extract()?;
            let output: Bound<'_, PyType> = member.getattr(intern!(py, "output"))?.extract()?;
            if cls.is_subclass(&input)? && output.is_subclass(output_type)? {
                return Ok(true);
            }
        }
        Ok(false)
    }
}

#[pyclass(subclass, frozen, extends = SourcesField, module = "pants.engine.internals.native_engine")]
pub struct MultipleSourcesField;

impl MultipleSourcesField {
    pub fn init(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<MultipleSourcesField>> {
        Ok(SourcesField::init(cls, raw_value, address, py)?.add_subclass(Self))
    }
}

#[pymethods]
impl MultipleSourcesField {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Self::init(cls, raw_value, address, py)
    }

    #[classattr]
    fn alias() -> &'static str {
        "sources"
    }

    #[classattr]
    fn _raw_value_type() -> &'static str {
        "Iterable[str] | None"
    }

    #[classattr]
    fn ban_subdirectories() -> bool {
        false
    }

    #[classattr]
    fn valid_choices<'py>(py: Python<'py>) -> Bound<'py, PyAny> {
        py.None().into_bound(py)
    }

    #[getter]
    fn globs<'py>(self_: &Bound<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let value = self_.getattr(intern!(py, "value"))?;
        if value.is_none() {
            Ok(PyTuple::empty(py).into_any())
        } else {
            Ok(value)
        }
    }

    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn compute_value<'py>(
        cls: &Bound<'py, PyType>,
        raw_value: Option<&Bound<'py, PyAny>>,
        address: Bound<'py, Address>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let value_or_default =
            Field::compute_value_from_bound(cls, raw_value, address.clone(), py)?;
        if value_or_default.is_none() {
            return Ok(value_or_default);
        }

        let str_type = py.get_type::<PyString>();

        if value_or_default.is_instance(&str_type)? {
            return Err(raise_invalid_field_type(
                py,
                address.as_any(),
                &Field::cls_alias(cls)?,
                raw_value,
                "an iterable of strings (e.g. a list of strings)",
            ));
        }
        let iter = value_or_default.try_iter().map_err(|_| {
            raise_invalid_field_type(
                py,
                address.as_any(),
                Field::cls_alias(cls).as_deref().unwrap_or(""),
                raw_value,
                "an iterable of strings (e.g. a list of strings)",
            )
        })?;

        let mut py_items: Vec<Bound<'py, PyAny>> = Vec::new();
        let mut strs: Vec<PyBackedStr> = Vec::new();
        for item in iter {
            let item = item?;
            if !item.is_instance(&str_type)? {
                return Err(raise_invalid_field_type(
                    py,
                    address.as_any(),
                    Field::cls_alias(cls).as_deref().unwrap_or(""),
                    raw_value,
                    "an iterable of strings (e.g. a list of strings)",
                ));
            }
            strs.push(item.extract::<PyBackedStr>()?);
            py_items.push(item);
        }
        let value = PyTuple::new(py, &py_items)?.into_any();

        if strs
            .iter()
            .any(|g| g.starts_with("../") || g.contains("/../"))
        {
            strs.sort();
            let alias = Field::cls_alias(cls)?;
            return Err(raise_invalid_field(
                py,
                format!(
                    "The {} field in target {address} must not have globs with the \
                     pattern `../` because targets can only have sources in the current directory \
                     or subdirectories. It was set to: {}",
                    PyRepr(&alias),
                    PyReprList(&strs),
                ),
            ));
        }

        if cls
            .getattr(intern!(py, "ban_subdirectories"))?
            .is_truthy()?
            && strs
                .iter()
                .any(|g| g.contains("**") || g.contains(std::path::MAIN_SEPARATOR))
        {
            strs.sort();
            let alias = Field::cls_alias(cls)?;
            let sep = std::path::MAIN_SEPARATOR;
            return Err(raise_invalid_field(
                py,
                format!(
                    "The {} field in target {address} must only have globs for \
                     the target's directory, i.e. it cannot include values with `**` or \
                     `{sep}`. It was set to: {}",
                    PyRepr(&alias),
                    PyReprList(&strs),
                ),
            ));
        }

        let valid = cls.getattr(intern!(py, "valid_choices"))?;
        if !valid.is_none() {
            validate_choices(
                py,
                address.as_any(),
                &Field::cls_alias(cls)?,
                &value,
                &valid,
            )?;
        }

        Ok(value)
    }
}

#[pyclass(subclass, frozen, extends = SourcesField, module = "pants.engine.internals.native_engine")]
pub struct OptionalSingleSourceField;

impl OptionalSingleSourceField {
    pub fn init(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<OptionalSingleSourceField>> {
        Ok(SourcesField::init(cls, raw_value, address, py)?.add_subclass(Self))
    }
}

#[pymethods]
impl OptionalSingleSourceField {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Self::init(cls, raw_value, address, py)
    }

    #[classattr]
    fn alias() -> &'static str {
        "source"
    }

    #[classattr]
    fn _raw_value_type() -> &'static str {
        "str | None"
    }

    #[classattr]
    fn required() -> bool {
        false
    }

    #[classattr]
    fn expected_num_files<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        Ok(PyRange::new(py, 0, 2)?.into_any())
    }

    #[classattr]
    fn help() -> &'static str {
        "A single file that belongs to this target.\n\n\
         Path is relative to the BUILD file's directory, e.g. `source='example.ext'`."
    }

    #[classattr]
    fn valid_choices<'py>(py: Python<'py>) -> Bound<'py, PyAny> {
        py.None().into_bound(py)
    }

    #[getter]
    fn globs<'py>(self_: &Bound<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        let value = self_.getattr(intern!(py, "value"))?;
        if value.is_none() {
            Ok(PyTuple::empty(py))
        } else {
            PyTuple::new(py, [value])
        }
    }

    #[getter]
    fn file_path(self_: &Bound<'_, Self>) -> PyResult<Py<PyAny>> {
        let py = self_.py();
        let value = self_.getattr(intern!(py, "value"))?;
        if value.is_none() {
            return Ok(py.None());
        }
        let value_str = value.cast::<PyString>()?.to_str()?;
        let afm = self_.as_any().cast::<AsyncFieldMixin>()?.get();
        let sp = afm.address.bind(py).get().spec_path_str();
        if sp.is_empty() {
            Ok(value.unbind())
        } else {
            Ok(PyString::new(py, &format!("{sp}/{value_str}"))
                .into_any()
                .unbind())
        }
    }

    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn compute_value<'py>(
        cls: &Bound<'py, PyType>,
        raw_value: Option<&Bound<'py, PyAny>>,
        address: Bound<'py, Address>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let value_or_default =
            Field::compute_value_from_bound(cls, raw_value, address.clone(), py)?;
        if value_or_default.is_none() {
            return Ok(value_or_default);
        }

        let s = value_or_default.cast::<PyString>().map_err(|_| {
            raise_invalid_field_type(
                py,
                address.as_any(),
                Field::cls_alias(cls).as_deref().unwrap_or(""),
                raw_value,
                "a string",
            )
        })?;

        let valid = cls.getattr(intern!(py, "valid_choices"))?;
        if !valid.is_none() {
            let alias = Field::cls_alias(cls)?;
            let as_list = pyo3::types::PyList::new(py, [&value_or_default])?;
            validate_choices(py, address.as_any(), &alias, as_list.as_any(), &valid)?;
        }

        let value_str = s.to_str()?;
        if value_str.starts_with("../") || value_str.contains("/../") {
            let alias = Field::cls_alias(cls)?;
            return Err(raise_invalid_field(
                py,
                format!(
                    "The {} field in target {address} should not include `../` \
                     patterns because targets can only have sources in the current directory or \
                     subdirectories. It was set to {value_str}. Instead, use a normalized \
                     literal file path (relative to the BUILD file).",
                    PyRepr(&alias),
                ),
            ));
        }

        if value_str.contains('*') {
            let alias = Field::cls_alias(cls)?;
            return Err(raise_invalid_field(
                py,
                format!(
                    "The {} field in target {address} should not include `*` globs, \
                     but was set to {value_str}. Instead, use a literal file path (relative \
                     to the BUILD file).",
                    PyRepr(&alias),
                ),
            ));
        }

        if value_str.starts_with('!') {
            let alias = Field::cls_alias(cls)?;
            return Err(raise_invalid_field(
                py,
                format!(
                    "The {} field in target {address} should not start with `!`, \
                     which is usually used in the `sources` field to exclude certain files. \
                     Instead, use a literal file path (relative to the BUILD file).",
                    PyRepr(&alias),
                ),
            ));
        }

        Ok(value_or_default)
    }
}

#[pyclass(subclass, frozen, extends = OptionalSingleSourceField, module = "pants.engine.internals.native_engine")]
pub struct SingleSourceField;

#[pymethods]
impl SingleSourceField {
    #[new]
    #[classmethod]
    #[pyo3(signature = (raw_value, address))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        raw_value: Option<&Bound<'_, PyAny>>,
        address: Bound<'_, Address>,
        py: Python,
    ) -> PyResult<PyClassInitializer<Self>> {
        Ok(OptionalSingleSourceField::init(cls, raw_value, address, py)?.add_subclass(Self))
    }

    #[classattr]
    fn required() -> bool {
        true
    }

    #[classattr]
    fn expected_num_files() -> i32 {
        1
    }

    #[getter]
    fn file_path(self_: &Bound<'_, Self>) -> PyResult<String> {
        let py = self_.py();
        let value_str = self_
            .getattr(intern!(py, "value"))?
            .cast_into::<PyString>()?
            .to_str()?
            .to_owned();
        let afm = self_.as_any().cast::<AsyncFieldMixin>()?.get();
        let sp = afm.address.bind(py).get().spec_path_str();
        if sp.is_empty() {
            Ok(value_str)
        } else {
            Ok(format!("{sp}/{value_str}"))
        }
    }
}
