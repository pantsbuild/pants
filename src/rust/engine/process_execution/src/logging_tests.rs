
use crate::logging::{DigestAndEntryType, LogEntry};
use crate::{
  CommandRunner, Context, ExecuteProcessRequest, FallibleExecuteProcessResult,
  MultiPlatformExecuteProcessRequest, Platform,
};
use boxfuture::{BoxFuture, Boxable};
use bytes::Bytes;
use futures::Future;
use hashing::Digest;
use maplit::btreeset;
use parking_lot::Mutex;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use store::EntryType;
use testutil::data::{TestData, TestDirectory};
use workunit_store::WorkUnitStore;

struct StubCommandRunner {
  results: Mutex<Vec<FallibleExecuteProcessResult>>,
}

impl crate::CommandRunner for StubCommandRunner {
  fn run(
    &self,
    _req: MultiPlatformExecuteProcessRequest,
    _context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    futures::future::ok(self.results.lock().remove(0)).to_boxed()
  }

  fn extract_compatible_request(
    &self,
    req: &MultiPlatformExecuteProcessRequest,
  ) -> Option<ExecuteProcessRequest> {
    req.0.values().cloned().next()
  }
}

#[test]
fn writes_line_per_execution() {
  let executor = task_executor::Executor::new();

  let stub_command_runner = StubCommandRunner {
    results: Mutex::new(vec![
      make_response_with_outputs(hashing::EMPTY_DIGEST),
      make_response_with_outputs(TestDirectory::nested_and_not().digest()),
    ]),
  };
  let store_dir = tempfile::tempdir().unwrap();
  let store = store::Store::local_only(executor.clone(), store_dir.path()).unwrap();
  executor
    .block_on(futures::future::join_all(vec![
      store.record_directory(&TestDirectory::nested_and_not().directory(), false),
      store.record_directory(&TestDirectory::containing_roland().directory(), false),
      store.record_directory(&TestDirectory::nested().directory(), false),
      store.store_file_bytes(TestData::roland().bytes(), false),
    ]))
    .unwrap();

  let command_runner = crate::logging::CommandRunner {
    delegate: Arc::new(stub_command_runner),
    store: store,
  };

  let eprs = vec![
    make_request_with_inputs(TestDirectory::nested().digest()),
    make_request_with_inputs(hashing::EMPTY_DIGEST),
  ];

  let out_dir = tempfile::tempdir().unwrap();
  let out_file = out_dir.path().join("out.json");

  {
    // Scope for dropping logfile so it gets closed.
    let logfile = Some(Arc::new(Mutex::new(
      std::fs::File::create(&out_file).unwrap(),
    )));

    let context = Context {
      workunit_store: WorkUnitStore::default(),
      build_id: String::new(),
      stats_logfile: logfile,
    };

    for epr in eprs {
      command_runner.run(epr, context.clone()).wait().unwrap();
    }
  }

  let found: Vec<LogEntry> = std::fs::read_to_string(out_file)
    .unwrap()
    .lines()
    .map(|line| serde_json::from_str(line).unwrap())
    .collect();

  let empty_dir = DigestAndEntryType {
    digest: hashing::EMPTY_DIGEST,
    entry_type: EntryType::Directory,
  };

  assert_eq!(
    found,
    vec![
      LogEntry {
        flattened_input_digests: btreeset![
          DigestAndEntryType {
            digest: TestDirectory::nested().digest(),
            entry_type: EntryType::Directory,
          },
          DigestAndEntryType {
            digest: TestDirectory::containing_roland().digest(),
            entry_type: EntryType::Directory,
          },
          DigestAndEntryType {
            digest: TestData::roland().digest(),
            entry_type: EntryType::File,
          },
        ],
        flattened_output_digests: Some(btreeset![empty_dir.clone()]),
      },
      LogEntry {
        flattened_input_digests: btreeset![empty_dir.clone()],
        flattened_output_digests: Some(btreeset![
          DigestAndEntryType {
            digest: TestDirectory::nested_and_not().digest(),
            entry_type: EntryType::Directory,
          },
          DigestAndEntryType {
            digest: TestDirectory::containing_roland().digest(),
            entry_type: EntryType::Directory,
          },
          DigestAndEntryType {
            digest: TestData::roland().digest(),
            entry_type: EntryType::File,
          },
        ]),
      },
    ],
  )
}

fn make_request_with_inputs(inputs: Digest) -> MultiPlatformExecuteProcessRequest {
  MultiPlatformExecuteProcessRequest::from(ExecuteProcessRequest {
    input_files: inputs,
    argv: vec![],
    env: BTreeMap::default(),
    output_files: BTreeSet::default(),
    output_directories: BTreeSet::default(),
    timeout: std::time::Duration::from_secs(1),
    description: String::new(),
    unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
      hashing::EMPTY_DIGEST,
    jdk_home: None,
    target_platform: Platform::None,
  })
}

fn make_response_with_outputs(outputs: Digest) -> FallibleExecuteProcessResult {
  FallibleExecuteProcessResult {
    output_directory: outputs,
    stdout: Bytes::new(),
    stderr: Bytes::new(),
    exit_code: 0,
    execution_attempts: vec![],
  }
}
