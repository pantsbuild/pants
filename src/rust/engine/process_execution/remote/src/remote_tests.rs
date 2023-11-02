// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::path::{Path, PathBuf};
use std::time::Duration;

use bytes::Bytes;
use grpc_util::prost::MessageExt;
use grpc_util::tls;
use hashing::{Digest, Fingerprint};
use maplit::{btreemap, hashset};
use mock::execution_server::{ExpectedAPICall, MockOperation};
use prost::Message;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::gen::google::longrunning::Operation;
use remexec::{execution_stage::Value as ExecutionStageValue, ExecutedActionMetadata};
use store::{RemoteStoreOptions, SnapshotOps, Store, StoreError};
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory, TestTree};
use testutil::{owned_string_vec, relative_paths};
use tokio::time::{sleep, timeout};
use workunit_store::{Level, RunId, RunningWorkunit, WorkunitStore};

use crate::remote::{CommandRunner, ExecutionError, OperationOrStatus};
use fs::{DirectoryDigest, RelativePath, SymlinkBehavior, EMPTY_DIRECTORY_DIGEST};
use process_execution::{
    CacheName, CommandRunner as CommandRunnerTrait, Context, EntireExecuteRequest,
    FallibleProcessResultWithPlatform, InputDigests, Platform, Process, ProcessCacheScope,
    ProcessError, ProcessExecutionEnvironment, ProcessExecutionStrategy,
};
use std::any::type_name;
use std::io::Cursor;
use tonic::{Code, Status};

const OVERALL_DEADLINE_SECS: Duration = Duration::from_secs(10 * 60);
const RETRY_INTERVAL: Duration = Duration::from_micros(0);
const STORE_CONCURRENCY_LIMIT: usize = 256;
const STORE_BATCH_API_SIZE_LIMIT: usize = 4 * 1024 * 1024;
const EXEC_CONCURRENCY_LIMIT: usize = 256;

#[derive(Debug, PartialEq)]
struct RemoteTestResult {
    original: FallibleProcessResultWithPlatform,
    stdout_bytes: Vec<u8>,
    stderr_bytes: Vec<u8>,
}

impl RemoteTestResult {
    pub fn stdout(&self) -> &str {
        std::str::from_utf8(&self.stdout_bytes).unwrap()
    }

    #[allow(dead_code)]
    pub fn stderr(&self) -> &str {
        std::str::from_utf8(&self.stderr_bytes).unwrap()
    }
}

#[derive(Debug, PartialEq)]
enum StdoutType {
    Raw(String),
    Digest(Digest),
}

#[derive(Debug, PartialEq)]
enum StderrType {
    Raw(String),
    Digest(Digest),
}

fn make_environment(platform: Platform) -> ProcessExecutionEnvironment {
    ProcessExecutionEnvironment {
        name: None,
        platform,
        strategy: ProcessExecutionStrategy::RemoteExecution(vec![]),
    }
}

#[tokio::test]
async fn make_execute_request() {
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let input_directory = TestDirectory::containing_roland();
    let req = Process {
        argv: owned_string_vec(&["/bin/echo", "yo"]),
        env: vec![("SOME".to_owned(), "value".to_owned())]
            .into_iter()
            .collect(),
        working_directory: None,
        input_digests: InputDigests::with_input_files(input_directory.directory_digest()),
        // Intentionally poorly sorted:
        output_files: relative_paths(&["path/to/file.ext", "other/file.ext"]).collect(),
        output_directories: relative_paths(&["directory/name"]).collect(),
        timeout: None,
        description: "some description".to_owned(),
        level: log::Level::Info,
        append_only_caches: BTreeMap::new(),
        jdk_home: None,
        execution_slot_variable: None,
        concurrency_available: 0,
        cache_scope: ProcessCacheScope::Always,
        execution_environment: make_environment(Platform::Linux_x86_64),
        remote_cache_speculation_delay: std::time::Duration::from_millis(0),
        attempt: 0,
    };

    let want_command = remexec::Command {
        arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
        environment_variables: vec![
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_EXECUTION_STRATEGY.to_owned(),
                value: ProcessExecutionStrategy::RemoteExecution(vec![]).cache_value(),
            },
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
                value: "linux_x86_64".to_owned(),
            },
            remexec::command::EnvironmentVariable {
                name: "SOME".to_owned(),
                value: "value".to_owned(),
            },
        ],
        output_files: vec!["other/file.ext".to_owned(), "path/to/file.ext".to_owned()],
        output_directories: vec!["directory/name".to_owned()],
        platform: Some(remexec::Platform::default()),
        ..Default::default()
    };

    let want_action = remexec::Action {
        command_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "d7b7538a7a57a2b04da51ffffff758036f43ebb92d37b66bd1bb8c6af0030e57",
                )
                .unwrap(),
                187,
            ))
                .into(),
        ),
        input_root_digest: Some((&input_directory.digest()).into()),
        ..Default::default()
    };

    let want_execute_request = remexec::ExecuteRequest {
        action_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "16bf057effe6d18553979a069228f0da81df307c964ea0f162bb60e31070bb27",
                )
                .unwrap(),
                141,
            ))
                .into(),
        ),
        skip_cache_lookup: true,
        ..Default::default()
    };

    assert_eq!(
        process_execution::make_execute_request(&req, None, None, &store, None).await,
        Ok(EntireExecuteRequest {
            action: want_action,
            command: want_command,
            execute_request: want_execute_request,
            input_root_digest: input_directory.directory_digest(),
        })
    );
}

#[tokio::test]
async fn make_execute_request_with_instance_name() {
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let input_directory = TestDirectory::containing_roland();
    let req = Process {
        argv: owned_string_vec(&["/bin/echo", "yo"]),
        env: vec![("SOME".to_owned(), "value".to_owned())]
            .into_iter()
            .collect(),
        working_directory: None,
        input_digests: InputDigests::with_input_files(input_directory.directory_digest()),
        // Intentionally poorly sorted:
        output_files: relative_paths(&["path/to/file.ext", "other/file.ext"]).collect(),
        output_directories: relative_paths(&["directory/name"]).collect(),
        timeout: None,
        description: "some description".to_owned(),
        level: log::Level::Info,
        append_only_caches: BTreeMap::new(),
        jdk_home: None,
        execution_slot_variable: None,
        concurrency_available: 0,
        cache_scope: ProcessCacheScope::Always,
        execution_environment: ProcessExecutionEnvironment {
            name: None,
            platform: Platform::Linux_x86_64,
            strategy: ProcessExecutionStrategy::RemoteExecution(vec![(
                "target_platform".to_owned(),
                "apple-2e".to_owned(),
            )]),
        },
        remote_cache_speculation_delay: std::time::Duration::from_millis(0),
        attempt: 0,
    };

    let want_command = remexec::Command {
        arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
        environment_variables: vec![
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_EXECUTION_STRATEGY.to_owned(),
                value: ProcessExecutionStrategy::RemoteExecution(vec![]).cache_value(),
            },
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
                value: "linux_x86_64".to_owned(),
            },
            remexec::command::EnvironmentVariable {
                name: "SOME".to_owned(),
                value: "value".to_owned(),
            },
        ],
        output_files: vec!["other/file.ext".to_owned(), "path/to/file.ext".to_owned()],
        output_directories: vec!["directory/name".to_owned()],
        platform: Some(remexec::Platform {
            properties: vec![remexec::platform::Property {
                name: "target_platform".to_owned(),
                value: "apple-2e".to_owned(),
            }],
        }),
        ..Default::default()
    };

    let want_action = remexec::Action {
        command_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "9f8a65e780495003c341923b62a06ae6796dcad47e396dc89704b10bc26e1729",
                )
                .unwrap(),
                216,
            ))
                .into(),
        ),
        input_root_digest: Some((&input_directory.digest()).into()),
        ..Default::default()
    };

    let want_execute_request = remexec::ExecuteRequest {
        instance_name: "dark-tower".to_owned(),
        action_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "5b017857389d245cd0663105f3b8ee47bb7412940e4859098c8af46bdd21c8b6",
                )
                .unwrap(),
                141,
            ))
                .into(),
        ),
        skip_cache_lookup: true,
        ..Default::default()
    };

    assert_eq!(
        process_execution::make_execute_request(
            &req,
            Some("dark-tower".to_owned()),
            None,
            &store,
            None
        )
        .await,
        Ok(EntireExecuteRequest {
            action: want_action,
            command: want_command,
            execute_request: want_execute_request,
            input_root_digest: input_directory.directory_digest(),
        })
    );
}

