// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::core::Value;
use crate::externs;
use crate::nodes::lift_digest;
use cpython::{PyDict, PyString, Python};
use hashing::Digest;
use workunit_store::Level;

//TODO all `retrieve` impelemntations should add a check that the `Value` actually subclasses
//`EngineAware`

pub trait EngineAwareInformation {
  type MaybeOutput;
  fn retrieve(value: &Value) -> Option<Self::MaybeOutput>;
}

#[derive(Clone, Debug)]
pub struct EngineAwareLevel {}

impl EngineAwareInformation for EngineAwareLevel {
  type MaybeOutput = Level;

  fn retrieve(value: &Value) -> Option<Level> {
    let new_level_val: Value = externs::call_method(&value, "level", &[]).ok()?;
    let new_level_val = externs::check_for_python_none(new_level_val)?;
    externs::val_to_log_level(&new_level_val).ok()
  }
}

#[derive(Clone, Debug)]
pub struct Message {}

impl EngineAwareInformation for Message {
  type MaybeOutput = String;

  fn retrieve(value: &Value) -> Option<String> {
    let msg_val: Value = externs::call_method(&value, "message", &[]).ok()?;
    let msg_val = externs::check_for_python_none(msg_val)?;
    Some(externs::val_to_str(&msg_val))
  }
}

#[derive(Clone, Debug)]
pub struct Artifacts {}

impl EngineAwareInformation for Artifacts {
  type MaybeOutput = Vec<(String, Digest)>;

  fn retrieve(value: &Value) -> Option<Self::MaybeOutput> {
    let artifacts_val: Value = externs::call_method(&value, "artifacts", &[]).ok()?;
    let artifacts_val: Value = externs::check_for_python_none(artifacts_val)?;
    let gil = Python::acquire_gil();
    let py = gil.python();
    let artifacts_dict: &PyDict = &*artifacts_val.cast_as::<PyDict>(py).ok()?;
    let mut output = Vec::new();

    for (key, value) in artifacts_dict.items(py).into_iter() {
      let key_name: String = match key.cast_as::<PyString>(py) {
        Ok(s) => s.to_string_lossy(py).into(),
        Err(e) => {
          log::warn!(
            "Error in EngineAware.artifacts() implementation - non-string key: {:?}",
            e
          );
          return None;
        }
      };
      let digest = match lift_digest(&Value::new(value)) {
        Ok(digest) => digest,
        Err(e) => {
          log::warn!("Error in EngineAware.artifacts() implementation: {}", e);
          return None;
        }
      };

      output.push((key_name, digest));
    }
    Some(output)
  }
}

#[derive(Clone, Debug)]
pub struct ParameterDebug {}

impl EngineAwareInformation for ParameterDebug {
  type MaybeOutput = String;

  fn retrieve(value: &Value) -> Option<String> {
    externs::call_method(&value, "parameter_debug", &[])
      .ok()
      .and_then(externs::check_for_python_none)
      .map(|val| externs::val_to_str(&val))
  }
}
