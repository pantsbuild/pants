// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use docker::docker::{ImagePullPolicy, ImagePullScope, DOCKER, IMAGE_PULL_CACHE};
use process_execution::Platform;
use pyo3::prelude::{pyfunction, wrap_pyfunction, PyAny, PyModule, PyResult, Python, ToPyObject};
use pyo3::types::PyString;

use crate::externs::{self, PyGeneratorResponseNativeCall};
use crate::nodes::task_get_context;
use crate::python::{Failure, Value};

pub fn register(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(docker_resolve_image, m)?)?;

    Ok(())
}

#[pyfunction]
fn docker_resolve_image(docker_request: Value) -> PyGeneratorResponseNativeCall {
    PyGeneratorResponseNativeCall::new(async move {
        let context = task_get_context();

        let types = &context.core.types;
        let docker_resolve_image_result = types.docker_resolve_image_result;

        let (image_name, platform) = Python::with_gil(|py| {
            let py_docker_request: &PyAny = docker_request.as_ref().as_ref(py);
            let image_name: String = externs::getattr(py_docker_request, "image_name").unwrap();
            let platform: String = externs::getattr(py_docker_request, "platform").unwrap();
            (image_name, platform)
        });

        let platform = Platform::try_from(platform)?;

        let docker = DOCKER.get().await?;
        let image_pull_scope = ImagePullScope::new(context.session.build_id());

        // Ensure that the image has been pulled.
        IMAGE_PULL_CACHE
            .pull_image(
                docker,
                &context.core.executor,
                &image_name,
                &platform,
                image_pull_scope,
                ImagePullPolicy::OnlyIfLatestOrMissing,
            )
            .await
            .map_err(|err| format!("Failed to pull image `{image_name}`: {err}"))?;

        let image_metadata = docker.inspect_image(&image_name).await.map_err(|err| {
            format!(
                "Failed to resolve image ID for image `{}`: {:?}",
                &image_name, err
            )
        })?;
        let image_id = image_metadata
            .id
            .ok_or_else(|| format!("Image does not exist: `{}`", &image_name))?;

        Ok::<_, Failure>(Python::with_gil(|py| {
            externs::unsafe_call(
                py,
                docker_resolve_image_result,
                &[Value::from(PyString::new(py, &image_id).to_object(py))],
            )
        }))
    })
}