#[tokio::test]
async fn make_execute_request_with_cache_key_gen_version() {
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let input_directory = TestDirectory::containing_roland();
    let req = Process {
        argv: owned_string_vec(&["/bin/echo", "yo"]),
        env: vec![("SOME".to_owned(), "value".to_owned())]
            .into_iter()
            .collect(),
        working_directory: None,
        input_digests: InputDigests::with_input_files(input_directory.directory_digest()),
        // Intentionally poorly sorted:
        output_files: relative_paths(&["path/to/file.ext", "other/file.ext"]).collect(),
        output_directories: relative_paths(&["directory/name"]).collect(),
        timeout: None,
        description: "some description".to_owned(),
        level: log::Level::Info,
        append_only_caches: BTreeMap::new(),
        jdk_home: None,
        execution_slot_variable: None,
        concurrency_available: 0,
        cache_scope: ProcessCacheScope::Always,
        execution_environment: make_environment(Platform::Linux_x86_64),
        remote_cache_speculation_delay: std::time::Duration::from_millis(0),
        attempt: 0,
    };

    let mut want_command = remexec::Command {
        arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
        environment_variables: vec![
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_EXECUTION_STRATEGY.to_owned(),
                value: ProcessExecutionStrategy::RemoteExecution(vec![]).cache_value(),
            },
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
                value: "linux_x86_64".to_owned(),
            },
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_GEN_VERSION_ENV_VAR_NAME.to_owned(),
                value: "meep".to_owned(),
            },
            remexec::command::EnvironmentVariable {
                name: "SOME".to_owned(),
                value: "value".to_owned(),
            },
        ],
        output_files: vec!["other/file.ext".to_owned(), "path/to/file.ext".to_owned()],
        output_directories: vec!["directory/name".to_owned()],
        platform: Some(remexec::Platform::default()),
        ..Default::default()
    };
    want_command
        .environment_variables
        .sort_by(|x, y| x.name.cmp(&y.name));

    let want_action = remexec::Action {
        command_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "04ed10b1ddac69249ad1ca463fd4284c4f9c0115a2f2aaf1fd8a9ce6571ee29c",
                )
                .unwrap(),
                224,
            ))
                .into(),
        ),
        input_root_digest: Some((&input_directory.digest()).into()),
        ..Default::default()
    };

    let want_execute_request = remexec::ExecuteRequest {
        action_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "e55329e2c0413a6def422752f9e964204e7e40ec81e2867a6222a43727ba29d1",
                )
                .unwrap(),
                141,
            ))
                .into(),
        ),
        skip_cache_lookup: true,
        ..Default::default()
    };

    assert_eq!(
        process_execution::make_execute_request(&req, None, Some("meep".to_owned()), &store, None)
            .await,
        Ok(EntireExecuteRequest {
            action: want_action,
            command: want_command,
            execute_request: want_execute_request,
            input_root_digest: input_directory.directory_digest(),
        })
    );
}

#[tokio::test]
async fn make_execute_request_with_jdk() {
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let input_directory = TestDirectory::containing_roland();
    let mut req = Process::new(owned_string_vec(&["/bin/echo", "yo"]));
    req.execution_environment.platform = Platform::Linux_x86_64;
    req.jdk_home = Some(PathBuf::from("/tmp"));
    req.description = "some description".to_owned();
    req.input_digests = InputDigests::with_input_files(input_directory.directory_digest());

    let want_command = remexec::Command {
        arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
        environment_variables: vec![
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_EXECUTION_STRATEGY.to_owned(),
                value: ProcessExecutionStrategy::Local.cache_value(),
            },
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
                value: "linux_x86_64".to_owned(),
            },
        ],
        platform: Some(remexec::Platform {
            properties: vec![remexec::platform::Property {
                name: "JDK_SYMLINK".to_owned(),
                value: ".jdk".to_owned(),
            }],
        }),
        ..Default::default()
    };

    let want_action = remexec::Action {
        command_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "45e72f32f1d935e02732e26a8aaec041877811a9b7fe66816ace7b570173953e",
                )
                .unwrap(),
                142,
            ))
                .into(),
        ),
        input_root_digest: Some((&input_directory.digest()).into()),
        ..Default::default()
    };

    let want_execute_request = remexec::ExecuteRequest {
        action_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "2868a54befe3ad9d8fd2ac30c2a170ac890715ec0b196ab8259e8b6beabf7d1c",
                )
                .unwrap(),
                141,
            ))
                .into(),
        ),
        skip_cache_lookup: true,
        ..Default::default()
    };

    assert_eq!(
        process_execution::make_execute_request(&req, None, None, &store, None).await,
        Ok(EntireExecuteRequest {
            action: want_action,
            command: want_command,
            execute_request: want_execute_request,
            input_root_digest: input_directory.directory_digest(),
        })
    );
}

#[tokio::test]
async fn make_execute_request_with_jdk_and_extra_platform_properties() {
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let input_directory = TestDirectory::containing_roland();
    let mut req = Process::new(owned_string_vec(&["/bin/echo", "yo"])).remote_execution(vec![
        ("FIRST".to_owned(), "foo".to_owned()),
        ("Multi".to_owned(), "uno".to_owned()),
        ("last".to_owned(), "bar".to_owned()),
        ("Multi".to_owned(), "dos".to_owned()),
    ]);
    req.execution_environment.platform = Platform::Linux_x86_64;
    req.input_digests = InputDigests::with_input_files(input_directory.directory_digest());
    req.description = "some description".to_owned();
    req.jdk_home = Some(PathBuf::from("/tmp"));

    let want_command = remexec::Command {
        arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
        environment_variables: vec![
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_EXECUTION_STRATEGY.to_owned(),
                value: ProcessExecutionStrategy::RemoteExecution(vec![]).cache_value(),
            },
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
                value: "linux_x86_64".to_owned(),
            },
        ],
        platform: Some(remexec::Platform {
            properties: vec![
                remexec::platform::Property {
                    name: "FIRST".to_owned(),
                    value: "foo".to_owned(),
                },
                remexec::platform::Property {
                    name: "JDK_SYMLINK".to_owned(),
                    value: ".jdk".to_owned(),
                },
                remexec::platform::Property {
                    name: "Multi".to_owned(),
                    value: "dos".to_owned(),
                },
                remexec::platform::Property {
                    name: "Multi".to_owned(),
                    value: "uno".to_owned(),
                },
                remexec::platform::Property {
                    name: "last".to_owned(),
                    value: "bar".to_owned(),
                },
            ],
        }),
        ..Default::default()
    };

    let want_action = remexec::Action {
        command_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "03b368b6f449438938636f57fbaf6b6e2a1eb776583b5197c1320b646ee8d64a",
                )
                .unwrap(),
                198,
            ))
                .into(),
        ),
        input_root_digest: Some((&input_directory.digest()).into()),
        ..Default::default()
    };

    let want_execute_request = remexec::ExecuteRequest {
        action_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "0291bda0da047d715b6da33c1e4c2a74679ab06c95a32424ea754f70be5242ed",
                )
                .unwrap(),
                141,
            ))
                .into(),
        ),
        skip_cache_lookup: true,
        ..Default::default()
    };

    assert_eq!(
        process_execution::make_execute_request(&req, None, None, &store, None).await,
        Ok(EntireExecuteRequest {
            action: want_action,
            command: want_command,
            execute_request: want_execute_request,
            input_root_digest: input_directory.directory_digest(),
        })
    );
}

#[tokio::test]
async fn make_execute_request_with_timeout() {
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let input_directory = TestDirectory::containing_roland();
    let req = Process {
        argv: owned_string_vec(&["/bin/echo", "yo"]),
        env: vec![("SOME".to_owned(), "value".to_owned())]
            .into_iter()
            .collect(),
        working_directory: None,
        input_digests: InputDigests::with_input_files(input_directory.directory_digest()),
        // Intentionally poorly sorted:
        output_files: relative_paths(&["path/to/file.ext", "other/file.ext"]).collect(),
        output_directories: relative_paths(&["directory/name"]).collect(),
        timeout: one_second(),
        description: "some description".to_owned(),
        level: log::Level::Info,
        append_only_caches: BTreeMap::new(),
        jdk_home: None,
        execution_slot_variable: None,
        concurrency_available: 0,
        cache_scope: ProcessCacheScope::Always,
        execution_environment: make_environment(Platform::Linux_x86_64),
        remote_cache_speculation_delay: std::time::Duration::from_millis(0),
        attempt: 0,
    };

    let want_command = remexec::Command {
        arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
        environment_variables: vec![
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_EXECUTION_STRATEGY.to_owned(),
                value: ProcessExecutionStrategy::RemoteExecution(vec![]).cache_value(),
            },
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
                value: "linux_x86_64".to_owned(),
            },
            remexec::command::EnvironmentVariable {
                name: "SOME".to_owned(),
                value: "value".to_owned(),
            },
        ],
        output_files: vec!["other/file.ext".to_owned(), "path/to/file.ext".to_owned()],
        output_directories: vec!["directory/name".to_owned()],
        platform: Some(remexec::Platform::default()),
        ..Default::default()
    };

    let want_action = remexec::Action {
        command_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "d7b7538a7a57a2b04da51ffffff758036f43ebb92d37b66bd1bb8c6af0030e57",
                )
                .unwrap(),
                187,
            ))
                .into(),
        ),
        input_root_digest: Some((&input_directory.digest()).into()),
        timeout: Some(prost_types::Duration::try_from(Duration::from_secs(1)).unwrap()),
        ..Default::default()
    };

    let want_execute_request = remexec::ExecuteRequest {
        action_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "6e3666265a4ef89ddf26a406516484429b2d8e744fbae6b36a66c6853407626a",
                )
                .unwrap(),
                145,
            ))
                .into(),
        ),
        skip_cache_lookup: true,
        ..Default::default()
    };

    assert_eq!(
        process_execution::make_execute_request(&req, None, None, &store, None).await,
        Ok(EntireExecuteRequest {
            action: want_action,
            command: want_command,
            execute_request: want_execute_request,
            input_root_digest: input_directory.directory_digest(),
        })
    );
}

