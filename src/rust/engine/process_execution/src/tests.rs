// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::time::Duration;

use crate::{
  Platform, Process, ProcessExecutionEnvironment, ProcessExecutionStrategy, ProcessResultMetadata,
  ProcessResultSource,
};
use prost_types::Timestamp;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::ExecutedActionMetadata;
use workunit_store::RunId;

#[test]
fn process_equality() {
  // TODO: Tests like these would be cleaner with the builder pattern for the rust-side Process API.

  let process_generator = |description: String, timeout: Option<Duration>| {
    let mut p = Process::new(vec![]);
    p.description = description;
    p.timeout = timeout;
    p
  };

  fn hash<Hashable: Hash>(hashable: &Hashable) -> u64 {
    let mut hasher = DefaultHasher::new();
    hashable.hash(&mut hasher);
    hasher.finish()
  }

  let a = process_generator("One thing".to_string(), Some(Duration::new(0, 0)));
  let b = process_generator("Another".to_string(), Some(Duration::new(0, 0)));
  let c = process_generator("One thing".to_string(), Some(Duration::new(5, 0)));
  let d = process_generator("One thing".to_string(), None);

  // Process should derive a PartialEq and Hash that ignores the description
  assert_eq!(a, b);
  assert_eq!(hash(&a), hash(&b));

  // ..but not other fields.
  assert_ne!(a, c);
  assert_ne!(hash(&a), hash(&c));

  // Absence of timeout is included in hash.
  assert_ne!(a, d);
  assert_ne!(hash(&a), hash(&d));
}

#[test]
fn process_result_metadata_to_and_from_executed_action_metadata() {
  let env = ProcessExecutionEnvironment {
    name: None,
    platform: Platform::Linux_x86_64,
    strategy: ProcessExecutionStrategy::Local,
  };
  let action_metadata = ExecutedActionMetadata {
    worker_start_timestamp: Some(Timestamp {
      seconds: 100,
      nanos: 20,
    }),
    worker_completed_timestamp: Some(Timestamp {
      seconds: 120,
      nanos: 50,
    }),
    ..ExecutedActionMetadata::default()
  };

  let converted_process_result: ProcessResultMetadata = ProcessResultMetadata::new_from_metadata(
    action_metadata,
    ProcessResultSource::Ran,
    env.clone(),
    RunId(0),
  );
  assert_eq!(
    converted_process_result,
    ProcessResultMetadata::new(
      Some(concrete_time::Duration::new(20, 30)),
      ProcessResultSource::Ran,
      env.clone(),
      RunId(0),
    )
  );

  // The conversion from `ExecutedActionMetadata` to `ProcessResultMetadata` is lossy.
  let restored_action_metadata: ExecutedActionMetadata = converted_process_result.into();
  assert_eq!(
    restored_action_metadata,
    ExecutedActionMetadata {
      worker_start_timestamp: Some(Timestamp {
        seconds: 0,
        nanos: 0,
      }),
      worker_completed_timestamp: Some(Timestamp {
        seconds: 20,
        nanos: 30,
      }),
      ..ExecutedActionMetadata::default()
    }
  );

  // The relevant metadata may be missing from either type.
  let empty = ProcessResultMetadata::new(None, ProcessResultSource::Ran, env.clone(), RunId(0));
  let action_metadata_missing: ProcessResultMetadata = ProcessResultMetadata::new_from_metadata(
    ExecutedActionMetadata::default(),
    ProcessResultSource::Ran,
    env,
    RunId(0),
  );
  assert_eq!(action_metadata_missing, empty);
  let process_result_missing: ExecutedActionMetadata = empty.into();
  assert_eq!(process_result_missing, ExecutedActionMetadata::default());
}

#[test]
fn process_result_metadata_time_saved_from_cache() {
  let env = ProcessExecutionEnvironment {
    name: None,
    platform: Platform::Linux_x86_64,
    strategy: ProcessExecutionStrategy::Local,
  };
  let mut metadata = ProcessResultMetadata::new(
    Some(concrete_time::Duration::new(5, 150)),
    ProcessResultSource::Ran,
    env.clone(),
    RunId(0),
  );
  metadata.update_cache_hit_elapsed(Duration::new(1, 100));
  assert_eq!(
    Duration::from(metadata.saved_by_cache.unwrap()),
    Duration::new(4, 50)
  );

  // If the cache lookup took more time than the process, we return 0.
  let mut metadata = ProcessResultMetadata::new(
    Some(concrete_time::Duration::new(1, 0)),
    ProcessResultSource::Ran,
    env.clone(),
    RunId(0),
  );
  metadata.update_cache_hit_elapsed(Duration::new(5, 0));
  assert_eq!(
    Duration::from(metadata.saved_by_cache.unwrap()),
    Duration::new(0, 0)
  );

  // If the original process time wasn't recorded, we can't compute the time saved.
  let mut metadata = ProcessResultMetadata::new(None, ProcessResultSource::Ran, env, RunId(0));
  metadata.update_cache_hit_elapsed(Duration::new(1, 100));
  assert_eq!(metadata.saved_by_cache, None);
}
