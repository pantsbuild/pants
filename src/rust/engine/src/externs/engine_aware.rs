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
pub(crate) struct EngineAwareReturnType;

impl EngineAwareReturnType {
  pub(crate) fn update_workunit(workunit: &mut RunningWorkunit, task_result: &PyAny) {
    workunit.update_metadata(|old_metadata| {
      let new_level = Self::level(task_result);
      // If the metadata already existed, or if its level changed, we need to update it.
      let mut metadata = if new_level.is_some() || old_metadata.is_some() {
        old_metadata.unwrap_or_default()
      } else {
        return None;
      };

      if let Some(new_level) = new_level {
        metadata.level = new_level;
      }
      metadata.message = Self::message(task_result);
      metadata
        .artifacts
        .extend(Self::artifacts(task_result).unwrap_or_else(Vec::new));
      metadata
        .user_metadata
        .extend(metadata_for(task_result).unwrap_or_else(Vec::new));
      Some(metadata)
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
    metadata_for(obj).unwrap_or_else(Vec::new)
  }
}

fn metadata_for(obj: &PyAny) -> Option<Vec<(String, UserMetadataItem)>> {
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