#[tokio::test]
async fn make_execute_request_with_append_only_caches() {
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let input_directory = TestDirectory::containing_roland();
    store
        .record_directory(&input_directory.directory(), false)
        .await
        .unwrap();

    let req = Process {
        argv: owned_string_vec(&["/bin/cat", "../.cache/xyzzy/foo.txt"]),
        env: vec![("SOME".to_owned(), "value".to_owned())]
            .into_iter()
            .collect(),
        working_directory: Some(RelativePath::new(Path::new("animals")).unwrap()),
        input_digests: InputDigests::with_input_files(input_directory.directory_digest()),
        output_files: BTreeSet::new(),
        output_directories: BTreeSet::new(),
        timeout: one_second(),
        description: "some description".to_owned(),
        level: log::Level::Info,
        append_only_caches: btreemap! {
          CacheName::new(String::from("xyzzy")).unwrap() => RelativePath::new(Path::new(".cache/xyzzy")).unwrap(),
        },
        jdk_home: None,
        execution_slot_variable: None,
        concurrency_available: 0,
        cache_scope: ProcessCacheScope::Always,
        execution_environment: make_environment(Platform::Linux_x86_64),
        remote_cache_speculation_delay: std::time::Duration::from_millis(0),
        attempt: 0,
    };

    let want_command = remexec::Command {
        arguments: vec![
            "./__pants_wrapper__".to_owned(),
            "/bin/cat".to_owned(),
            "../.cache/xyzzy/foo.txt".to_owned(),
        ],
        environment_variables: vec![
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_EXECUTION_STRATEGY.to_owned(),
                value: ProcessExecutionStrategy::RemoteExecution(vec![]).cache_value(),
            },
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
                value: "linux_x86_64".to_owned(),
            },
            remexec::command::EnvironmentVariable {
                name: "SOME".to_owned(),
                value: "value".to_owned(),
            },
        ],
        platform: Some(remexec::Platform::default()),
        ..Default::default()
    };

    let want_action = remexec::Action {
        command_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "1deb19eddcefd5074263064a7df2a19caeb4e6d86a849bc07e23a5d856f886ec",
                )
                .unwrap(),
                178,
            ))
                .into(),
        ),
        input_root_digest: Some(
            (Digest::new(
                Fingerprint::from_hex_string(
                    "92f5d2ff07cb6cdf4a70f2d6392781b482cd587b9dd69d6729ac73eb54110a69",
                )
                .unwrap(),
                178,
            ))
            .into(),
        ),
        timeout: Some(prost_types::Duration::try_from(Duration::from_secs(1)).unwrap()),
        ..Default::default()
    };

    let want_execute_request = remexec::ExecuteRequest {
        action_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "e4196db365556cbeed4941845f448cfafc1fabb76b3c476c3f378f358235d3c4",
                )
                .unwrap(),
                146,
            ))
                .into(),
        ),
        skip_cache_lookup: true,
        ..Default::default()
    };

    let want_input_root_digest = DirectoryDigest::from_persisted_digest(Digest::new(
        Fingerprint::from_hex_string(
            "92f5d2ff07cb6cdf4a70f2d6392781b482cd587b9dd69d6729ac73eb54110a69",
        )
        .unwrap(),
        178,
    ));

    let got_execute_request = process_execution::make_execute_request(
        &req,
        None,
        None,
        &store,
        Some("/append-only-caches"),
    )
    .await
    .unwrap();
    assert_eq!(
        got_execute_request,
        EntireExecuteRequest {
            action: want_action,
            command: want_command,
            execute_request: want_execute_request,
            input_root_digest: want_input_root_digest,
        }
    );

    // Ensure that the wrapper script was added to the input root.
    let mut files = store
        .load_digest_trie(got_execute_request.input_root_digest)
        .await
        .unwrap()
        .files(SymlinkBehavior::Oblivious);
    files.sort();
    assert_eq!(
        files,
        vec![
            Path::new("__pants_wrapper__").to_path_buf(),
            Path::new("roland.ext").to_path_buf()
        ]
    )
}

#[tokio::test]
async fn make_execute_request_using_immutable_inputs() {
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let prefix = RelativePath::new("cats").unwrap();
    let input_directory = TestDirectory::containing_roland();
    store
        .record_directory(&input_directory.directory(), false)
        .await
        .expect("Saving directory bytes to store");
    let input_digests = InputDigests::new(
        &store,
        EMPTY_DIRECTORY_DIGEST.clone(),
        {
            let mut map = BTreeMap::new();
            map.insert(prefix.clone(), input_directory.directory_digest());
            map
        },
        BTreeSet::new(),
    )
    .await
    .unwrap();

    // The computed input root digest will be prefixed with the mount point.
    let expected_digest = store
        .add_prefix(input_directory.directory_digest(), &prefix)
        .await
        .unwrap();

    let req = Process {
        argv: owned_string_vec(&["/bin/echo", "yo"]),
        env: vec![("SOME".to_owned(), "value".to_owned())]
            .into_iter()
            .collect(),
        working_directory: None,
        input_digests,
        output_files: relative_paths(&["path/to/file.ext", "other/file.ext"]).collect(),
        output_directories: relative_paths(&["directory/name"]).collect(),
        timeout: None,
        description: "some description".to_owned(),
        level: log::Level::Info,
        append_only_caches: BTreeMap::new(),
        jdk_home: None,
        execution_slot_variable: None,
        concurrency_available: 0,
        cache_scope: ProcessCacheScope::Always,
        execution_environment: make_environment(Platform::Linux_x86_64),
        remote_cache_speculation_delay: std::time::Duration::from_millis(0),
        attempt: 0,
    };

    let want_command = remexec::Command {
        arguments: vec!["/bin/echo".to_owned(), "yo".to_owned()],
        environment_variables: vec![
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_EXECUTION_STRATEGY.to_owned(),
                value: ProcessExecutionStrategy::RemoteExecution(vec![]).cache_value(),
            },
            remexec::command::EnvironmentVariable {
                name: process_execution::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME.to_owned(),
                value: "linux_x86_64".to_owned(),
            },
            remexec::command::EnvironmentVariable {
                name: "SOME".to_owned(),
                value: "value".to_owned(),
            },
        ],
        output_files: vec!["other/file.ext".to_owned(), "path/to/file.ext".to_owned()],
        output_directories: vec!["directory/name".to_owned()],
        platform: Some(remexec::Platform::default()),
        ..Default::default()
    };

    let want_action = remexec::Action {
        command_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "d7b7538a7a57a2b04da51ffffff758036f43ebb92d37b66bd1bb8c6af0030e57",
                )
                .unwrap(),
                187,
            ))
                .into(),
        ),
        input_root_digest: Some((&expected_digest.as_digest()).into()),
        ..Default::default()
    };

    let want_execute_request = remexec::ExecuteRequest {
        action_digest: Some(
            (&Digest::new(
                Fingerprint::from_hex_string(
                    "2c1eae75a54d2464ac63ba51587deb3986f15c3966c61f77fb9b06b195f4127a",
                )
                .unwrap(),
                141,
            ))
                .into(),
        ),
        skip_cache_lookup: true,
        ..Default::default()
    };

    assert_eq!(
        process_execution::make_execute_request(&req, None, None, &store, None).await,
        Ok(EntireExecuteRequest {
            action: want_action,
            command: want_command,
            execute_request: want_execute_request,
            input_root_digest: expected_digest,
        })
    );
}

#[tokio::test]
async fn successful_with_only_call_to_execute() {
    WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();
    let op_name = "gimme-foo".to_string();

    let mock_server = {
        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(&execute_request, None, None, &store, None)
            .await
            .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
                execute_request,
                stream_responses: Ok(vec![
                    make_incomplete_operation(&op_name),
                    make_successful_operation(
                        &op_name,
                        StdoutType::Raw("foo".to_owned()),
                        StderrType::Raw("".to_owned()),
                        0,
                    ),
                ]),
            }]),
            None,
        )
    };

    let result = run_command_remote(mock_server.address(), execute_request)
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "foo".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
    assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn successful_after_reconnect_with_wait_execution() {
    WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();
    let op_name = "gimme-foo".to_string();

    let mock_server = {
        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(&execute_request, None, None, &store, None)
            .await
            .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![
                ExpectedAPICall::Execute {
                    execute_request,
                    stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
                },
                ExpectedAPICall::WaitExecution {
                    operation_name: op_name.clone(),
                    stream_responses: Ok(vec![make_successful_operation(
                        &op_name,
                        StdoutType::Raw("foo".to_owned()),
                        StderrType::Raw("".to_owned()),
                        0,
                    )]),
                },
            ]),
            None,
        )
    };

    let result = run_command_remote(mock_server.address(), execute_request)
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "foo".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
    assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn successful_after_reconnect_from_retryable_error() {
    WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();
    let op_name_1 = "gimme-foo".to_string();
    let op_name_2 = "gimme-bar".to_string();

    let mock_server = {
        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(&execute_request, None, None, &store, None)
            .await
            .unwrap();

        let execute_request_2 = execute_request.clone();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![
                ExpectedAPICall::Execute {
                    execute_request,
                    stream_responses: Ok(vec![
                        make_incomplete_operation(&op_name_1),
                        make_retryable_operation_failure(),
                    ]),
                },
                ExpectedAPICall::Execute {
                    execute_request: execute_request_2,
                    stream_responses: Ok(vec![
                        make_incomplete_operation(&op_name_2),
                        make_successful_operation(
                            &op_name_2,
                            StdoutType::Raw("foo".to_owned()),
                            StderrType::Raw("".to_owned()),
                            0,
                        ),
                    ]),
                },
            ]),
            None,
        )
    };

    let result = run_command_remote(mock_server.address(), execute_request)
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, "foo".as_bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
    assert_cancellation_requests(&mock_server, vec![]);
}

