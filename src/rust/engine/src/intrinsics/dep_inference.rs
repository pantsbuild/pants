// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::{Path, PathBuf};
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
use store::{Snapshot, Store};
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
    digest: DirectoryDigest,
    // Per-file info will be added to this for per-file caching.
    cache_key_base: DependencyInferenceRequest,
}

impl PreparedInferenceRequest {
    pub async fn prepare(deps_request: Value, impl_hash: &str) -> NodeResult<Self> {
        let PyNativeDependenciesRequest {
            directory_digest,
            metadata,
        } = Python::attach(|py| deps_request.bind(py).extract().map_err(PyErr::from))?;

        Ok(Self {
            digest: directory_digest,
            cache_key_base: DependencyInferenceRequest {
                input_file_path: String::new(),
                input_file_digest: None,
                metadata,
                impl_hash: impl_hash.to_string(),
            },
        })
    }

    async fn snapshot(&self, store: &Store) -> NodeResult<Snapshot> {
        Ok(Snapshot::from_digest(store.clone(), self.digest.clone()).await?)
    }

    fn cache_key_for_file(&self, path: &Path, digest: Digest) -> CacheKey {
        let file_request = DependencyInferenceRequest {
            input_file_path: path.display().to_string(),
            input_file_digest: Some(digest.into()),
            metadata: self.cache_key_base.metadata.clone(),
            impl_hash: self.cache_key_base.impl_hash.clone(),
        };
        CacheKey {
            key_type: CacheKeyType::DepInferenceRequest.into(),
            digest: Some(Digest::of_bytes(&file_request.to_bytes()).into()),
        }
    }
}

#[pyfunction]
fn parse_dockerfile_info(deps_request: Value) -> PyGeneratorResponseNativeCall {
    PyGeneratorResponseNativeCall::new(async move {
        let context = task_get_context();

        let core = &context.core;
        let store = core.store();
        let prepared_request =
            PreparedInferenceRequest::prepare(deps_request, dockerfile::IMPL_HASH).await?;

        in_workunit!(
            "parse_dockerfile_info",
            Level::Debug,
            desc = Some("Determine Dockerfile info".to_string()),
            |_workunit| async move {
                let parsed_results: Vec<(PathBuf, ParsedDockerfileDependencies)> =
                    get_or_create_inferred_dependencies(core, &store, &prepared_request, |content, path| {
                        dockerfile::get_info(content, path.clone())
                    })
                    .await?;

                convert_results_to_tuple(parsed_results, |py, _path, result| {
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
                                        "Could not convert ParsedDockerfileDependencies.path `{}` to UTF8.",
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
                })
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
        let prepared_request =
            PreparedInferenceRequest::prepare(deps_request, python::IMPL_HASH).await?;

        in_workunit!(
            "parse_python_dependencies",
            Level::Debug,
            desc = Some("Determine Python dependencies".to_string()),
            |_workunit| async move {
                let parsed_results: Vec<(PathBuf, ParsedPythonDependencies)> =
                    get_or_create_inferred_dependencies(
                        core,
                        &store,
                        &prepared_request,
                        |content, path| python::get_dependencies(content, path.clone()),
                    )
                    .await?;

                convert_results_to_tuple(parsed_results, |py, _path, result| {
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
                })
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
        let prepared_request =
            PreparedInferenceRequest::prepare(deps_request, javascript::IMPL_HASH).await?;

        // Extract JS metadata once for all files.
        let js_metadata = match prepared_request.cache_key_base.metadata.clone() {
            Some(dependency_inference_request::Metadata::Js(metadata)) => metadata,
            other => {
                return Err(Failure::from(format!(
                    "{other:?} is not valid metadata for Javascript dependency inference"
                )));
            }
        };

        in_workunit!(
            "parse_javascript_dependencies",
            Level::Debug,
            desc = Some("Determine Javascript dependencies".to_string()),
            |_workunit| async move {
                let parsed_results: Vec<(PathBuf, ParsedJavascriptDependencies)> =
                    get_or_create_inferred_dependencies(
                        core,
                        &store,
                        &prepared_request,
                        |content, path| {
                            javascript::get_dependencies(content, path.clone(), js_metadata.clone())
                        },
                    )
                    .await?;

                convert_results_to_tuple(parsed_results, |py, _path, result| {
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
                        .collect::<Result<Vec<_>, PyErr>>()?;

                    Ok(externs::unsafe_call(
                        py,
                        core.types.parsed_javascript_deps_result,
                        &[store_dict(py, import_items)?],
                    ))
                })
            }
        )
        .await
    })
}

struct PathAndDigest {
    path: PathBuf,
    digest: Digest,
}

fn convert_results_to_tuple<T, F>(
    parsed_results: Vec<(PathBuf, T)>,
    result_converter: F,
) -> NodeResult<Value>
where
    F: Fn(Python<'_>, &Path, T) -> Result<Value, PyErr>,
{
    let mut result_pairs = Vec::with_capacity(parsed_results.len());
    for (path, result) in parsed_results {
        let py_result_pair = Python::attach(|py| -> Result<_, PyErr> {
            let path_str: String = path
                .as_os_str()
                .to_str()
                .map(|s| s.to_string())
                .ok_or_else(|| {
                    PyException::new_err(format!(
                        "Could not convert path `{}` to UTF8.",
                        path.display()
                    ))
                })?;
            externs::store_tuple(
                py,
                vec![
                    path_str.into_pyobject(py)?.into_any().into(),
                    result_converter(py, &path, result)?,
                ],
            )
        })?;
        result_pairs.push(py_result_pair);
    }

    Python::attach(|py| externs::store_tuple(py, result_pairs)).map_err(Failure::from)
}

pub(crate) async fn get_or_create_inferred_dependencies<T, F>(
    core: &Arc<Core>,
    store: &Store,
    request: &PreparedInferenceRequest,
    dependencies_parser: F,
) -> NodeResult<Vec<(PathBuf, T)>>
where
    T: serde::de::DeserializeOwned + serde::Serialize,
    F: Fn(&str, &PathBuf) -> Result<T, String>,
{
    let snapshot = request.snapshot(store).await?;
    let mut files = Vec::new();
    snapshot
        .tree
        .walk(SymlinkBehavior::Oblivious, &mut |path, entry| {
            if let Entry::File(file) = entry {
                files.push(PathAndDigest {
                    path: path.to_owned(),
                    digest: file.digest(),
                });
            }
        });

    let mut results = Vec::with_capacity(files.len());
    for file in &files {
        let cache_key = request.cache_key_for_file(&file.path, file.digest);
        let result = if let Some(result) = lookup_inferred_dependencies(&cache_key, core).await? {
            result
        } else {
            let bytes = store
                .load_file_bytes_with(file.digest, |bytes| Vec::from(bytes))
                .await?;
            let contents = String::from_utf8(bytes)
                .map_err(|err| format!("Failed to convert digest bytes to utf-8: {err}"))?;
            let result = dependencies_parser(&contents, &file.path)?;
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
        results.push((file.path.clone(), result));
    }
    Ok(results)
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
