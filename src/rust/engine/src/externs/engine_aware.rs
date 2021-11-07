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
      artifacts: Self::artifacts(py, &context.core.types, task_result),
      metadata: metadata(py, context, task_result),
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
    let level_val = externs::call_method0(py, value, "level").unwrap();
    if level_val.is_none(py) {
      return None;
    }
    Some(externs::val_to_log_level(&level_val).unwrap())
  }

  fn message(py: Python, value: &Value) -> Option<String> {
    let msg_val = externs::call_method0(py, value, "message").unwrap();
    if msg_val.is_none(py) {
      return None;
    }
    msg_val.extract(py).unwrap()
  }

  fn artifacts(py: Python, types: &Types, value: &Value) -> Vec<(String, ArtifactOutput)> {
    let artifacts_val = externs::call_method0(py, value, "artifacts").unwrap();
    if artifacts_val.is_none(py) {
      return vec![];
    }

    let artifacts_dict: &PyDict = artifacts_val.cast_as::<PyDict>(py).unwrap();
    let mut output = Vec::new();

    for (key, value) in artifacts_dict.items(py).into_iter() {
      let key_name: String = key
        .cast_as::<PyString>(py)
        .unwrap()
        .to_string_lossy(py)
        .into();

      let artifact_output = if TypeId::new(&value.get_type(py)) == types.file_digest {
        lift_file_digest(types, &value).map(ArtifactOutput::FileDigest)
      } else {
        let digest_value = value.getattr(py, "digest").unwrap();
        lift_directory_digest(&digest_value).map(ArtifactOutput::Snapshot)
      }
      .unwrap();
      output.push((key_name, artifact_output));
    }
    output
  }

  pub(crate) fn is_cacheable(py: Python, value: &Value) -> bool {
    externs::call_method0(py, value, "cacheable")
      .unwrap()
      .extract(py)
      .unwrap()
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
    metadata(py, context, value)
  }
}

fn metadata(py: Python, context: &Context, value: &Value) -> Vec<(String, UserMetadataItem)> {
  let metadata_val = externs::call_method0(py, value, "metadata").unwrap();
  if metadata_val.is_none(py) {
    return vec![];
  }

  let mut output = Vec::new();
  let metadata_dict: &PyDict = metadata_val.cast_as::<PyDict>(py).unwrap();

  for (key, value) in metadata_dict.items(py).into_iter() {
    let key_name: String = key.extract(py).unwrap();
    let py_value_handle = UserMetadataPyValue::new();
    let umi = UserMetadataItem::PyValue(py_value_handle.clone());
    context.session.with_metadata_map(|map| {
      map.insert(py_value_handle.clone(), value.into());
    });
    output.push((key_name, umi));
  }
  output
}