#[tokio::test]
async fn creates_executing_workunit() {
    let (workunit_store, mut workunit) = WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();
    let op_name = "gimme-foo".to_string();

    let queue_time = Duration::from_millis(100);
    let executing_time = Duration::from_millis(100);

    let mock_server = {
        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(&execute_request, None, None, &store, None)
            .await
            .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
                execute_request,
                stream_responses: Ok(vec![
                    make_delayed_incomplete_operation_with_stage(
                        &op_name,
                        queue_time,
                        ExecutionStageValue::Queued,
                    ),
                    make_delayed_incomplete_operation_with_stage(
                        &op_name,
                        Duration::from_millis(0),
                        ExecutionStageValue::Executing,
                    ),
                    make_delayed_incomplete_operation_with_stage(
                        &op_name,
                        executing_time,
                        ExecutionStageValue::Completed,
                    ),
                    make_successful_operation(
                        &op_name,
                        StdoutType::Raw("foo".to_owned()),
                        StderrType::Raw("".to_owned()),
                        0,
                    ),
                ]),
            }]),
            None,
        )
    };

    let result =
        run_command_remote_in_workunit(mock_server.address(), execute_request, &mut workunit)
            .await
            .unwrap();

    assert_eq!(result.original.exit_code, 0);

    // Confirm that a workunit was created, and that it took:
    // 1. at least the queue_time less than its parent
    // 2. more than the executing_time
    let (_, completed_workunits) = workunit_store.latest_workunits(Level::Trace);
    let parent_duration: Duration = completed_workunits
        .iter()
        .find(|wu| wu.name == "run_execute_request")
        .unwrap()
        .time_span()
        .unwrap()
        .duration
        .into();
    let child_duration: Duration = completed_workunits
        .iter()
        .find(|wu| wu.name == "run_remote_process")
        .unwrap()
        .time_span()
        .unwrap()
        .duration
        .into();

    assert!(parent_duration - queue_time >= child_duration);
    assert!(child_duration >= executing_time);
}

#[tokio::test]
async fn dropped_request_cancels() {
    let (workunit_store, mut workunit) = WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let client_timeout = Duration::new(5, 0);
    let delayed_operation_time = Duration::new(15, 0);

    let request = Process::new(owned_string_vec(&["/bin/echo", "-n", "foo"]));

    let op_name = "gimme-foo".to_string();

    let mock_server = {
        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
                execute_request: process_execution::make_execute_request(
                    &request, None, None, &store, None,
                )
                .await
                .unwrap()
                .execute_request,
                stream_responses: Ok(vec![
                    make_incomplete_operation(&op_name),
                    make_delayed_incomplete_operation(&op_name, delayed_operation_time),
                ]),
            }]),
            None,
        )
    };

    let cas = mock::StubCAS::builder()
        .file(&TestData::roland())
        .directory(&TestDirectory::containing_roland())
        .build();
    let (command_runner, _store) = create_command_runner(mock_server.address(), &cas).await;

    let context = Context {
        workunit_store,
        build_id: String::from("marmosets"),
        run_id: RunId(0),
        ..Context::default()
    };

    // Timeout the run, which should cause the remote operation to be cancelled.
    if let Ok(res) = timeout(
        client_timeout,
        command_runner.run(context, &mut workunit, request),
    )
    .await
    {
        panic!("Did not expect the client to return successfully. Got: {res:?}");
    }

    // Wait for the cancellation to have been spawned and sent.
    sleep(Duration::from_secs(2)).await;

    // Confirm that the cancellation was sent.
    assert_cancellation_requests(&mock_server, vec![op_name.to_owned()]);
}

#[tokio::test]
async fn server_rejecting_execute_request_gives_error() {
    WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();

    let mock_server = mock::execution_server::TestServer::new(
        mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
            execute_request: process_execution::make_execute_request(
                &Process::new(owned_string_vec(&["/bin/echo", "-n", "bar"])),
                None,
                None,
                &store,
                None,
            )
            .await
            .unwrap()
            .execute_request,
            stream_responses: Err(Status::invalid_argument("".to_owned())),
        }]),
        None,
    );

    let error = run_command_remote(mock_server.address(), execute_request)
        .await
        .expect_err("Want Err");
    assert!(&error.to_string().contains("InvalidArgument"));
    assert!(&error.to_string().contains("Did not expect this request"));
}

#[tokio::test]
async fn server_sending_triggering_timeout_with_deadline_exceeded() {
    WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();

    let mock_server = {
        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(&execute_request, None, None, &store, None)
            .await
            .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
                execute_request,
                stream_responses: Err(Status::deadline_exceeded("")),
            }]),
            None,
        )
    };

    let result = run_command_remote(mock_server.address(), execute_request)
        .await
        .expect("Should succeed, but with a failed process.");
    assert!(result.stdout().contains("user timeout"));
}

fn remote_options_for_cas(cas: &mock::StubCAS) -> RemoteStoreOptions {
    RemoteStoreOptions {
        store_address: cas.address(),
        instance_name: None,
        tls_config: tls::Config::default(),
        headers: BTreeMap::new(),
        chunk_size_bytes: 10 * 1024 * 1024,
        timeout: Duration::from_secs(1),
        retries: 1,
        concurrency_limit: STORE_CONCURRENCY_LIMIT,
        batch_api_size_limit: STORE_BATCH_API_SIZE_LIMIT,
    }
}

#[tokio::test]
async fn sends_headers() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();

    let cas = mock::StubCAS::empty();
    let runtime = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(runtime.clone(), store_dir)
        .unwrap()
        .into_with_remote(remote_options_for_cas(&cas))
        .await
        .unwrap();

    let execute_request = echo_foo_request();
    let op_name = "gimme-foo".to_string();

    let mock_server = {
        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(&execute_request, None, None, &store, None)
            .await
            .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
                execute_request,
                stream_responses: Ok(vec![
                    make_incomplete_operation(&op_name),
                    make_successful_operation(
                        &op_name,
                        StdoutType::Raw("foo".to_owned()),
                        StderrType::Raw("".to_owned()),
                        0,
                    ),
                ]),
            }]),
            None,
        )
    };

    let command_runner = CommandRunner::new(
        &mock_server.address(),
        None,
        None,
        None,
        Default::default(),
        btreemap! {
          String::from("cat") => String::from("roland"),
          String::from("authorization") => String::from("Bearer catnip-will-get-you-anywhere"),
        },
        store,
        task_executor::Executor::new(),
        OVERALL_DEADLINE_SECS,
        RETRY_INTERVAL,
        EXEC_CONCURRENCY_LIMIT,
    )
    .await
    .unwrap();
    let context = Context {
        workunit_store: WorkunitStore::new(false, log::Level::Debug),
        build_id: String::from("marmosets"),
        run_id: RunId(0),
        ..Context::default()
    };
    command_runner
        .run(context, &mut workunit, execute_request)
        .await
        .expect("Execution failed");

    let received_messages = mock_server.mock_responder.received_messages.lock();
    let message_headers: Vec<_> = received_messages
        .iter()
        .map(|received_message| received_message.headers.clone())
        .collect();
    assert_eq!(message_headers.len(), 1);
    for headers in message_headers {
        {
            let want_key = "google.devtools.remoteexecution.v1test.requestmetadata-bin";
            assert!(headers.contains_key(want_key));

            let bytes = headers.get_bin(want_key).unwrap().to_bytes().unwrap();
            let proto = remexec::RequestMetadata::decode(Cursor::new(bytes))
                .expect("Failed to parse metadata proto");

            assert_eq!(proto.tool_details.map(|x| x.tool_name).unwrap(), "pants");
            assert_eq!(proto.tool_invocation_id, "marmosets");
        }

        assert_eq!(headers.get("cat").unwrap().to_str().unwrap(), "roland");

        assert_eq!(
            headers.get("authorization").unwrap().to_str().unwrap(),
            "Bearer catnip-will-get-you-anywhere"
        );
    }
}

