// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, HashMap};
use std::hash::{Hash, Hasher};
use std::path::PathBuf;

use options::fromfile::FromfileExpander;
use options::{BuildRoot, Env, ListOptionValue, OptionId, Scope, Val};
use options_pants_ng::options::{Options, OptionsReader};
use options_pants_ng::pants_invocation::{Args, Flag, PantsInvocation};
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::externs::options::{
    OptionValue, PyConfigSource, PyDictVal, PyOptionId, condense_dict_value_derivation,
    condense_list_value_derivation, dict_into_py, into_py, py_object_to_val,
};

pyo3::import_exception!(pants.option.errors, ParseError);

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyNgInvocation>()?;
    m.add_class::<PyNgOptionsReader>()?;
    m.add_class::<PyNgOptions>()?;
    m.add_class::<PyNgSourcePartition>()?;
    Ok(())
}

#[pyclass]
struct PyNgInvocation(PantsInvocation);

#[pyclass(eq, frozen, hash)]
#[derive(Eq, Hash, PartialEq)]
pub struct PyNgOptionsReader(pub OptionsReader);

// There is repetition below of similar code for PyOptionParser in externs/options.rs.
// This is necessary because we don't want to reuse that class directly (it has various
// unhelpful restrictions, such as not being able to implement Hash+Eq due to dyn compatibility).

#[allow(clippy::type_complexity)]
impl PyNgOptionsReader {
    fn get_list<'py, T: ToOwned + ?Sized, F>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<T::Owned>,
        getter: F,
    ) -> PyResult<OptionValue<'py, Vec<T::Owned>>>
    where
        F: Fn(
            &'py OptionsReader,
            &OptionId,
            Vec<T::Owned>,
        ) -> Result<ListOptionValue<'py, T::Owned>, String>,
        <T as ToOwned>::Owned: PartialEq,
    {
        let opt_val =
            getter(&self.0, &option_id.borrow().0, default).map_err(ParseError::new_err)?;
        Ok((
            Some(opt_val.value),
            opt_val.source.rank() as isize,
            opt_val
                .derivation
                .map(|d| condense_list_value_derivation(py, d)),
        ))
    }
}

#[pymethods]
impl PyNgOptionsReader {
    #[new]
    #[pyo3(signature = (buildroot, flags, env, configs))]
    // Ctor useful for Python tests.
    fn __new__<'py>(
        buildroot: PathBuf,
        flags: HashMap<String, HashMap<String, Vec<Option<String>>>>,
        env: &Bound<'py, PyDict>,
        configs: Vec<Bound<'py, PyConfigSource>>,
    ) -> PyResult<Self> {
        let flags = flags
            .into_iter()
            .map(|(k, v)| (Scope::named(&k), v))
            .collect();
        let env = Env::new(
            env.items()
                .into_iter()
                .map(|kv_pair| kv_pair.extract::<(String, String)>())
                .collect::<Result<BTreeMap<_, _>, _>>()?,
        );
        let configs = configs
            .iter()
            .map(|c| (c.borrow().0.clone(), None))
            .collect();
        OptionsReader::new(
            &FromfileExpander::relative_to(BuildRoot::for_path(buildroot)),
            flags,
            &env,
            configs,
        )
        .map(Self)
        .map_err(ParseError::new_err)
    }

    #[pyo3(signature = (option_id, default))]
    fn get_bool<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<bool>,
    ) -> PyResult<OptionValue<'py, bool>> {
        into_py(
            py,
            self.0.parse_bool_optional(&option_id.borrow().0, default),
        )
    }

    #[pyo3(signature = (option_id, default))]
    fn get_int<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<i64>,
    ) -> PyResult<OptionValue<'py, i64>> {
        into_py(
            py,
            self.0.parse_int_optional(&option_id.borrow().0, default),
        )
    }

    #[pyo3(signature = (option_id, default))]
    fn get_float<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<f64>,
    ) -> PyResult<OptionValue<'py, f64>> {
        into_py(
            py,
            self.0.parse_float_optional(&option_id.borrow().0, default),
        )
    }

    #[pyo3(signature = (option_id, default))]
    fn get_string<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<&str>,
    ) -> PyResult<OptionValue<'py, String>> {
        into_py(
            py,
            self.0.parse_string_optional(&option_id.borrow().0, default),
        )
    }

    fn get_bool_list<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<bool>,
    ) -> PyResult<OptionValue<'py, Vec<bool>>> {
        self.get_list::<bool, _>(py, option_id, default, |op, oid, def| {
            op.parse_bool_list(oid, def)
        })
    }

    fn get_int_list<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<i64>,
    ) -> PyResult<OptionValue<'py, Vec<i64>>> {
        self.get_list::<i64, _>(py, option_id, default, |op, oid, def| {
            op.parse_int_list(oid, def)
        })
    }

    fn get_float_list<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<f64>,
    ) -> PyResult<OptionValue<'py, Vec<f64>>> {
        self.get_list::<f64, _>(py, option_id, default, |op, oid, def| {
            op.parse_float_list(oid, def)
        })
    }

    fn get_string_list<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<String>,
    ) -> PyResult<OptionValue<'py, Vec<String>>> {
        self.get_list::<String, _>(py, option_id, default, |op, oid, def| {
            op.parse_string_list(oid, def)
        })
    }

    fn get_dict<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: &Bound<'_, PyDict>,
    ) -> PyResult<OptionValue<'py, PyDictVal>> {
        let default = default
            .items()
            .into_iter()
            .map(|kv_pair| {
                let (k, v) = kv_pair.extract::<(String, Bound<'_, PyAny>)>()?;
                Ok::<(String, Val), PyErr>((k, py_object_to_val(&v)?))
            })
            .collect::<Result<HashMap<_, _>, _>>()?;

        let opt_val = self
            .0
            .parse_dict(&option_id.borrow().0, default)
            .map_err(ParseError::new_err)?;
        let opt_val_py = dict_into_py(py, opt_val.value)?;

        Ok((
            Some(opt_val_py),
            opt_val.source.rank() as isize,
            match opt_val.derivation {
                Some(d) => Some(condense_dict_value_derivation(py, d)?),
                None => None,
            },
        ))
    }
}

