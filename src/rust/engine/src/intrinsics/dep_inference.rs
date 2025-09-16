// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::PathBuf;
use std::sync::Arc;

use bytes::Bytes;
use dep_inference::dockerfile::ParsedDockerfileDependencies;
use dep_inference::javascript::ParsedJavascriptDependencies;
use dep_inference::python::ParsedPythonDependencies;
use dep_inference::{dockerfile, javascript, python};
use fs::{DirectoryDigest, Entry, SymlinkBehavior};
use grpc_util::prost::MessageExt;
use hashing::Digest;
use protos::pb::pants::cache::{
    CacheKey, CacheKeyType, DependencyInferenceRequest, dependency_inference_request,
};
use pyo3::exceptions::PyException;
use pyo3::prelude::{PyModule, PyResult, Python, pyfunction, wrap_pyfunction};
use pyo3::types::{PyAnyMethods, PyModuleMethods};
use pyo3::{Bound, IntoPyObject, PyErr};
use store::Store;
use workunit_store::{Level, in_workunit};

use crate::externs::dep_inference::PyNativeDependenciesRequest;
use crate::externs::{PyGeneratorResponseNativeCall, store_dict};
use crate::nodes::{NodeResult, task_get_context};
use crate::python::{Failure, Value};
use crate::{Core, externs};

pub fn register(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_dockerfile_info, m)?)?;
    m.add_function(wrap_pyfunction!(parse_python_deps, m)?)?;
    m.add_function(wrap_pyfunction!(parse_javascript_deps, m)?)?;

    Ok(())
}

pub(crate) struct PreparedInferenceRequest {
    digest: Digest,
    /// The request that's guaranteed to have been constructed via ::prepare().
    ///
    /// NB. this `inner` value is used as the cache key, so anything that can influence the dep
    /// inference should (also) be inside it, not just a key on the outer struct
    inner: DependencyInferenceRequest,
}

impl PreparedInferenceRequest {
    pub async fn prepare(
        deps_request: Value,
        store: &Store,
        backend: &str,
        impl_hash: &str,
    ) -> NodeResult<Self> {
        let PyNativeDependenciesRequest {
            directory_digest,
            metadata,
        } = Python::attach(|py| deps_request.bind(py).extract())?;

        let (path, digest) = Self::find_one_file(directory_digest, store, backend).await?;
        let str_path = path.display().to_string();

        Ok(Self {
            digest,
            inner: DependencyInferenceRequest {
                input_file_path: str_path,
                input_file_digest: Some(digest.into()),
                metadata,
                impl_hash: impl_hash.to_string(),
            },
        })
    }

    pub async fn read_digest(&self, store: &Store) -> NodeResult<String> {
        let bytes = store
            .load_file_bytes_with(self.digest, |bytes| Vec::from(bytes))
            .await?;

        Ok(String::from_utf8(bytes)
            .map_err(|err| format!("Failed to convert digest bytes to utf-8: {err}"))?)
    }

    async fn find_one_file(
        directory_digest: DirectoryDigest,
        store: &Store,
        backend: &str,
    ) -> NodeResult<(PathBuf, Digest)> {
        let mut path = None;
        let mut digest = None;
        store
            .load_digest_trie(directory_digest.clone())
            .await?
            .walk(SymlinkBehavior::Oblivious, &mut |node_path, entry| {
                if let Entry::File(file) = entry {
                    path = Some(node_path.to_owned());
                    digest = Some(file.digest());
                }
            });
        if digest.is_none() || path.is_none() {
            Err(format!(
                "Couldn't find a file in digest for {backend} inference: {directory_digest:?}"
            ))?
        }
        let path = path.unwrap();
        let digest = digest.unwrap();
        Ok((path, digest))
    }

    fn cache_key(&self) -> CacheKey {
        CacheKey {
            key_type: CacheKeyType::DepInferenceRequest.into(),
            digest: Some(Digest::of_bytes(&self.inner.to_bytes()).into()),
        }
    }
}

#[pyfunction]
fn parse_dockerfile_info(deps_request: Value) -> PyGeneratorResponseNativeCall {
    PyGeneratorResponseNativeCall::new(async move {
        let context = task_get_context();

        let core = &context.core;
        let store = core.store();
        let prepared_inference_request = PreparedInferenceRequest::prepare(
            deps_request,
            &store,
            "Dockerfile",
            dockerfile::IMPL_HASH,
        )
        .await?;
        in_workunit!(
            "parse_dockerfile_info",
            Level::Debug,
            desc = Some(format!(
                "Determine Dockerfile info for {:?}",
                &prepared_inference_request.inner.input_file_path
            )),
            |_workunit| async move {
                let result: ParsedDockerfileDependencies = get_or_create_inferred_dependencies(
                    core,
                    &store,
                    prepared_inference_request,
                    |content, request| {
                        dockerfile::get_info(content, request.inner.input_file_path.into())
                    },
                )
                .await?;

                let result = Python::attach(|py| -> Result<_, PyErr> {
                    Ok(externs::unsafe_call(
                        py,
                        core.types.parsed_dockerfile_info_result,
                        &[
                            result
                                .path
                                .as_os_str()
                                .to_str()
                                .map(|s| s.to_string())
                                .ok_or_else(|| {
                                    PyException::new_err(format!(
                                        "Could not convert ParsedDockerfileInfo.path `{}` to UTF8.",
                                        result.path.display()
                                    ))
                                })?
                                .into_pyobject(py)?
                                .into_any()
                                .into(),
                            result.build_args.into_pyobject(py)?.into_any().into(),
                            result
                                .copy_source_paths
                                .into_pyobject(py)?
                                .into_any()
                                .into(),
                            result.copy_build_args.into_pyobject(py)?.into_any().into(),
                            result
                                .from_image_build_args
                                .into_pyobject(py)?
                                .into_any()
                                .into(),
                            result
                                .version_tags
                                .into_iter()
                                .map(|(stage, tag)| match tag {
                                    Some(tag) => format!("{stage} {tag}"),
                                    None => stage.to_string(),
                                })
                                .collect::<Vec<_>>()
                                .into_pyobject(py)?
                                .into_any()
                                .into(),
                        ],
                    ))
                })?;

                Ok::<_, Failure>(result)
            }
        )
        .await
    })
}