#[tokio::test]
async fn extract_response_with_digest_stdout() {
    WorkunitStore::setup_for_tests();

    let op_name = "gimme-foo".to_string();
    let testdata = TestData::roland();
    let testdata_empty = TestData::empty();
    let result = extract_execute_response(
        make_successful_operation(
            &op_name,
            StdoutType::Digest(testdata.digest()),
            StderrType::Raw(testdata_empty.string()),
            0,
        )
        .op
        .unwrap()
        .unwrap(),
        Platform::Linux_x86_64,
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, testdata.bytes());
    assert_eq!(result.stderr_bytes, testdata_empty.bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test]
async fn extract_response_with_digest_stderr() {
    let _ = WorkunitStore::setup_for_tests();
    let op_name = "gimme-foo".to_string();
    let testdata = TestData::roland();
    let testdata_empty = TestData::empty();
    let result = extract_execute_response(
        make_successful_operation(
            &op_name,
            StdoutType::Raw(testdata_empty.string()),
            StderrType::Digest(testdata.digest()),
            0,
        )
        .op
        .unwrap()
        .unwrap(),
        Platform::Linux_x86_64,
    )
    .await
    .unwrap();

    assert_eq!(result.stdout_bytes, testdata_empty.bytes());
    assert_eq!(result.stderr_bytes, testdata.bytes());
    assert_eq!(result.original.exit_code, 0);
    assert_eq!(result.original.output_directory, *EMPTY_DIRECTORY_DIGEST);
}

#[tokio::test]
async fn ensure_inline_stdio_is_stored() {
    WorkunitStore::setup_for_tests();

    let runtime = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store_dir_path = store_dir.path();

    let cas = mock::StubCAS::empty();
    let store = Store::local_only(runtime.clone(), store_dir_path)
        .unwrap()
        .into_with_remote(remote_options_for_cas(&cas))
        .await
        .unwrap();

    let test_stdout = TestData::roland();
    let test_stderr = TestData::catnip();

    let mock_server = {
        let op_name = "cat".to_owned();

        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(
            &echo_roland_request(),
            None,
            None,
            &store,
            None,
        )
        .await
        .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
                execute_request,
                stream_responses: Ok(vec![
                    make_incomplete_operation(&op_name),
                    make_successful_operation(
                        &op_name.clone(),
                        StdoutType::Raw(test_stdout.string()),
                        StderrType::Raw(test_stderr.string()),
                        0,
                    ),
                ]),
            }]),
            None,
        )
    };

    let cmd_runner = CommandRunner::new(
        &mock_server.address(),
        None,
        None,
        None,
        Default::default(),
        BTreeMap::new(),
        store.clone(),
        task_executor::Executor::new(),
        OVERALL_DEADLINE_SECS,
        RETRY_INTERVAL,
        EXEC_CONCURRENCY_LIMIT,
    )
    .await
    .unwrap();

    let result = run_cmd_runner(echo_roland_request(), cmd_runner, store)
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, test_stdout.bytes());
    assert_eq!(result.stderr_bytes, test_stderr.bytes());
    assert_eq!(result.original.exit_code, 0);

    let local_store =
        Store::local_only(runtime.clone(), store_dir_path).expect("Error creating local store");
    {
        assert_eq!(
            local_store
                .load_file_bytes_with(test_stdout.digest(), Bytes::copy_from_slice)
                .await
                .unwrap(),
            test_stdout.bytes()
        );
        assert_eq!(
            local_store
                .load_file_bytes_with(test_stderr.digest(), Bytes::copy_from_slice)
                .await
                .unwrap(),
            test_stderr.bytes()
        );
    }
}

#[tokio::test]
async fn bad_result_bytes() {
    WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();

    let mock_server = {
        let op_name = "gimme-foo".to_string();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
                execute_request: process_execution::make_execute_request(
                    &execute_request,
                    None,
                    None,
                    &store,
                    None,
                )
                .await
                .unwrap()
                .execute_request,
                stream_responses: Ok(vec![
          make_incomplete_operation(&op_name),
          MockOperation::new(Operation {
            name: op_name.clone(),
            done: true,
            result: Some(
              protos::gen::google::longrunning::operation::Result::Response(prost_types::Any {
                type_url: "type.googleapis.com/build.bazel.remote.execution.v2.ExecuteResponse"
                  .into(),
                value: vec![0x00, 0x00, 0x00],
              }),
            ),
            ..Default::default()
          }),
        ]),
            }]),
            None,
        )
    };

    run_command_remote(mock_server.address(), execute_request)
        .await
        .expect_err("Want Err");
}

#[tokio::test]
async fn initial_response_error() {
    WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();

    let mock_server = {
        let op_name = "gimme-foo".to_string();

        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(&execute_request, None, None, &store, None)
            .await
            .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
                execute_request,
                stream_responses: Ok(vec![MockOperation::new({
                    Operation {
                        name: op_name.to_string(),
                        done: true,
                        result: Some(protos::gen::google::longrunning::operation::Result::Error(
                            protos::gen::google::rpc::Status {
                                code: Code::Internal as i32,
                                message: "Something went wrong".to_string(),
                                ..Default::default()
                            },
                        )),
                        ..Default::default()
                    }
                })]),
            }]),
            None,
        )
    };

    let result = run_command_remote(mock_server.address(), execute_request)
        .await
        .expect_err("Want Err");

    assert!(result.to_string().ends_with(
        "Error from remote execution: \
     InvalidArgument: \"Execute endpoint called. Did not expect this call.\""
    ));
}

#[tokio::test]
async fn initial_response_missing_response_and_error() {
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();

    let mock_server = {
        let op_name = "gimme-foo".to_string();

        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(&execute_request, None, None, &store, None)
            .await
            .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![ExpectedAPICall::Execute {
                execute_request,
                stream_responses: Ok(vec![MockOperation::new({
                    Operation {
                        name: op_name.to_string(),
                        done: true,
                        ..Default::default()
                    }
                })]),
            }]),
            None,
        )
    };

    let result = run_command_remote(mock_server.address(), execute_request)
        .await
        .expect_err("Want Err");

    assert!(result
        .to_string()
        .ends_with("Operation finished but no response supplied"));
}

#[tokio::test]
async fn fails_after_retry_limit_exceeded() {
    WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();

    let mock_server = {
        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(&execute_request, None, None, &store, None)
            .await
            .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![
                ExpectedAPICall::Execute {
                    execute_request: execute_request.clone(),
                    stream_responses: Ok(vec![make_retryable_operation_failure()]),
                },
                ExpectedAPICall::Execute {
                    execute_request: execute_request.clone(),
                    stream_responses: Ok(vec![make_retryable_operation_failure()]),
                },
                ExpectedAPICall::Execute {
                    execute_request: execute_request.clone(),
                    stream_responses: Ok(vec![make_retryable_operation_failure()]),
                },
                ExpectedAPICall::Execute {
                    execute_request: execute_request.clone(),
                    stream_responses: Ok(vec![make_retryable_operation_failure()]),
                },
                ExpectedAPICall::Execute {
                    execute_request: execute_request.clone(),
                    stream_responses: Ok(vec![make_retryable_operation_failure()]),
                },
                ExpectedAPICall::Execute {
                    execute_request: execute_request,
                    stream_responses: Ok(vec![make_retryable_operation_failure()]),
                },
            ]),
            None,
        )
    };

    let result = run_command_remote(mock_server.address(), execute_request)
        .await
        .expect_err("Expected error");

    assert!(result.to_string().ends_with(
        "Too many failures from server. \
     The last error was: the bot running the task appears to be lost"
    ));
}

#[tokio::test]
async fn fails_after_retry_limit_exceeded_with_stream_close() {
    WorkunitStore::setup_for_tests();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(executor, store_dir).unwrap();

    let execute_request = echo_foo_request();

    let mock_server = {
        let op_name = "foo-bar".to_owned();
        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(&execute_request, None, None, &store, None)
            .await
            .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![
                ExpectedAPICall::Execute {
                    execute_request: execute_request,
                    stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
                },
                ExpectedAPICall::WaitExecution {
                    operation_name: op_name.clone(),
                    stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
                },
                ExpectedAPICall::WaitExecution {
                    operation_name: op_name.clone(),
                    stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
                },
                ExpectedAPICall::WaitExecution {
                    operation_name: op_name.clone(),
                    stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
                },
                ExpectedAPICall::WaitExecution {
                    operation_name: op_name.clone(),
                    stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
                },
                ExpectedAPICall::WaitExecution {
                    operation_name: op_name.clone(),
                    stream_responses: Ok(vec![make_incomplete_operation(&op_name)]),
                },
            ]),
            None,
        )
    };

    let result = run_command_remote(mock_server.address(), execute_request)
        .await
        .expect_err("Expected error");

    assert!(result.to_string().ends_with(
        "Too many failures from server. \
     The last event was the server disconnecting with no error given."
    ));
}

#[tokio::test]
async fn execute_missing_file_uploads_if_known() {
    WorkunitStore::setup_for_tests();

    let runtime = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let cas = mock::StubCAS::builder()
        .directory(&TestDirectory::containing_roland())
        .build();
    let store = Store::local_only(runtime.clone(), store_dir)
        .unwrap()
        .into_with_remote(remote_options_for_cas(&cas))
        .await
        .unwrap();

    let roland = TestData::roland();

    let mock_server = {
        let op_name = "cat".to_owned();

        let EntireExecuteRequest {
            execute_request, ..
        } = process_execution::make_execute_request(
            &cat_roland_request(),
            None,
            None,
            &store,
            None,
        )
        .await
        .unwrap();

        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![
                ExpectedAPICall::Execute {
                    execute_request,
                    stream_responses: Ok(vec![
                        make_incomplete_operation(&op_name),
                        make_precondition_failure_operation(vec![
                            missing_preconditionfailure_violation(&roland.digest()),
                        ]),
                    ]),
                },
                ExpectedAPICall::Execute {
                    execute_request: process_execution::make_execute_request(
                        &cat_roland_request(),
                        None,
                        None,
                        &store,
                        None,
                    )
                    .await
                    .unwrap()
                    .execute_request,
                    stream_responses: Ok(vec![
                        make_incomplete_operation(&op_name),
                        make_successful_operation(
                            "cat2",
                            StdoutType::Raw(roland.string()),
                            StderrType::Raw("".to_owned()),
                            0,
                        ),
                    ]),
                },
            ]),
            None,
        )
    };

    store
        .store_file_bytes(roland.bytes(), false)
        .await
        .expect("Saving file bytes to store");
    store
        .record_directory(&TestDirectory::containing_roland().directory(), false)
        .await
        .expect("Saving directory bytes to store");
    let command_runner = CommandRunner::new(
        &mock_server.address(),
        None,
        None,
        None,
        Default::default(),
        BTreeMap::new(),
        store.clone(),
        task_executor::Executor::new(),
        OVERALL_DEADLINE_SECS,
        RETRY_INTERVAL,
        EXEC_CONCURRENCY_LIMIT,
    )
    .await
    .unwrap();

    let result = run_cmd_runner(cat_roland_request(), command_runner, store)
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, roland.bytes());
    assert_eq!(result.stderr_bytes, "".as_bytes());
    assert_eq!(result.original.exit_code, 0);

    {
        let blobs = cas.blobs.lock();
        assert_eq!(blobs.get(&roland.fingerprint()), Some(&roland.bytes()));
    }
}

