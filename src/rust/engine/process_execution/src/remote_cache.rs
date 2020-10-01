use std::collections::{BTreeMap, HashSet, VecDeque};
use std::convert::{TryFrom, TryInto};
use std::path::Component;
use std::str::FromStr;
use std::sync::Arc;

use async_trait::async_trait;
use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use fs::RelativePath;
use futures::compat::Future01CompatExt;
use hashing::{Digest, EMPTY_DIGEST};
use remexec::action_cache_client::ActionCacheClient;
use remexec::{ActionResult, Command, FileNode, Tree};
use store::Store;
use tokio_rustls::rustls::ClientConfig;
use tonic::metadata::{AsciiMetadataKey, AsciiMetadataValue};
use tonic::transport::{Channel, ClientTlsConfig, Endpoint};
use tonic::Request;
use workunit_store::{with_workunit, Level, Metric, WorkunitMetadata};

use crate::remote::make_execute_request;
use crate::{
  Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, Platform, Process,
  ProcessMetadata,
};

/// This `CommandRunner` implementation caches results remotely using the Action Cache service
/// of the Remote Execution API.
///
/// This runner expects to sit between the local cache CommandRunner and the CommandRunner
/// that is actually executing the Process. Thus, the local cache will be checked first,
/// then the remote cache, and then execution (local or remote) as necessary if neither cache
/// has a hit. On the way back out of the stack, the result will be stored remotely and
/// then locally.
#[derive(Clone)]
pub struct CommandRunner {
  underlying: Arc<dyn crate::CommandRunner>,
  metadata: ProcessMetadata,
  store: Store,
  action_cache_client: Arc<ActionCacheClient<Channel>>,
  headers: BTreeMap<String, String>,
  platform: Platform,
  cache_read: bool,
  cache_write: bool,
}

impl CommandRunner {
  fn create_tonic_endpoint(
    addr: &str,
    tls_config_opt: Option<&ClientConfig>,
  ) -> Result<Endpoint, String> {
    let uri =
      tonic::transport::Uri::try_from(addr).map_err(|err| format!("invalid address: {}", err))?;
    let endpoint = Channel::builder(uri);
    let maybe_tls_endpoint = if let Some(tls_config) = tls_config_opt {
      endpoint
        .tls_config(ClientTlsConfig::new().rustls_client_config(tls_config.clone()))
        .map_err(|e| format!("TLS setup error: {}", e))?
    } else {
      endpoint
    };
    Ok(maybe_tls_endpoint)
  }

  pub fn new(
    underlying: Arc<dyn crate::CommandRunner>,
    metadata: ProcessMetadata,
    store: Store,
    action_cache_address: &str,
    root_ca_certs: Option<Vec<u8>>,
    oauth_bearer_token: Option<String>,
    headers: BTreeMap<String, String>,
    platform: Platform,
    cache_read: bool,
    cache_write: bool,
  ) -> Result<Self, String> {
    let tls_client_config = match root_ca_certs {
      Some(pem_bytes) => {
        let mut tls_config = ClientConfig::new();
        let mut reader = std::io::Cursor::new(pem_bytes);
        tls_config
          .root_store
          .add_pem_file(&mut reader)
          .map_err(|_| "unexpected state in PEM file add".to_owned())?;
        Some(tls_config)
      }
      _ => None,
    };

    let scheme = if tls_client_config.is_some() {
      "https"
    } else {
      "http"
    };

    let mut headers = headers;
    if let Some(oauth_bearer_token) = oauth_bearer_token {
      headers.insert(
        String::from("authorization"),
        format!("Bearer {}", oauth_bearer_token.trim()),
      );
    }

    let address_with_scheme = format!("{}://{}", scheme, action_cache_address);

    let endpoint = Self::create_tonic_endpoint(&address_with_scheme, tls_client_config.as_ref())?;
    let channel = tonic::transport::Channel::balance_list(vec![endpoint].into_iter());
    let action_cache_client = Arc::new(if headers.is_empty() {
      ActionCacheClient::new(channel)
    } else {
      let headers = headers.clone();
      ActionCacheClient::with_interceptor(channel, move |mut req: Request<()>| {
        let metadata = req.metadata_mut();
        for (key, value) in &headers {
          let key_ascii = AsciiMetadataKey::from_str(key.as_str()).unwrap();
          let value_ascii = AsciiMetadataValue::from_str(value.as_str()).unwrap();
          metadata.insert(key_ascii, value_ascii);
        }
        Ok(req)
      })
    });

    Ok(CommandRunner {
      underlying,
      metadata,
      store,
      action_cache_client,
      headers,
      platform,
      cache_read,
      cache_write,
    })
  }