#[pyfunction]
fn parse_python_deps(deps_request: Value) -> PyGeneratorResponseNativeCall {
    PyGeneratorResponseNativeCall::new(async move {
        let context = task_get_context();

        let core = &context.core;
        let store = core.store();
        let prepared_inference_request =
            PreparedInferenceRequest::prepare(deps_request, &store, "Python", python::IMPL_HASH)
                .await?;
        in_workunit!(
            "parse_python_dependencies",
            Level::Debug,
            desc = Some(format!(
                "Determine Python dependencies for {:?}",
                &prepared_inference_request.inner.input_file_path
            )),
            |_workunit| async move {
                let result: ParsedPythonDependencies = get_or_create_inferred_dependencies(
                    core,
                    &store,
                    prepared_inference_request,
                    |content, request| {
                        python::get_dependencies(content, request.inner.input_file_path.into())
                    },
                )
                .await?;

                let result = Python::attach(|py| -> Result<_, PyErr> {
                    Ok(externs::unsafe_call(
                        py,
                        core.types.parsed_python_deps_result,
                        &[
                            result.imports.into_pyobject(py)?.into_any().into(),
                            result
                                .string_candidates
                                .into_pyobject(py)?
                                .into_any()
                                .into(),
                        ],
                    ))
                })?;

                Ok::<_, Failure>(result)
            }
        )
        .await
    })
}

#[pyfunction]
fn parse_javascript_deps(deps_request: Value) -> PyGeneratorResponseNativeCall {
    PyGeneratorResponseNativeCall::new(async move {
        let context = task_get_context();

        let core = &context.core;
        let store = core.store();
        let prepared_inference_request = PreparedInferenceRequest::prepare(
            deps_request,
            &store,
            "Javascript",
            javascript::IMPL_HASH,
        )
        .await?;

        in_workunit!(
            "parse_javascript_dependencies",
            Level::Debug,
            desc = Some(format!(
                "Determine Javascript dependencies for {:?}",
                prepared_inference_request.inner.input_file_path
            )),
            |_workunit| async move {
                let result: ParsedJavascriptDependencies = get_or_create_inferred_dependencies(
                    core,
                    &store,
                    prepared_inference_request,
                    |content, request| {
                        if let Some(dependency_inference_request::Metadata::Js(metadata)) =
                            request.inner.metadata
                        {
                            javascript::get_dependencies(
                                content,
                                request.inner.input_file_path.into(),
                                metadata,
                            )
                        } else {
                            Err(format!(
                                "{:?} is not valid metadata for Javascript dependency inference",
                                request.inner.metadata
                            ))
                        }
                    },
                )
                .await?;

                Python::attach(|py| -> Result<_, Failure> {
                    let import_items = result
                        .imports
                        .into_iter()
                        .map(|(string, info)| -> Result<_, PyErr> {
                            Ok((
                                string.into_pyobject(py)?.into_any().into(),
                                externs::unsafe_call(
                                    py,
                                    core.types.parsed_javascript_deps_candidate_result,
                                    &[
                                        info.file_imports.into_pyobject(py)?.into_any().into(),
                                        info.package_imports.into_pyobject(py)?.into_any().into(),
                                    ],
                                ),
                            ))
                        })
                        .collect::<Result<Vec<_>, PyErr>>()
                        .map_err(|e| Failure::from_py_err_with_gil(py, e))?;

                    Ok(externs::unsafe_call(
                        py,
                        core.types.parsed_javascript_deps_result,
                        &[store_dict(py, import_items)
                            .map_err(|e| Failure::from_py_err_with_gil(py, e))?],
                    ))
                })
            }
        )
        .await
    })
}

pub(crate) async fn get_or_create_inferred_dependencies<T, F>(
    core: &Arc<Core>,
    store: &Store,
    request: PreparedInferenceRequest,
    dependencies_parser: F,
) -> NodeResult<T>
where
    T: serde::de::DeserializeOwned + serde::Serialize,
    F: Fn(&str, PreparedInferenceRequest) -> Result<T, String>,
{
    let cache_key = request.cache_key();
    let result =
        if let Some(result) = lookup_inferred_dependencies(&cache_key, core).await? {
            result
        } else {
            let contents = request.read_digest(store).await?;
            let result = dependencies_parser(&contents, request)?;
            core.local_cache
                .store(
                    &cache_key,
                    Bytes::from(serde_json::to_string(&result).map_err(|e| {
                        format!("Failed to serialize dep inference cache result: {e}")
                    })?),
                )
                .await?;
            result
        };
    Ok(result)
}

pub(crate) async fn lookup_inferred_dependencies<T: serde::de::DeserializeOwned>(
    key: &CacheKey,
    core: &Arc<Core>,
) -> NodeResult<Option<T>> {
    let cached_result = core.local_cache.load(key).await?;
    Ok(cached_result
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .flatten())
}
