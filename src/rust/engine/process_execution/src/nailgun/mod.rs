use std::collections::{BTreeMap, BTreeSet};
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::time::Duration;

use async_trait::async_trait;
use futures::future::{FutureExt, TryFutureExt};
use futures::stream::{BoxStream, StreamExt};
use hashing::Digest;
use log::{debug, trace};
use nails::execution::{self, child_channel, ChildInput, Command};
use task_executor::Executor;
use tokio::net::TcpStream;
use workunit_store::RunningWorkunit;

use crate::local::{CapturedWorkdir, ChildOutput};
use crate::{
  Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, NamedCaches, Platform, Process,
  ProcessCacheScope, ProcessMetadata,
};

#[cfg(test)]
pub mod tests;

mod nailgun_pool;

mod parsed_jvm_command_lines;
#[cfg(test)]
mod parsed_jvm_command_lines_tests;

use nailgun_pool::NailgunPool;
use parsed_jvm_command_lines::ParsedJVMCommandLines;

// Hardcoded constants for connecting to nailgun
static NAILGUN_MAIN_CLASS: &str = "com.martiansoftware.nailgun.NGServer";
static ARGS_TO_START_NAILGUN: [&str; 1] = [":0"];

///
/// Constructs the Process that would be used
/// to start the nailgun servers if we needed to.
///
fn construct_nailgun_server_request(
  nailgun_name: &str,
  args_for_the_jvm: Vec<String>,
  platform_constraint: Option<Platform>,
  nailgun_digest: Digest,
) -> Process {
  let mut full_args = args_for_the_jvm;
  full_args.push(NAILGUN_MAIN_CLASS.to_string());
  full_args.extend(ARGS_TO_START_NAILGUN.iter().map(|&a| a.to_string()));

  Process {
    argv: full_args,
    env: BTreeMap::new(),
    working_directory: None,
    input_files: nailgun_digest,
    output_files: BTreeSet::new(),
    output_directories: BTreeSet::new(),
    timeout: Some(Duration::new(1000, 0)),
    description: format!("Start a nailgun server for {}", nailgun_name),
    level: log::Level::Info,
    append_only_caches: BTreeMap::new(),
    jdk_home: None,
    platform_constraint,
    use_nailgun: hashing::EMPTY_DIGEST,
    execution_slot_variable: None,
    cache_scope: ProcessCacheScope::Always,
  }
}

fn construct_nailgun_client_request(
  original_req: Process,
  client_main_class: String,
  mut client_args: Vec<String>,
) -> Process {
  client_args.insert(0, client_main_class);
  Process {
    argv: client_args,
    jdk_home: None,
    ..original_req
  }
}

///
/// A command runner that can run local requests under nailgun.
///
/// It should only be invoked with local requests.
/// It will read a flag marking an `Process` as nailgunnable.
/// If that flag is set, it will connect to a running nailgun server and run the command there.
/// Otherwise, it will just delegate to the regular local runner.
///
pub struct CommandRunner {
  inner: super::local::CommandRunner,
  nailgun_pool: NailgunPool,
  metadata: ProcessMetadata,
  executor: Executor,
}

impl CommandRunner {
  pub fn new(
    runner: crate::local::CommandRunner,
    metadata: ProcessMetadata,
    workdir_base: PathBuf,
    executor: Executor,
    nailgun_pool_size: usize,
  ) -> Self {
    CommandRunner {
      inner: runner,
      nailgun_pool: NailgunPool::new(workdir_base, nailgun_pool_size, executor.clone()),
      metadata,
      executor,
    }
  }

  fn calculate_nailgun_name(main_class: &str) -> String {
    format!("nailgun_server_{}", main_class)
  }
}