  /// Create a REAPI `Tree` protobuf for an output directory by traversing down from a Pants
  /// merged final output directory to find the specific path to extract. (REAPI requires
  /// output directories to be stored as `Tree` protos that contain all of the `Directory`
  /// protos that constitute the directory tree.)
  pub(crate) async fn make_tree_for_output_directory(
    root_directory_digest: Digest,
    directory_path: RelativePath,
    store: &Store,
  ) -> Result<Tree, String> {
    // Traverse down from the root directory digest to find the directory digest for
    // the output directory.
    let mut current_directory_digest = root_directory_digest;
    for next_path_component in directory_path.as_ref().components() {
      let next_name = match next_path_component {
        Component::Normal(name) => name
          .to_str()
          .ok_or_else(|| format!("unable to convert '{:?}' to string", name))?,
        _ => return Err("illegal state: unexpected path component in relative path".into()),
      };

      // Load the Directory proto corresponding to `current_directory_digest`.
      let current_directory = match store.load_directory(current_directory_digest).await? {
        Some((dir, _)) => dir,
        None => {
          return Err(format!(
            "illegal state: directory for digest {:?} did not exist locally",
            &current_directory_digest
          ))
        }
      };

      // Scan the current directory for the current path component.
      let dir_node = match current_directory
        .directories
        .iter()
        .find(|dn| dn.name == next_name)
      {
        Some(dn) => dn,
        None => {
          return Err(format!(
            "unable to find path component {:?} in directory",
            next_name
          ))
        }
      };

      // Set the current directory digest to be the digest in the DirectoryNode just found.
      // If there are more path components, then the search will continue there.
      // Otherwise, if this loop ends then the final Directory digest has been found.
      current_directory_digest = dir_node
        .digest
        .as_ref()
        .map(|d| d.try_into())
        .unwrap_or(Ok(EMPTY_DIGEST))?;
    }

    // At this point, `current_directory_digest` holds the digest of the output directory.
    // This will be the root of the Tree. Add it to a queue of digests to traverse.
    let mut tree = Tree::default();

    let mut digest_queue = VecDeque::new();
    digest_queue.push_back(current_directory_digest);

    while let Some(directory_digest) = digest_queue.pop_front() {
      let directory = match store.load_directory(directory_digest).await? {
        Some((dir, _)) => dir,
        None => {
          return Err(format!(
            "illegal state: directory for digest {:?} did not exist locally",
            &current_directory_digest
          ))
        }
      };

      // Add all of the digests for subdirectories into the queue so they are processed
      // in future iterations of the loop.
      for subdirectory_node in &directory.directories {
        let subdirectory_digest = subdirectory_node
          .digest
          .as_ref()
          .map(|d| d.try_into())
          .unwrap_or(Ok(EMPTY_DIGEST))?;
        digest_queue.push_back(subdirectory_digest);
      }

      // Store this directory either as the `root` or one of the `children` if not the root.
      if directory_digest == current_directory_digest {
        tree.root = Some(directory);
      } else {
        tree.children.push(directory)
      }
    }

    Ok(tree)
  }

