// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::Arc;

use crate::externs;
use crate::externs::fs::PyFileDigest;
use crate::nodes::{lift_directory_digest, lift_file_digest};
use crate::Value;

use pyo3::prelude::*;
use pyo3::types::PyDict;

use workunit_store::{ArtifactOutput, Level, RunningWorkunit, UserMetadataItem};

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
  pub(crate) fn from_task_result(task_result: &PyAny) -> Self {
    Self {
      level: Self::level(task_result),
      message: Self::message(task_result),
      artifacts: Self::artifacts(task_result).unwrap_or_else(Vec::new),
      metadata: metadata(task_result).unwrap_or_else(Vec::new),
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

  fn level(obj: &PyAny) -> Option<Level> {
    let level_val = obj.call_method0("level").ok()?;
    if level_val.is_none() {
      return None;
    }
    externs::val_to_log_level(level_val).ok()
  }

  fn message(obj: &PyAny) -> Option<String> {
    let msg_val = obj.call_method0("message").ok()?;
    if msg_val.is_none() {
      return None;
    }
    msg_val.extract().ok()
  }

  fn artifacts(obj: &PyAny) -> Option<Vec<(String, ArtifactOutput)>> {
    let artifacts_val = obj.call_method0("artifacts").ok()?;
    if artifacts_val.is_none() {
      return None;
    }

    let artifacts_dict = artifacts_val.cast_as::<PyDict>().ok()?;
    let mut output = Vec::new();

    for kv_pair in artifacts_dict.items().into_iter() {
      let (key, value): (String, &PyAny) = kv_pair.extract().ok()?;
      let artifact_output = if value.is_instance_of::<PyFileDigest>().unwrap_or(false) {
        lift_file_digest(value).map(ArtifactOutput::FileDigest)
      } else {
        let digest_value = value.getattr("digest").ok()?;
        lift_directory_digest(digest_value).map(|dd| ArtifactOutput::Snapshot(Arc::new(dd)))
      }
      .ok()?;
      output.push((key, artifact_output));
    }
    Some(output)
  }

  pub(crate) fn is_cacheable(obj: &PyAny) -> Option<bool> {
    obj.call_method0("cacheable").ok()?.extract().ok()
  }
}

pub struct EngineAwareParameter;

impl EngineAwareParameter {
  pub fn debug_hint(obj: &PyAny) -> Option<String> {
    let hint = obj.call_method0("debug_hint").ok()?;
    if hint.is_none() {
      return None;
    }
    hint.extract().ok()
  }

  pub fn metadata(obj: &PyAny) -> Vec<(String, UserMetadataItem)> {
    metadata(obj).unwrap_or_else(Vec::new)
  }
}

fn metadata(obj: &PyAny) -> Option<Vec<(String, UserMetadataItem)>> {
  let metadata_val = obj.call_method0("metadata").ok()?;
  if metadata_val.is_none() {
    return None;
  }

  let mut output = Vec::new();
  let metadata_dict = metadata_val.cast_as::<PyDict>().ok()?;

  for kv_pair in metadata_dict.items().into_iter() {
    let (key, py_any): (String, &PyAny) = kv_pair.extract().ok()?;
    let value: Value = Value::new(py_any.into());
    output.push((key, UserMetadataItem::PyValue(Arc::new(value))));
  }
  Some(output)
}