#[pyclass(eq, frozen, hash)]
#[derive(Eq, Hash, PartialEq)]
struct PyNgOptions(Options);

// A set of source files and the reader for the options pertaining to those files.
#[pyclass(eq, frozen, hash)]
struct PyNgSourcePartition {
    pub paths: Vec<PathBuf>,
    pub options_reader: Py<PyNgOptionsReader>,
}

impl PartialEq for PyNgSourcePartition {
    fn eq(&self, other: &Self) -> bool {
        Python::attach(|py| {
            self.paths == other.paths
                && self.options_reader.borrow(py).0 == other.options_reader.borrow(py).0
        })
    }
}

impl Eq for PyNgSourcePartition {}

impl Hash for PyNgSourcePartition {
    fn hash<H: Hasher>(&self, state: &mut H) {
        Python::attach(|py| {
            self.paths.hash(state);
            self.options_reader.borrow(py).0.hash(state);
        });
    }
}

pyo3::import_exception!(pants.option.errors, OptionsError);

#[pymethods]
impl PyNgInvocation {
    #[staticmethod]
    fn empty() -> Self {
        Self(PantsInvocation::empty())
    }

    #[staticmethod]
    #[pyo3(signature = (args))]
    fn from_args(args: Vec<String>) -> PyResult<Self> {
        PantsInvocation::from_args(Args::new(args))
            .map(Self)
            .map_err(OptionsError::new_err)
    }

    #[pyo3(signature = ())]
    fn global_flag_strings(&self) -> Vec<String> {
        self.0
            .global_flags
            .iter()
            .map(Flag::to_arg_string)
            .collect()
    }

    #[pyo3(signature = ())]
    fn specs(&self) -> &Vec<String> {
        &self.0.specs
    }

    #[pyo3(signature = ())]
    fn goals(&self) -> Vec<String> {
        self.0.goals()
    }

    #[pyo3(signature = ())]
    fn passthru(&self) -> &Option<Vec<String>> {
        &self.0.passthru
    }
}

#[pymethods]
impl PyNgOptions {
    #[new]
    #[pyo3(signature = (pants_invocation, env, include_derivation))]
    fn __new__<'py>(
        pants_invocation: &Bound<'py, PyNgInvocation>,
        env: &Bound<'py, PyDict>,
        include_derivation: bool,
    ) -> PyResult<Self> {
        let env = env
            .items()
            .into_iter()
            .map(|kv_pair| kv_pair.extract::<(String, String)>())
            .collect::<Result<BTreeMap<_, _>, _>>()?;

        Options::new(
            &pants_invocation.borrow().0,
            Env::new(env),
            None,
            None,
            include_derivation,
        )
        .map(Self)
        .map_err(OptionsError::new_err)
    }

    #[pyo3(signature = (dir))]
    fn get_options_reader_for_dir(&self, dir: &str) -> PyResult<PyNgOptionsReader> {
        self.0
            .get_options_reader_for_dir(&PathBuf::from(dir))
            .map(PyNgOptionsReader)
            .map_err(OptionsError::new_err)
    }

    #[pyo3(signature = (paths))]
    fn partition_sources(
        &self,
        py: Python,
        paths: Vec<String>,
    ) -> PyResult<Vec<PyNgSourcePartition>> {
        self.0
            .partition_sources(paths.into_iter().map(PathBuf::from).collect())
            .map_err(OptionsError::new_err)
            .map(|partitions| {
                partitions
                    .into_iter()
                    .map(|partition| {
                        PyResult::Ok(PyNgSourcePartition {
                            paths: partition.paths,
                            options_reader: Py::new(
                                py,
                                PyNgOptionsReader(partition.options_reader),
                            )?,
                        })
                    })
                    .collect()
            })?
    }
}

#[pymethods]
impl PyNgSourcePartition {
    #[pyo3(signature = ())]
    fn paths(&self) -> &Vec<PathBuf> {
        &self.paths
    }

    #[pyo3(signature = ())]
    fn options_reader<'py>(&'py self, py: Python<'py>) -> PyRef<'py, PyNgOptionsReader> {
        self.options_reader.borrow(py)
    }
}