#[tokio::test]
async fn execute_missing_file_errors_if_unknown() {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();
    let missing_digest = TestDirectory::containing_roland().digest();

    let mock_server = {
        mock::execution_server::TestServer::new(
            mock::execution_server::MockExecution::new(vec![]),
            None,
        )
    };

    let store_dir = TempDir::new().unwrap();
    let cas = mock::StubCAS::builder().file(&TestData::roland()).build();
    let runtime = task_executor::Executor::new();
    let store = Store::local_only(runtime.clone(), store_dir)
        .unwrap()
        .into_with_remote(remote_options_for_cas(&cas))
        .await
        .unwrap();

    let runner = CommandRunner::new(
        &mock_server.address(),
        None,
        None,
        None,
        Default::default(),
        BTreeMap::new(),
        store,
        task_executor::Executor::new(),
        OVERALL_DEADLINE_SECS,
        RETRY_INTERVAL,
        EXEC_CONCURRENCY_LIMIT,
    )
    .await
    .unwrap();

    let error = runner
        .run(Context::default(), &mut workunit, cat_roland_request())
        .await
        .expect_err("Want error");
    assert_contains(&error.to_string(), &format!("{}", missing_digest.hash));
}

#[tokio::test]
async fn extract_execute_response_success() {
    let wanted_exit_code = 17;
    let wanted_stdout = Bytes::from_static(b"roland");
    let wanted_stderr = Bytes::from_static(b"simba");

    let operation = Operation {
        name: "cat".to_owned(),
        done: true,
        result: Some(
            protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
                &remexec::ExecuteResponse {
                    result: Some(remexec::ActionResult {
                        exit_code: wanted_exit_code,
                        stdout_raw: wanted_stdout.clone(),
                        stderr_raw: wanted_stderr.clone(),
                        output_files: vec![remexec::OutputFile {
                            path: "cats/roland.ext".into(),
                            digest: Some((&TestData::roland().digest()).into()),
                            is_executable: false,
                            ..Default::default()
                        }],
                        ..Default::default()
                    }),
                    ..Default::default()
                },
                "protos::gen::",
            )),
        ),
        ..Default::default()
    };

    let result = extract_execute_response(operation, Platform::Linux_x86_64)
        .await
        .unwrap();

    assert_eq!(result.stdout_bytes, wanted_stdout);
    assert_eq!(result.stderr_bytes, wanted_stderr);
    assert_eq!(result.original.exit_code, wanted_exit_code);
    assert_eq!(
        result.original.output_directory,
        TestDirectory::nested().directory_digest()
    );
}

#[tokio::test]
async fn extract_execute_response_timeout() {
    let operation = Operation {
        name: "cat".to_owned(),
        done: true,
        result: Some(
            protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
                &remexec::ExecuteResponse {
                    status: Some(protos::gen::google::rpc::Status {
                        code: Code::DeadlineExceeded as i32,
                        ..Default::default()
                    }),
                    ..Default::default()
                },
                "protos::gen::",
            )),
        ),
        ..Default::default()
    };

    match extract_execute_response(operation, Platform::Linux_x86_64).await {
        Err(ExecutionError::Timeout) => (),
        other => assert!(false, "Want timeout error, got {other:?}"),
    };
}

#[tokio::test]
async fn extract_execute_response_missing_digests() {
    let missing_files = vec![
        TestData::roland().digest(),
        TestDirectory::containing_roland().digest(),
    ];

    let missing = missing_files
        .iter()
        .map(missing_preconditionfailure_violation)
        .collect();

    let operation = make_precondition_failure_operation(missing)
        .op
        .unwrap()
        .unwrap();

    assert_eq!(
        extract_execute_response(operation, Platform::Linux_x86_64).await,
        Err(ExecutionError::MissingRemoteDigests(missing_files))
    );
}

#[tokio::test]
async fn extract_execute_response_missing_other_things() {
    let missing = vec![
        missing_preconditionfailure_violation(&TestData::roland().digest()),
        protos::gen::google::rpc::precondition_failure::Violation {
            r#type: "MISSING".to_owned(),
            subject: "monkeys".to_owned(),
            ..Default::default()
        },
    ];

    let operation = make_precondition_failure_operation(missing)
        .op
        .unwrap()
        .unwrap();

    match extract_execute_response(operation, Platform::Linux_x86_64).await {
        Err(ExecutionError::Fatal(err)) => assert_contains(&err.to_string(), "monkeys"),
        other => assert!(false, "Want fatal error, got {other:?}"),
    };
}

#[tokio::test]
async fn extract_execute_response_other_failed_precondition() {
    let missing = vec![protos::gen::google::rpc::precondition_failure::Violation {
        r#type: "OUT_OF_CAPACITY".to_owned(),
        ..Default::default()
    }];

    let operation = make_precondition_failure_operation(missing)
        .op
        .unwrap()
        .unwrap();

    match extract_execute_response(operation, Platform::Linux_x86_64).await {
        Err(ExecutionError::Fatal(err)) => assert_contains(&err.to_string(), "OUT_OF_CAPACITY"),
        other => assert!(false, "Want fatal error, got {other:?}"),
    };
}

#[tokio::test]
async fn extract_execute_response_missing_without_list() {
    let missing = vec![];

    let operation = make_precondition_failure_operation(missing)
        .op
        .unwrap()
        .unwrap();

    match extract_execute_response(operation, Platform::Linux_x86_64).await {
        Err(ExecutionError::Fatal(err)) => {
            assert_contains(&err.to_string().to_lowercase(), "precondition")
        }
        other => assert!(false, "Want fatal error, got {other:?}"),
    };
}

#[tokio::test]
async fn extract_execute_response_other_status() {
    let operation = Operation {
        name: "cat".to_owned(),
        done: true,
        result: Some(
            protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
                &remexec::ExecuteResponse {
                    status: Some(protos::gen::google::rpc::Status {
                        code: Code::PermissionDenied as i32,
                        ..Default::default()
                    }),
                    ..Default::default()
                },
                "protos::gen::",
            )),
        ),
        ..Default::default()
    };

    match extract_execute_response(operation, Platform::Linux_x86_64).await {
        Err(ExecutionError::Fatal(err)) => assert_contains(&err.to_string(), "PermissionDenied"),
        other => assert!(false, "Want fatal error, got {other:?}"),
    };
}

#[tokio::test]
async fn remote_workunits_are_stored() {
    let (workunit_store, _) = WorkunitStore::setup_for_tests();
    let op_name = "gimme-foo".to_string();
    let testdata = TestData::roland();
    let testdata_empty = TestData::empty();
    let operation = make_successful_operation_with_metadata(
        &op_name,
        StdoutType::Digest(testdata.digest()),
        StderrType::Raw(testdata_empty.string()),
        0,
    );
    let cas = mock::StubCAS::builder()
        .file(&TestData::roland())
        .directory(&TestDirectory::containing_roland())
        .build();
    // TODO: This CommandRunner is only used for parsing, add so intentionally passes a CAS/AC
    // address rather than an Execution address.
    let (command_runner, _store) = create_command_runner(cas.address(), &cas).await;

    command_runner
        .extract_execute_response(
            RunId(0),
            make_environment(Platform::Linux_x86_64),
            OperationOrStatus::Operation(operation),
        )
        .await
        .unwrap();

    let got_workunit_items: HashSet<&'static str> = workunit_store
        .latest_workunits(log::Level::Trace)
        .1
        .into_iter()
        .map(|workunit| workunit.name)
        .collect();

    let wanted_workunit_items = hashset! {
      "remote execution action scheduling",
      "remote execution worker input fetching",
      "remote execution worker command executing",
      "remote execution worker output uploading",
    };

    assert!(got_workunit_items.is_superset(&wanted_workunit_items));
}

#[tokio::test]
async fn format_error_complete() {
    let error = protos::gen::google::rpc::Status {
        code: Code::Cancelled as i32,
        message: "Oops, oh well!".to_string(),
        ..Default::default()
    };

    assert_eq!(
        crate::remote::format_error(&error),
        "Cancelled: Oops, oh well!".to_string()
    );
}

