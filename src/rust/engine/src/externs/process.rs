// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyAssertionError, PyValueError};
use pyo3::prelude::*;

use process_execution::{Platform, ProcessExecutionEnvironment, ProcessExecutionStrategy};

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyProcessExecutionEnvironment>()?;

    Ok(())
}

#[pyclass(name = "ProcessExecutionEnvironment")]
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct PyProcessExecutionEnvironment {
    pub environment: ProcessExecutionEnvironment,
}

#[pymethods]
impl PyProcessExecutionEnvironment {
    #[new]
    #[pyo3(signature = (platform, remote_execution, remote_execution_extra_platform_properties, execute_in_workspace, environment_name=None, docker_image=None))]
    fn __new__(
        platform: String,
        remote_execution: bool,
        remote_execution_extra_platform_properties: Vec<(String, String)>,
        execute_in_workspace: bool,
        environment_name: Option<String>,
        docker_image: Option<String>,
    ) -> PyResult<Self> {
        let platform = Platform::try_from(platform).map_err(PyValueError::new_err)?;
        let strategy = match (docker_image, remote_execution, execute_in_workspace) {
            (Some(_), _, true) | (_, true, true) => Err(PyAssertionError::new_err(
                "workspace execution is only available locally",
            )),
            (None, true, _) => Ok(ProcessExecutionStrategy::RemoteExecution(
                remote_execution_extra_platform_properties,
            )),
            (None, false, false) => Ok(ProcessExecutionStrategy::Local),
            (None, false, true) => Ok(ProcessExecutionStrategy::LocalInWorkspace),
            (Some(image), false, _) => Ok(ProcessExecutionStrategy::Docker(image)),
            (Some(_), true, _) => Err(PyAssertionError::new_err(
                "docker_image cannot be set at the same time as remote_execution",
            )),
        }?;
        Ok(Self {
            environment: ProcessExecutionEnvironment {
                name: environment_name,
                platform,
                strategy,
            },
        })
    }

    fn __hash__(&self) -> u64 {
        let mut s = DefaultHasher::new();
        self.environment.hash(&mut s);
        s.finish()
    }

    fn __repr__(&self) -> String {
        format!(
            "ProcessExecutionEnvironment(environment={:?})",
            self.environment,
        )
    }

    fn __richcmp__(
        &self,
        other: &Bound<'_, PyProcessExecutionEnvironment>,
        op: CompareOp,
        py: Python,
    ) -> PyObject {
        let other = other.borrow();
        match op {
            CompareOp::Eq => (*self == *other).into_py(py),
            CompareOp::Ne => (*self != *other).into_py(py),
            _ => py.NotImplemented(),
        }
    }

    #[getter]
    fn name(&self) -> Option<&str> {
        self.environment.name.as_deref()
    }

    #[getter]
    fn environment_type(&self) -> &str {
        self.environment.strategy.strategy_type()
    }

    #[getter]
    fn platform(&self) -> String {
        self.environment.platform.into()
    }

    #[getter]
    fn remote_execution(&self) -> bool {
        matches!(
            self.environment.strategy,
            ProcessExecutionStrategy::RemoteExecution(_)
        )
    }

    #[getter]
    fn docker_image(&self) -> Option<&str> {
        match &self.environment.strategy {
            ProcessExecutionStrategy::Docker(image) => Some(image),
            _ => None,
        }
    }

    #[getter]
    fn remote_execution_extra_platform_properties(&self) -> Vec<(String, String)> {
        match &self.environment.strategy {
            ProcessExecutionStrategy::RemoteExecution(properties) => properties.to_owned(),
            _ => vec![],
        }
    }
}