  pub(crate) async fn extract_output_file(
    root_directory_digest: Digest,
    file_path: RelativePath,
    store: &Store,
  ) -> Result<FileNode, String> {
    // Traverse down from the root directory digest to find the directory digest for
    // the output directory.
    let mut current_directory_digest = root_directory_digest;
    let parent_path = file_path.as_ref().parent();
    let components_opt = parent_path.map(|x| x.components());
    if let Some(components) = components_opt {
      for next_path_component in components {
        let next_name = match next_path_component {
          Component::Normal(name) => name
            .to_str()
            .ok_or_else(|| format!("unable to convert '{:?}' to string", name))?,
          _ => {
            return Err(
              "Illegal state: Found an unexpected path component in relative path.".into(),
            )
          }
        };

        // Load the Directory proto corresponding to `current_directory_digest`.
        let current_directory = match store.load_directory(current_directory_digest).await? {
          Some((dir, _)) => dir,
          None => {
            return Err(format!(
              "Illegal state: The directory for digest {:?} did not exist locally.",
              &current_directory_digest
            ))
          }
        };

        // Scan the current directory for the current path component.
        let dir_node = match current_directory
          .directories
          .iter()
          .find(|dn| dn.name == next_name)
        {
          Some(dn) => dn,
          None => {
            return Err(format!(
              "Unable to find path component {:?} in directory.",
              next_name
            ))
          }
        };

        // Set the current directory digest to be the digest in the DirectoryNode just found.
        // If there are more path components, then the search will continue there.
        // Otherwise, if this loop ends then the final Directory digest has been found.
        current_directory_digest = dir_node
          .digest
          .as_ref()
          .map(|d| d.try_into())
          .unwrap_or(Ok(EMPTY_DIGEST))?;
      }
    }

    // Load the final directory.
    let directory = match store.load_directory(current_directory_digest).await? {
      Some((dir, _)) => dir,
      None => {
        return Err(format!(
          "Illegal state: The directory for digest {:?} did not exist locally.",
          &current_directory_digest
        ))
      }
    };

    // Search for the file.
    let file_base_name = file_path.as_ref().file_name().unwrap();
    directory
      .files
      .iter()
      .find(|n| n.name == file_base_name.to_string_lossy())
      .cloned()
      .ok_or_else(|| format!("File {:?} did not exist locally.", file_path))
  }

  /// Converts a REAPI `Command` and a `FallibleProcessResultWithPlatform` produced from executing
  /// that Command into a REAPI `ActionResult` suitable for upload to the REAPI Action Cache.
  ///
  /// This function also returns a vector of all `Digest`s referenced directly and indirectly by
  /// the `ActionResult` suitable for passing to `Store::ensure_remote_has_recursive`. (The
  /// digests may include both File and Tree digests.)
  pub(crate) async fn make_action_result(
    &self,
    command: &Command,
    result: &FallibleProcessResultWithPlatform,
    store: &Store,
  ) -> Result<(ActionResult, Vec<Digest>), String> {
    // Keep track of digests that need to be uploaded.
    let mut digests = HashSet::new();

    let mut action_result = ActionResult {
      exit_code: result.exit_code,
      stdout_digest: Some(result.stdout_digest.into()),
      stderr_digest: Some(result.stderr_digest.into()),
      ..ActionResult::default()
    };

    digests.insert(result.stdout_digest);
    digests.insert(result.stderr_digest);

    for output_directory in &command.output_directories {
      let tree = Self::make_tree_for_output_directory(
        result.output_directory,
        RelativePath::new(output_directory).unwrap(),
        store,
      )
      .await?;

      let tree_digest = crate::remote::store_proto_locally(&self.store, &tree).await?;
      digests.insert(tree_digest);

      action_result
        .output_directories
        .push(remexec::OutputDirectory {
          path: String::new(),
          tree_digest: Some(tree_digest.into()),
        });
    }

    for output_file in &command.output_files {
      let file_node = Self::extract_output_file(
        result.output_directory,
        RelativePath::new(output_file).unwrap(),
        store,
      )
      .await?;

      let digest = file_node
        .digest
        .map(|d| d.try_into())
        .unwrap_or(Ok(EMPTY_DIGEST))?;

      digests.insert(digest);

      action_result.output_files.push({
        remexec::OutputFile {
          digest: Some(digest.into()),
          path: output_file.to_owned(),
          is_executable: file_node.is_executable,
          ..remexec::OutputFile::default()
        }
      })
    }

    Ok((action_result, digests.into_iter().collect::<Vec<_>>()))
  }