#[async_trait]
impl super::CommandRunner for CommandRunner {
  async fn run(
    &self,
    context: Context,
    workunit: &mut RunningWorkunit,
    req: MultiPlatformProcess,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    let original_request = self.extract_compatible_request(&req).unwrap();

    if original_request.use_nailgun == hashing::EMPTY_DIGEST {
      trace!("The request is not nailgunnable! Short-circuiting to regular process execution");
      return self.inner.run(context, workunit, req).await;
    }
    debug!("Running request under nailgun:\n {:#?}", &original_request);

    // Separate argument lists, to form distinct EPRs for (1) starting the nailgun server and (2) running the client in it.
    let ParsedJVMCommandLines {
      nailgun_args,
      client_main_class,
      ..
    } = ParsedJVMCommandLines::parse_command_lines(&original_request.argv)?;
    let nailgun_name = CommandRunner::calculate_nailgun_name(&client_main_class);

    let nailgun_req = construct_nailgun_server_request(
      &nailgun_name,
      nailgun_args,
      original_request.platform_constraint,
      original_request.use_nailgun,
    );
    trace!("Extracted nailgun request:\n {:#?}", &nailgun_req);

    let nailgun_req_digest = crate::digest(
      MultiPlatformProcess::from(nailgun_req.clone()),
      &self.metadata,
    );

    // Get an instance of a nailgun server for this fingerprint, and then run in its directory.
    let mut nailgun_process = self
      .nailgun_pool
      .acquire(
        nailgun_name,
        nailgun_req,
        nailgun_req_digest,
        self.inner.store.clone(),
      )
      .await
      .map_err(|e| format!("Failed to connect to nailgun! {}", e))?;

    let res = self
      .run_and_capture_workdir(
        original_request,
        context,
        self.inner.store.clone(),
        self.executor.clone(),
        nailgun_process.workdir_path().to_owned(),
        (nailgun_process.name().to_owned(), nailgun_process.address()),
        Platform::current().unwrap(),
      )
      .await;

    // NB: We explicitly release the BorrowedNailgunProcess, because when it is Dropped without
    // release, it assumes that it has been canceled and kills the server.
    nailgun_process.release().await?;

    res
  }

  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    // Request compatibility should be the same as for the local runner, so we just delegate this.
    self.inner.extract_compatible_request(req)
  }
}

#[async_trait]
impl CapturedWorkdir for CommandRunner {
  type WorkdirToken = (String, SocketAddr);

  fn named_caches(&self) -> &NamedCaches {
    self.inner.named_caches()
  }

  async fn run_in_workdir<'a, 'b, 'c>(
    &'a self,
    workdir_path: &'b Path,
    workdir_token: Self::WorkdirToken,
    req: Process,
    _context: Context,
    _exclusive_spawn: bool,
  ) -> Result<BoxStream<'c, Result<ChildOutput, String>>, String> {
    let client_workdir = if let Some(working_directory) = &req.working_directory {
      workdir_path.join(working_directory)
    } else {
      workdir_path.to_path_buf()
    };

    let ParsedJVMCommandLines {
      client_args,
      client_main_class,
      ..
    } = ParsedJVMCommandLines::parse_command_lines(&req.argv)?;

    let (name, addr) = workdir_token;
    debug!("Connected to nailgun instance {} at {}...", name, addr);
    let mut child = {
      // Run the client request in the nailgun we have active.
      let client_req = construct_nailgun_client_request(req, client_main_class, client_args);
      let cmd = Command {
        command: client_req.argv[0].clone(),
        args: client_req.argv[1..].to_vec(),
        env: client_req
          .env
          .iter()
          .map(|(k, v)| (k.clone(), v.clone()))
          .collect(),
        working_dir: client_workdir,
      };
      trace!("Client request: {:#?}", client_req);
      TcpStream::connect(addr)
        .and_then(move |stream| {
          nails::client::handle_connection(nails::Config::default(), stream, cmd, async {
            let (_stdin_write, stdin_read) = child_channel::<ChildInput>();
            stdin_read
          })
        })
        .map_err(|e| format!("Error communicating with server: {}", e))
        .await?
    };

    let output_stream = child
      .output_stream
      .take()
      .unwrap()
      .map(|output| match output {
        execution::ChildOutput::Stdout(bytes) => Ok(ChildOutput::Stdout(bytes)),
        execution::ChildOutput::Stderr(bytes) => Ok(ChildOutput::Stderr(bytes)),
      });
    let exit_code = child
      .wait()
      .map_ok(ChildOutput::Exit)
      .map_err(|e| format!("Error communicating with server: {}", e));

    Ok(futures::stream::select(output_stream, exit_code.into_stream()).boxed())
  }
}
