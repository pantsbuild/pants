use std::collections::{BTreeMap, VecDeque};
use std::convert::TryInto;
use std::path::Component;
use std::sync::Arc;

use async_trait::async_trait;
use bazel_protos::call_option;
use bazel_protos::remote_execution::{
  ActionResult, Command, FileNode, Tree, UpdateActionResultRequest,
};
use fs::RelativePath;
use futures::compat::Future01CompatExt;
use hashing::Digest;
use store::Store;
use workunit_store::{with_workunit, Level, WorkunitMetadata};

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
  action_cache_client: Arc<bazel_protos::remote_execution_grpc::ActionCacheClient>,
  headers: BTreeMap<String, String>,
  platform: Platform,
  cache_read: bool,
  cache_write: bool,
}

impl CommandRunner {
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
    let env = Arc::new(grpcio::EnvBuilder::new().build());
    let channel = {
      let builder = grpcio::ChannelBuilder::new(env);
      if let Some(ref root_ca_certs) = root_ca_certs {
        let creds = grpcio::ChannelCredentialsBuilder::new()
          .root_cert(root_ca_certs.clone())
          .build();
        builder.secure_connect(action_cache_address, creds)
      } else {
        builder.connect(action_cache_address)
      }
    };
    let action_cache_client = Arc::new(
      bazel_protos::remote_execution_grpc::ActionCacheClient::new(channel),
    );

    let mut headers = headers;
    if let Some(oauth_bearer_token) = oauth_bearer_token {
      headers.insert(
        String::from("authorization"),
        format!("Bearer {}", oauth_bearer_token.trim()),
      );
    }

    // Validate any configured static headers.
    call_option(&headers, None)?;

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
      current_directory_digest = dir_node.get_digest().try_into()?;
    }

    // At this point, `current_directory_digest` holds the digest of the output directory.
    // This will be the root of the Tree. Add it to a queue of digests to traverse.
    let mut tree = Tree::new();

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
        digest_queue.push_back(subdirectory_node.get_digest().try_into()?);
      }

      // Store this directory either as the `root` or one of the `children` if not the root.
      if directory_digest == current_directory_digest {
        tree.set_root(directory);
      } else {
        tree.mut_children().push(directory)
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
        current_directory_digest = dir_node.get_digest().try_into()?;
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
      .find(|n| n.get_name() == file_base_name)
      .cloned()
      .ok_or_else(|| format!("File {:?} did not exist locally.", file_path))
  }

  async fn make_action_result(
    &self,
    command: &Command,
    result: &FallibleProcessResultWithPlatform,
    store: &Store,
  ) -> Result<ActionResult, String> {
    let mut action_result = ActionResult::new();
    action_result.set_exit_code(result.exit_code);

    action_result.set_stdout_digest(result.stdout_digest.into());
    action_result.set_stderr_digest(result.stderr_digest.into());

    let mut tree_digests = Vec::new();
    for output_directory in &command.output_directories {
      let tree = Self::make_tree_for_output_directory(
        result.output_directory,
        RelativePath::new(output_directory).unwrap(),
        store,
      )
      .await?;

      let tree_digest = crate::remote::store_proto_locally(&self.store, &tree).await?;
      tree_digests.push(tree_digest);

      action_result.mut_output_directories().push({
        let mut directory = bazel_protos::remote_execution::OutputDirectory::new();
        directory.set_path(String::new());
        directory.set_tree_digest(tree_digest.into());
        directory
      });
    }

    store
      .ensure_remote_has_recursive(tree_digests)
      .compat()
      .await?;

    let mut file_digests = Vec::new();
    for output_file in &command.output_files {
      let file_node = Self::extract_output_file(
        result.output_directory,
        RelativePath::new(output_file).unwrap(),
        store,
      )
      .await?;

      file_digests.push(file_node.get_digest().try_into()?);

      action_result.mut_output_files().push({
        let mut file = bazel_protos::remote_execution::OutputFile::new();
        let digest: Digest = file_node.get_digest().try_into()?;
        file.set_digest(digest.into());
        file.set_is_executable(file_node.get_is_executable());
        file.set_path(output_file.to_owned());
        file
      })
    }

    store
      .ensure_remote_has_recursive(file_digests)
      .compat()
      .await?;

    Ok(action_result)
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
    let action_result = self
      .make_action_result(command, result, &self.store)
      .await?;

    let mut update_action_cache_request = UpdateActionResultRequest::new();
    if let Some(ref instance_name) = metadata.instance_name {
      update_action_cache_request.set_instance_name(instance_name.clone());
    }
    update_action_cache_request.set_action_digest(action_digest.into());
    update_action_cache_request.set_action_result(action_result);

    let call_opt = call_option(&self.headers, Some(context.build_id.clone()))?;

    self
      .action_cache_client
      .update_action_result_async_opt(&update_action_cache_request, call_opt)
      .unwrap()
      .compat()
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
    let request = self.extract_compatible_request(&req).unwrap();
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
        log::warn!("Failed to update remote cache: {}", err)
      }
    }

    Ok(result)
  }

  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    self.underlying.extract_compatible_request(req)
  }
}
