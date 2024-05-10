// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use docker::docker::{ImagePullPolicy, ImagePullScope, DOCKER, IMAGE_PULL_CACHE};
use futures::future::{BoxFuture, FutureExt};
use process_execution::Platform;
use pyo3::types::PyString;
use pyo3::{Python, ToPyObject};

use crate::context::Context;
use crate::externs;
use crate::nodes::NodeResult;
use crate::python::Value;

pub(crate) fn docker_resolve_image(
    context: Context,
    args: Vec<Value>,
) -> BoxFuture<'static, NodeResult<Value>> {
    async move {
        let types = &context.core.types;
        let docker_resolve_image_result = types.docker_resolve_image_result;

        let (image_name, platform) = Python::with_gil(|py| {
            let py_docker_request = (*args[0]).as_ref(py);
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

        Ok(Python::with_gil(|py| {
            externs::unsafe_call(
                py,
                docker_resolve_image_result,
                &[Value::from(PyString::new(py, &image_id).to_object(py))],
            )
        }))
    }
    .boxed()
}