#[tokio::test]
async fn extract_execute_response_unknown_code() {
    let error = protos::gen::google::rpc::Status {
        code: 555,
        message: "Oops, oh well!".to_string(),
        ..Default::default()
    };

    assert_eq!(
        crate::remote::format_error(&error),
        "555: Oops, oh well!".to_string()
    );
}

#[tokio::test]
async fn digest_command() {
    let command = remexec::Command {
        arguments: vec!["/bin/echo".to_string(), "foo".to_string()],
        environment_variables: vec![
            remexec::command::EnvironmentVariable {
                name: "A".to_string(),
                value: "a".to_string(),
            },
            remexec::command::EnvironmentVariable {
                name: "B".to_string(),
                value: "b".to_string(),
            },
        ],
        ..Default::default()
    };

    let digest = process_execution::digest(&command).unwrap();

    assert_eq!(
        &digest.hash.to_hex(),
        "a32cd427e5df6a998199266681692989f56c19cabd1cc637bdd56ae2e62619b4"
    );
    assert_eq!(digest.size_bytes, 32)
}

#[tokio::test]
async fn extract_output_files_from_response_one_file() {
    let execute_response = remexec::ExecuteResponse {
        result: Some(remexec::ActionResult {
            exit_code: 0,
            output_files: vec![remexec::OutputFile {
                path: "roland.ext".into(),
                digest: Some((&TestData::roland().digest()).into()),
                is_executable: false,
                ..Default::default()
            }],
            ..Default::default()
        }),
        ..Default::default()
    };

    assert_eq!(
        extract_output_files_from_response(&execute_response).await,
        Ok(TestDirectory::containing_roland().digest())
    )
}

#[tokio::test]
async fn extract_output_files_from_response_two_files_not_nested() {
    let execute_response = remexec::ExecuteResponse {
        result: Some(remexec::ActionResult {
            exit_code: 0,
            output_files: vec![
                remexec::OutputFile {
                    path: "roland.ext".into(),
                    digest: Some((&TestData::roland().digest()).into()),
                    is_executable: false,
                    ..Default::default()
                },
                remexec::OutputFile {
                    path: "treats.ext".into(),
                    digest: Some((&TestData::catnip().digest()).into()),
                    is_executable: false,
                    ..Default::default()
                },
            ],
            ..Default::default()
        }),
        ..Default::default()
    };

    assert_eq!(
        extract_output_files_from_response(&execute_response).await,
        Ok(TestDirectory::containing_roland_and_treats().digest())
    )
}

#[tokio::test]
async fn extract_output_files_from_response_two_files_nested() {
    let execute_response = remexec::ExecuteResponse {
        result: Some(remexec::ActionResult {
            exit_code: 0,
            output_files: vec![
                remexec::OutputFile {
                    path: "cats/roland.ext".into(),
                    digest: Some((&TestData::roland().digest()).into()),
                    is_executable: false,
                    ..Default::default()
                },
                remexec::OutputFile {
                    path: "treats.ext".into(),
                    digest: Some((&TestData::catnip().digest()).into()),
                    is_executable: false,
                    ..Default::default()
                },
            ],
            ..Default::default()
        }),
        ..Default::default()
    };

    assert_eq!(
        extract_output_files_from_response(&execute_response).await,
        Ok(TestDirectory::recursive().digest())
    )
}

#[tokio::test]
async fn extract_output_files_from_response_just_directory() {
    let _ = WorkunitStore::setup_for_tests();
    let test_tree: TestTree = TestDirectory::containing_roland().into();

    let execute_response = remexec::ExecuteResponse {
        result: Some(remexec::ActionResult {
            exit_code: 0,
            output_directories: vec![remexec::OutputDirectory {
                path: "cats".into(),
                tree_digest: Some(test_tree.digest().into()),
                is_topologically_sorted: false,
            }],
            ..Default::default()
        }),
        ..Default::default()
    };

    assert_eq!(
        extract_output_files_from_response(&execute_response).await,
        Ok(TestDirectory::nested().digest())
    )
}

#[tokio::test]
async fn extract_output_files_from_response_directories_and_files() {
    // /treats.ext
    // /pets/cats/roland.ext
    // /pets/dogs/robin.ext

    let _ = WorkunitStore::setup_for_tests();
    let execute_response = remexec::ExecuteResponse {
        result: Some(remexec::ActionResult {
            exit_code: 0,
            output_files: vec![remexec::OutputFile {
                path: "treats.ext".into(),
                digest: Some((&TestData::catnip().digest()).into()),
                ..Default::default()
            }],
            output_directories: vec![
                remexec::OutputDirectory {
                    path: "pets/cats".into(),
                    tree_digest: Some((&TestTree::roland_at_root().digest()).into()),
                    is_topologically_sorted: false,
                },
                remexec::OutputDirectory {
                    path: "pets/dogs".into(),
                    tree_digest: Some((&TestTree::robin_at_root().digest()).into()),
                    is_topologically_sorted: false,
                },
            ],
            ..Default::default()
        }),
        ..Default::default()
    };

    assert_eq!(
        extract_output_files_from_response(&execute_response).await,
        Ok(Digest::new(
            Fingerprint::from_hex_string(
                "b5e7010d8c5ef77b383fc60ea00bdfb4743dd6fa3983033b50f218ea90124d0d"
            )
            .unwrap(),
            163
        ))
    )
}

#[tokio::test]
async fn extract_output_files_from_response_no_prefix() {
    let _ = WorkunitStore::setup_for_tests();
    let execute_response = remexec::ExecuteResponse {
        result: Some(remexec::ActionResult {
            exit_code: 0,
            output_directories: vec![remexec::OutputDirectory {
                path: String::new(),
                tree_digest: Some((&TestTree::roland_at_root().digest()).into()),
                is_topologically_sorted: false,
            }],
            ..Default::default()
        }),
        ..Default::default()
    };

    assert_eq!(
        extract_output_files_from_response(&execute_response).await,
        Ok(TestDirectory::containing_roland().digest())
    )
}

pub fn echo_foo_request() -> Process {
    let mut req = Process::new(owned_string_vec(&["/bin/echo", "-n", "foo"]));
    req.timeout = Some(Duration::from_millis(5000));
    req.description = "echo a foo".to_string();
    req
}

fn make_incomplete_operation(operation_name: &str) -> MockOperation {
    MockOperation::new(Operation {
        name: operation_name.to_string(),
        done: false,
        ..Default::default()
    })
}

fn make_delayed_incomplete_operation(operation_name: &str, delay: Duration) -> MockOperation {
    let mut op = make_incomplete_operation(operation_name);
    op.duration = Some(delay);
    op
}

fn make_delayed_incomplete_operation_with_stage(
    operation_name: &str,
    delay: Duration,
    stage: ExecutionStageValue,
) -> MockOperation {
    let mut op = make_delayed_incomplete_operation(operation_name, delay);
    match &mut op.op {
        Ok(Some(op)) => {
            op.metadata = Some(make_any_proto(
                &remexec::ExecuteOperationMetadata {
                    stage: stage as i32,
                    ..Default::default()
                },
                "protos::gen::",
            ));
        }
        x => panic!("Unexpected MockOperation content: {x:?}"),
    }
    op
}

fn make_retryable_operation_failure() -> MockOperation {
    let status = protos::gen::google::rpc::Status {
        code: Code::Aborted as i32,
        message: String::from("the bot running the task appears to be lost"),
        ..Default::default()
    };

    let operation = Operation {
        done: true,
        result: Some(
            protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
                &remexec::ExecuteResponse {
                    status: Some(status),
                    ..Default::default()
                },
                "protos::gen::",
            )),
        ),
        ..Default::default()
    };

    MockOperation {
        op: Ok(Some(operation)),
        duration: None,
    }
}

fn make_action_result(
    stdout: StdoutType,
    stderr: StderrType,
    exit_code: i32,
    metadata: Option<ExecutedActionMetadata>,
) -> remexec::ActionResult {
    let mut action_result = remexec::ActionResult::default();
    match stdout {
        StdoutType::Raw(stdout_raw) => {
            action_result.stdout_raw = stdout_raw.into_bytes().into();
        }
        StdoutType::Digest(stdout_digest) => {
            action_result.stdout_digest = Some((&stdout_digest).into());
        }
    }
    match stderr {
        StderrType::Raw(stderr_raw) => {
            action_result.stderr_raw = stderr_raw.into_bytes().into();
        }
        StderrType::Digest(stderr_digest) => {
            action_result.stderr_digest = Some((&stderr_digest).into());
        }
    }
    action_result.exit_code = exit_code;
    if let Some(metadata) = metadata {
        action_result.execution_metadata = Some(metadata);
    };
    action_result
}

fn make_successful_operation_with_maybe_metadata(
    operation_name: &str,
    stdout: StdoutType,
    stderr: StderrType,
    exit_code: i32,
    metadata: Option<ExecutedActionMetadata>,
) -> Operation {
    Operation {
        name: operation_name.to_string(),
        done: true,
        result: Some(
            protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
                &remexec::ExecuteResponse {
                    status: Some(protos::gen::google::rpc::Status {
                        code: Code::Ok as i32,
                        ..Default::default()
                    }),
                    result: Some(make_action_result(stdout, stderr, exit_code, metadata)),
                    ..Default::default()
                },
                "protos::gen::",
            )),
        ),
        ..Default::default()
    }
}

