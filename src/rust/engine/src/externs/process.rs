// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyAssertionError, PyValueError};
use pyo3::prelude::*;

use process_execution::{Platform, ProcessExecutionEnvironment, ProcessExecutionStrategy};

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
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
    fn __new__(
        platform: String,
        remote_execution: bool,
        remote_execution_extra_platform_properties: Vec<(String, String)>,
        environment_name: Option<String>,
        docker_image: Option<String>,
        docker_mounts: Option<Vec<String>>,
    ) -> PyResult<Self> {
        let platform = Platform::try_from(platform).map_err(PyValueError::new_err)?;
        let strategy = match (docker_image, docker_mounts, remote_execution) {
            (None, None, true) => Ok(ProcessExecutionStrategy::RemoteExecution(
                remote_execution_extra_platform_properties,
            )),
            (None, None, false) => Ok(ProcessExecutionStrategy::Local),
            (Some(image), mounts, false) => Ok(ProcessExecutionStrategy::Docker { image, mounts }),
            (Some(_), _, true) => Err(PyAssertionError::new_err(
                "docker_image cannot be set at the same time as remote_execution",
            )),
            (None, Some(_), _) => Err(PyAssertionError::new_err(
                "docker_mounts cannot be set without docker_image",
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
        other: &PyProcessExecutionEnvironment,
        op: CompareOp,
        py: Python,
    ) -> PyObject {
        match op {
            CompareOp::Eq => (self == other).into_py(py),
            CompareOp::Ne => (self != other).into_py(py),
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
            ProcessExecutionStrategy::Docker { image, .. } => Some(image),
            _ => None,
        }
    }

    #[getter]
    fn docker_mounts(&self) -> Option<Vec<String>> {
        match &self.environment.strategy {
            ProcessExecutionStrategy::Docker { mounts, .. } => mounts.clone(),
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