  /// Stores an execution result into the remote Action Cache.
  async fn update_action_cache(
    &self,
    context: &Context,
    request: &Process,
    result: &FallibleProcessResultWithPlatform,
    metadata: &ProcessMetadata,
    command: &Command,
    action_digest: Digest,
    command_digest: Digest,
  ) -> Result<(), String> {
    // Upload the action (and related data, i.e. the embedded command and input files).
    // Assumption: The Action and related data has already been stored locally.
    with_workunit(
      context.workunit_store.clone(),
      "ensure_action_uploaded".to_owned(),
      WorkunitMetadata::with_level(Level::Debug),
      crate::remote::ensure_action_uploaded(
        &self.store,
        command_digest,
        action_digest,
        request.input_files,
      ),
      |_, md| md,
    )
    .await?;

    // Create an ActionResult from the process result.
    let (action_result, digests_for_action_result) = self
      .make_action_result(command, result, &self.store)
      .await?;

    // Ensure that all digests referenced by directly and indirectly by the ActionResult
    // have been uploaded to the remote cache.
    self
      .store
      .ensure_remote_has_recursive(digests_for_action_result)
      .compat()
      .await?;

    let update_action_cache_request = remexec::UpdateActionResultRequest {
      instance_name: metadata
        .instance_name
        .as_ref()
        .cloned()
        .unwrap_or_else(|| "".to_owned()),
      action_digest: Some(action_digest.into()),
      action_result: Some(action_result),
      ..remexec::UpdateActionResultRequest::default()
    };

    let mut client = self.action_cache_client.as_ref().clone();
    client
      .update_action_result(update_action_cache_request)
      .await
      .map_err(crate::remote::rpcerror_to_string)?;

    Ok(())
  }
}

#[async_trait]
impl crate::CommandRunner for CommandRunner {
  async fn run(
    &self,
    req: MultiPlatformProcess,
    context: Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    // Construct the REv2 ExecuteRequest and related data for this execution request.
    let request = self
      .extract_compatible_request(&req)
      .ok_or_else(|| "No compatible Process found for checking remote cache.".to_owned())?;
    let (action, command, _execute_request) =
      make_execute_request(&request, self.metadata.clone())?;

    // Ensure the action and command are stored locally.
    let (command_digest, action_digest) = with_workunit(
      context.workunit_store.clone(),
      "ensure_action_stored_locally".to_owned(),
      WorkunitMetadata::with_level(Level::Debug),
      crate::remote::ensure_action_stored_locally(&self.store, &command, &action),
      |_, md| md,
    )
    .await?;

    // Check the remote Action Cache to see if this request was already computed.
    // If so, return immediately with the result.
    if self.cache_read {
      let response = with_workunit(
        context.workunit_store.clone(),
        "check_action_cache".to_owned(),
        WorkunitMetadata::with_level(Level::Debug),
        crate::remote::check_action_cache(
          action_digest,
          &self.metadata,
          self.platform,
          &context,
          self.action_cache_client.clone(),
          &self.headers,
          self.store.clone(),
        ),
        |_, md| md,
      )
      .await;
      match response {
        Ok(cached_response_opt) => {
          log::debug!(
            "remote cache response: digest={:?}: {:?}",
            action_digest,
            cached_response_opt
          );

          if let Some(cached_response) = cached_response_opt {
            return Ok(cached_response);
          }
        }
        Err(err) => {
          log::warn!("Failed to read from remote cache: {}", err);
        }
      };
    }

    let result = self.underlying.run(req, context.clone()).await?;
    if result.exit_code == 0 && self.cache_write {
      // Store the result in the remote cache if not the product of a remote execution.
      if let Err(err) = self
        .update_action_cache(
          &context,
          &request,
          &result,
          &self.metadata,
          &command,
          action_digest,
          command_digest,
        )
        .await
      {
        log::warn!("Failed to write to remote cache: {}", err);
        context
          .workunit_store
          .increment_counter(Metric::RemoteCacheWriteErrors, 1);
      }
    }

    Ok(result)
  }

  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    self.underlying.extract_compatible_request(req)
  }
}