fn make_successful_operation(
    operation_name: &str,
    stdout: StdoutType,
    stderr: StderrType,
    exit_code: i32,
) -> MockOperation {
    let op = make_successful_operation_with_maybe_metadata(
        operation_name,
        stdout,
        stderr,
        exit_code,
        None,
    );
    MockOperation::new(op)
}

fn make_successful_operation_with_metadata(
    operation_name: &str,
    stdout: StdoutType,
    stderr: StderrType,
    exit_code: i32,
) -> Operation {
    let metadata = remexec::ExecutedActionMetadata {
        queued_timestamp: Some(timestamp_only_secs(0)),
        worker_start_timestamp: Some(timestamp_only_secs(1)),
        input_fetch_start_timestamp: Some(timestamp_only_secs(2)),
        input_fetch_completed_timestamp: Some(timestamp_only_secs(3)),
        execution_start_timestamp: Some(timestamp_only_secs(4)),
        execution_completed_timestamp: Some(timestamp_only_secs(5)),
        output_upload_start_timestamp: Some(timestamp_only_secs(6)),
        output_upload_completed_timestamp: Some(timestamp_only_secs(7)),
        worker_completed_timestamp: Some(timestamp_only_secs(8)),
        ..Default::default()
    };

    make_successful_operation_with_maybe_metadata(
        operation_name,
        stdout,
        stderr,
        exit_code,
        Some(metadata),
    )
}

fn timestamp_only_secs(v: i64) -> prost_types::Timestamp {
    prost_types::Timestamp {
        seconds: v,
        nanos: 0,
    }
}

fn make_precondition_failure_operation(
    violations: Vec<protos::gen::google::rpc::precondition_failure::Violation>,
) -> MockOperation {
    let operation = Operation {
        name: "cat".to_owned(),
        done: true,
        result: Some(
            protos::gen::google::longrunning::operation::Result::Response(make_any_proto(
                &remexec::ExecuteResponse {
                    status: Some(make_precondition_failure_status(violations)),
                    ..Default::default()
                },
                "protos::gen::",
            )),
        ),
        ..Default::default()
    };
    MockOperation::new(operation)
}

fn make_precondition_failure_status(
    violations: Vec<protos::gen::google::rpc::precondition_failure::Violation>,
) -> protos::gen::google::rpc::Status {
    protos::gen::google::rpc::Status {
        code: Code::FailedPrecondition as i32,
        details: vec![make_any_proto(
            &protos::gen::google::rpc::PreconditionFailure { violations },
            "protos::gen::",
        )],
        ..Default::default()
    }
}

async fn run_cmd_runner<R: CommandRunnerTrait>(
    request: Process,
    command_runner: R,
    store: Store,
) -> Result<RemoteTestResult, ProcessError> {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();
    let original = command_runner
        .run(Context::default(), &mut workunit, request)
        .await?;
    let stdout_bytes = store
        .load_file_bytes_with(original.stdout_digest, |bytes| bytes.to_vec())
        .await?;
    let stderr_bytes = store
        .load_file_bytes_with(original.stderr_digest, |bytes| bytes.to_vec())
        .await?;
    Ok(RemoteTestResult {
        original,
        stdout_bytes,
        stderr_bytes,
    })
}

async fn create_command_runner(
    execution_address: String,
    cas: &mock::StubCAS,
) -> (CommandRunner, Store) {
    let runtime = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = make_store(store_dir.path(), cas, runtime).await;
    let command_runner = CommandRunner::new(
        &execution_address,
        None,
        None,
        None,
        Default::default(),
        BTreeMap::new(),
        store.clone(),
        task_executor::Executor::new(),
        OVERALL_DEADLINE_SECS,
        RETRY_INTERVAL,
        EXEC_CONCURRENCY_LIMIT,
    )
    .await
    .expect("Failed to make command runner");
    (command_runner, store)
}

async fn run_command_remote(
    execution_address: String,
    request: Process,
) -> Result<RemoteTestResult, ProcessError> {
    let (_, mut workunit) = WorkunitStore::setup_for_tests();
    run_command_remote_in_workunit(execution_address, request, &mut workunit).await
}

async fn run_command_remote_in_workunit(
    execution_address: String,
    request: Process,
    workunit: &mut RunningWorkunit,
) -> Result<RemoteTestResult, ProcessError> {
    let cas = mock::StubCAS::builder()
        .file(&TestData::roland())
        .directory(&TestDirectory::containing_roland())
        .tree(&TestTree::roland_at_root())
        .build();
    let (command_runner, store) = create_command_runner(execution_address, &cas).await;
    let original = command_runner
        .run(Context::default(), workunit, request)
        .await?;

    let stdout_bytes = store
        .load_file_bytes_with(original.stdout_digest, |bytes| bytes.to_vec())
        .await?;
    let stderr_bytes = store
        .load_file_bytes_with(original.stderr_digest, |bytes| bytes.to_vec())
        .await?;
    Ok(RemoteTestResult {
        original,
        stdout_bytes,
        stderr_bytes,
    })
}

async fn make_store(
    store_dir: &Path,
    cas: &mock::StubCAS,
    executor: task_executor::Executor,
) -> Store {
    Store::local_only(executor, store_dir)
        .unwrap()
        .into_with_remote(remote_options_for_cas(&cas))
        .await
        .unwrap()
}

async fn extract_execute_response(
    operation: Operation,
    platform: Platform,
) -> Result<RemoteTestResult, ExecutionError> {
    let cas = mock::StubCAS::builder()
        .file(&TestData::roland())
        .directory(&TestDirectory::containing_roland())
        .build();
    // TODO: This CommandRunner is only used for parsing, add so intentionally passes a CAS/AC
    // address rather than an Execution address.
    let (command_runner, store) = create_command_runner(cas.address(), &cas).await;

    let original = command_runner
        .extract_execute_response(
            RunId(0),
            make_environment(platform),
            OperationOrStatus::Operation(operation),
        )
        .await?;

    let stdout_bytes: Vec<u8> = store
        .load_file_bytes_with(original.stdout_digest, |bytes| bytes.to_vec())
        .await
        .unwrap();

    let stderr_bytes: Vec<u8> = store
        .load_file_bytes_with(original.stderr_digest, |bytes| bytes.to_vec())
        .await
        .unwrap();

    Ok(RemoteTestResult {
        original,
        stdout_bytes,
        stderr_bytes,
    })
}

async fn extract_output_files_from_response(
    execute_response: &remexec::ExecuteResponse,
) -> Result<Digest, StoreError> {
    let cas = mock::StubCAS::builder()
        .file(&TestData::roland())
        .directory(&TestDirectory::containing_roland())
        .tree(&TestTree::roland_at_root())
        .tree(&TestTree::robin_at_root())
        .build();
    let executor = task_executor::Executor::new();
    let store_dir = TempDir::new().unwrap();
    let store = make_store(store_dir.path(), &cas, executor.clone()).await;
    let action_result = execute_response
        .result
        .as_ref()
        .ok_or_else(|| "No ActionResult found".to_string())?;
    let directory_digest =
        process_execution::extract_output_files(store, action_result, false).await?;
    Ok(directory_digest.as_digest())
}

fn make_any_proto<T: Message>(message: &T, prefix: &str) -> prost_types::Any {
    let rust_type_name = type_name::<T>();
    let proto_type_name = rust_type_name
        .strip_prefix(prefix)
        .unwrap()
        .replace("::", ".");

    prost_types::Any {
        type_url: format!("type.googleapis.com/{proto_type_name}"),
        value: message.to_bytes().to_vec(),
    }
}

fn missing_preconditionfailure_violation(
    digest: &Digest,
) -> protos::gen::google::rpc::precondition_failure::Violation {
    {
        protos::gen::google::rpc::precondition_failure::Violation {
            r#type: "MISSING".to_owned(),
            subject: format!("blobs/{}/{}", digest.hash, digest.size_bytes),
            ..Default::default()
        }
    }
}

#[track_caller]
fn assert_contains(haystack: &str, needle: &str) {
    assert!(
        haystack.contains(needle),
        "{haystack:?} should contain {needle:?}"
    )
}

fn cat_roland_request() -> Process {
    let argv = owned_string_vec(&["/bin/cat", "roland.ext"]);
    let mut process = Process::new(argv);
    process.execution_environment.platform = Platform::Linux_x86_64;
    process.input_digests =
        InputDigests::with_input_files(TestDirectory::containing_roland().directory_digest());
    process.timeout = one_second();
    process.description = "cat a roland".to_string();
    process
}

fn echo_roland_request() -> Process {
    let mut req = Process::new(owned_string_vec(&["/bin/echo", "meoooow"]));
    req.execution_environment.platform = Platform::Linux_x86_64;
    req.timeout = one_second();
    req.description = "unleash a roaring meow".to_string();
    req
}

fn assert_cancellation_requests(
    mock_server: &mock::execution_server::TestServer,
    expected: Vec<String>,
) {
    let cancels = mock_server
        .mock_responder
        .cancelation_requests
        .lock()
        .iter()
        .map(|req| req.name.clone())
        .collect::<Vec<_>>();
    assert_eq!(expected, cancels);
}

fn one_second() -> Option<Duration> {
    Some(Duration::from_millis(1000))
}
