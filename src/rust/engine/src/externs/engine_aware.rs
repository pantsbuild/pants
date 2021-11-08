// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::context::Context;
use crate::externs;
use crate::nodes::{lift_directory_digest, lift_file_digest};
use crate::python::{TypeId, Value};
use crate::Types;

use cpython::{ObjectProtocol, PyDict, PyString, Python};
use workunit_store::{
  ArtifactOutput, Level, RunningWorkunit, UserMetadataItem, UserMetadataPyValue,
};

// Note: these functions should not panic, but we also don't preserve errors (e.g. to log) because
// we rely on MyPy to catch TypeErrors with using the APIs incorrectly. So we convert errors to
// be like the user did not set extra metadata.

#[derive(Default, Clone, Debug)]
pub(crate) struct EngineAwareReturnType {
  level: Option<Level>,
  message: Option<String>,
  metadata: Vec<(String, UserMetadataItem)>,
  artifacts: Vec<(String, ArtifactOutput)>,
}

impl EngineAwareReturnType {
  pub(crate) fn from_task_result(py: Python, task_result: &Value, context: &Context) -> Self {
    Self {
      level: Self::level(py, task_result),
      message: Self::message(py, task_result),
      artifacts: Self::artifacts(py, &context.core.types, task_result).unwrap_or_else(Vec::new),
      metadata: metadata(py, context, task_result).unwrap_or_else(Vec::new),
    }
  }

  pub(crate) fn update_workunit(self, workunit: &mut RunningWorkunit) {
    workunit.update_metadata(|mut metadata| {
      if let Some(new_level) = self.level {
        metadata.level = new_level;
      }
      metadata.message = self.message;
      metadata.artifacts.extend(self.artifacts);
      metadata.user_metadata.extend(self.metadata);
      metadata
    });
  }

  fn level(py: Python, value: &Value) -> Option<Level> {
    let level_val = externs::call_method0(py, value, "level").ok()?;
    if level_val.is_none(py) {
      return None;
    }
    externs::val_to_log_level(&level_val).ok()
  }

  fn message(py: Python, value: &Value) -> Option<String> {
    let msg_val = externs::call_method0(py, value, "message").ok()?;
    if msg_val.is_none(py) {
      return None;
    }
    msg_val.extract(py).ok()
  }

  fn artifacts(py: Python, types: &Types, value: &Value) -> Option<Vec<(String, ArtifactOutput)>> {
    let artifacts_val = externs::call_method0(py, value, "artifacts").ok()?;
    if artifacts_val.is_none(py) {
      return None;
    }

    let artifacts_dict: &PyDict = artifacts_val.cast_as::<PyDict>(py).ok()?;
    let mut output = Vec::new();

    for (key, value) in artifacts_dict.items(py).into_iter() {
      let key_name: String = key.cast_as::<PyString>(py).ok()?.to_string_lossy(py).into();

      let artifact_output = if TypeId::new(&value.get_type(py)) == types.file_digest {
        lift_file_digest(types, &value).map(ArtifactOutput::FileDigest)
      } else {
        let digest_value = value.getattr(py, "digest").ok()?;
        lift_directory_digest(&digest_value).map(ArtifactOutput::Snapshot)
      }
      .ok()?;
      output.push((key_name, artifact_output));
    }
    Some(output)
  }

  pub(crate) fn is_cacheable(py: Python, value: &Value) -> Option<bool> {
    externs::call_method0(py, value, "cacheable")
      .ok()?
      .extract(py)
      .ok()
  }
}

pub struct EngineAwareParameter;

impl EngineAwareParameter {
  pub fn debug_hint(py: Python, value: &Value) -> Option<String> {
    let hint = externs::call_method0(py, value, "debug_hint").ok()?;
    if hint.is_none(py) {
      return None;
    }
    hint.extract(py).ok()
  }

  pub fn metadata(py: Python, context: &Context, value: &Value) -> Vec<(String, UserMetadataItem)> {
    metadata(py, context, value).unwrap_or_else(Vec::new)
  }
}

fn metadata(
  py: Python,
  context: &Context,
  value: &Value,
) -> Option<Vec<(String, UserMetadataItem)>> {
  let metadata_val = externs::call_method0(py, value, "metadata").ok()?;
  if metadata_val.is_none(py) {
    return None;
  }

  let mut output = Vec::new();
  let metadata_dict: &PyDict = metadata_val.cast_as::<PyDict>(py).ok()?;

  for (key, value) in metadata_dict.items(py).into_iter() {
    let key_name: String = key.extract(py).ok()?;
    let py_value_handle = UserMetadataPyValue::new();
    let umi = UserMetadataItem::PyValue(py_value_handle.clone());
    context.session.with_metadata_map(|map| {
      map.insert(py_value_handle.clone(), value.into());
    });
    output.push((key_name, umi));
  }
  Some(output)
}
