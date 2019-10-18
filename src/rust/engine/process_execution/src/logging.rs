use crate::{
  Context, ExecuteProcessRequest, FallibleExecuteProcessResult, MultiPlatformExecuteProcessRequest,
};
use boxfuture::{BoxFuture, Boxable};
use futures::Future;
use hashing::Digest;
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::BTreeSet;
use std::io::Write;
use std::sync::Arc;

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
pub struct DigestAndEntryType {
  pub digest: Digest,
  pub entry_type: store::EntryType,
}

impl PartialOrd for DigestAndEntryType {
  fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
    Some(self.cmp(other))
  }
}

impl Ord for DigestAndEntryType {
  fn cmp(&self, other: &Self) -> Ordering {
    let fingerprint_cmp = self.digest.0.cmp(&other.digest.0);
    if fingerprint_cmp != Ordering::Equal {
      return fingerprint_cmp;
    }
    let size_cmp = self.digest.1.cmp(&other.digest.1);
    if fingerprint_cmp != Ordering::Equal {
      return size_cmp;
    }
    self.entry_type.cmp(&other.entry_type)
  }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Serialize)]
pub struct LogEntry {
  pub flattened_input_digests: BTreeSet<DigestAndEntryType>,
  pub flattened_output_digests: Option<BTreeSet<DigestAndEntryType>>,
}

pub struct CommandRunner {
  pub delegate: Arc<dyn crate::CommandRunner>,
  pub store: store::Store,
}

impl crate::CommandRunner for CommandRunner {
  fn run(
    &self,
    req: MultiPlatformExecuteProcessRequest,
    context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let compatible_request = self.extract_compatible_request(&req).expect("TODO");
    let store = self.store.clone();

    self
      .delegate
      .run(req, context.clone())
      .then(move |response| {
        if context.stats_logfile.is_some() {
          let output_future = if let Ok(response) = &response {
            let output_directory = response.output_directory;
            store
              .expand_transitive_digests(vec![output_directory], context.workunit_store.clone())
              .map(Some)
              .to_boxed()
          } else {
            futures::future::ok(None).to_boxed()
          };
          futures::future::ok(response)
            .join(
              store
                .expand_transitive_digests(
                  vec![compatible_request.input_files],
                  context.workunit_store.clone(),
                )
                .join(output_future),
            )
            .and_then(
              move |(response, (flattened_input_digests, flattened_output_digests))| {
                if let Some(logfile) = context.stats_logfile.as_ref() {
                  let log_entry = LogEntry {
                    flattened_input_digests: flattened_input_digests
                      .into_iter()
                      .map(|(digest, entry_type)| DigestAndEntryType { digest, entry_type })
                      .collect(),
                    flattened_output_digests: flattened_output_digests.map(|digests| {
                      digests
                        .into_iter()
                        .map(|(digest, entry_type)| DigestAndEntryType { digest, entry_type })
                        .collect()
                    }),
                  };
                  writeln!(
                    logfile.lock(),
                    "{}",
                    serde_json::to_string(&log_entry).unwrap()
                  )
                  .map_err(|err| format!("Error writing log file: {}", err))?;
                }
                response
              },
            )
            .to_boxed()
        } else {
          futures::future::done(response).to_boxed()
        }
      })
      .to_boxed()
  }

  fn extract_compatible_request(
    &self,
    req: &MultiPlatformExecuteProcessRequest,
  ) -> Option<ExecuteProcessRequest> {
    self.delegate.extract_compatible_request(req)
  }
}
