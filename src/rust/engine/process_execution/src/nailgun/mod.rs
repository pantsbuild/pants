use std::collections::{BTreeMap, BTreeSet};
use std::fmt::{self, Debug};
use std::net::SocketAddr;
use std::path::{Path, PathBuf};

use async_trait::async_trait;
use futures::future::{FutureExt, TryFutureExt};
use futures::stream::{BoxStream, StreamExt};
use log::{debug, trace};
use nails::execution::{self, child_channel, ChildInput, Command};
use store::Store;
use task_executor::Executor;
use tokio::net::TcpStream;
use workunit_store::{in_workunit, Metric, RunningWorkunit};

use crate::local::{prepare_workdir, CapturedWorkdir, ChildOutput};
use crate::{
    Context, FallibleProcessResultWithPlatform, InputDigests, Platform, Process, ProcessError,
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

fn construct_nailgun_server_request(
    client_request: Process,
    input_digests: InputDigests,
    nailgun_name: &str,
    args_for_the_jvm: Vec<String>,
) -> Process {
    let mut full_args = args_for_the_jvm;
    full_args.push(NAILGUN_MAIN_CLASS.to_string());
    full_args.extend(ARGS_TO_START_NAILGUN.iter().map(|&a| a.to_string()));

    Process {
        argv: full_args,
        input_digests,
        output_files: BTreeSet::new(),
        output_directories: BTreeSet::new(),
        timeout: None,
        description: format!("nailgun server for {}", nailgun_name),
        level: log::Level::Info,
        execution_slot_variable: None,
        env: client_request.env,
        append_only_caches: client_request.append_only_caches,
        ..client_request
    }
}

fn construct_nailgun_client_request(
    original_req: Process,
    input_digests: InputDigests,
    client_main_class: String,
    mut client_args: Vec<String>,
) -> Process {
    client_args.insert(0, client_main_class);
    Process {
        argv: client_args,
        jdk_home: None,
        input_digests,
        // The append_only_caches are created and preserved by the server.
        append_only_caches: BTreeMap::new(),
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
    executor: Executor,
}

impl CommandRunner {
    pub fn new(
        runner: crate::local::CommandRunner,
        workdir_base: PathBuf,
        store: Store,
        executor: Executor,
        nailgun_pool_size: usize,
    ) -> Self {
        CommandRunner {
            inner: runner,
            nailgun_pool: NailgunPool::new(
                workdir_base,
                nailgun_pool_size,
                store,
                executor.clone(),
            ),
            executor,
        }
    }

    fn calculate_nailgun_name(main_class: &str) -> String {
        format!("nailgun_server_{}", main_class)
    }
}

impl Debug for CommandRunner {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("nailgun::CommandRunner")
            .field("inner", &self.inner)
            .finish_non_exhaustive()
    }
}

#[async_trait]
impl super::CommandRunner for CommandRunner {
    async fn run(
        &self,
        context: Context,
        workunit: &mut RunningWorkunit,
        req: Process,
    ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
        if req.input_digests.use_nailgun.is_empty() {
            trace!(
                "The request is not nailgunnable! Short-circuiting to regular process execution"
            );
            return self.inner.run(context, workunit, req).await;
        }
        debug!("Running request under nailgun:\n {:?}", req);

        in_workunit!(
            "run_nailgun_process",
            // NB: See engine::nodes::NodeKey::workunit_level for more information on why this workunit
            // renders at the Process's level.
            req.level,
            desc = Some(req.description.clone()),
            |workunit| async move {
                workunit.increment_counter(Metric::LocalExecutionRequests, 1);

                // Separate argument lists, to form distinct EPRs for
                //  1. starting the nailgun server
                //  2. running the client against it
                let ParsedJVMCommandLines {
                    nailgun_args,
                    client_args,
                    client_main_class,
                    ..
                } = ParsedJVMCommandLines::parse_command_lines(&req.argv)
                    .map_err(ProcessError::Unclassified)?;

                let nailgun_name = CommandRunner::calculate_nailgun_name(&client_main_class);
                let (client_input_digests, server_input_digests) =
                    req.input_digests.nailgun_client_and_server();
                let client_req = construct_nailgun_client_request(
                    req.clone(),
                    client_input_digests,
                    client_main_class,
                    client_args,
                );
                let server_req = construct_nailgun_server_request(
                    req,
                    server_input_digests,
                    &nailgun_name,
                    nailgun_args,
                );
                trace!("Running request under nailgun:\n {:#?}", &client_req);

                // Get an instance of a nailgun server for this fingerprint, and then run in its directory.
                let mut nailgun_process = self
                    .nailgun_pool
                    .acquire(
                        server_req,
                        self.inner.named_caches(),
                        self.inner.immutable_inputs(),
                    )
                    .await
                    .map_err(|e| e.enrich("Failed to connect to nailgun"))?;

                // Prepare the workdir.
                let exclusive_spawn = prepare_workdir(
                    nailgun_process.workdir_path().to_owned(),
                    &client_req,
                    client_req.input_digests.input_files.clone(),
                    self.inner.store.clone(),
                    self.executor.clone(),
                    self.inner.named_caches(),
                    self.inner.immutable_inputs(),
                )
                .await?;

                let res = self
                    .run_and_capture_workdir(
                        client_req,
                        context,
                        self.inner.store.clone(),
                        self.executor.clone(),
                        nailgun_process.workdir_path().to_owned(),
                        (nailgun_process.name().to_owned(), nailgun_process.address()),
                        exclusive_spawn,
                        Platform::current().unwrap(),
                    )
                    .await;

                // NB: We explicitly release the BorrowedNailgunProcess, because when it is Dropped without
                // release, it assumes that it has been canceled and kills the server.
                nailgun_process.release().await?;

                Ok(res?)
            }
        )
        .await
    }
}

#[async_trait]
impl CapturedWorkdir for CommandRunner {
    type WorkdirToken = (String, SocketAddr);

    async fn run_in_workdir<'a, 'b, 'c>(
        &'a self,
        workdir_path: &'b Path,
        workdir_token: Self::WorkdirToken,
        req: Process,
        _exclusive_spawn: bool,
    ) -> Result<BoxStream<'c, Result<ChildOutput, String>>, String> {
        let client_workdir = if let Some(working_directory) = &req.working_directory {
            workdir_path.join(working_directory)
        } else {
            workdir_path.to_path_buf()
        };

        let (name, addr) = workdir_token;
        debug!("Connected to nailgun instance {} at {}...", name, addr);
        let mut child = {
            // Run the client request in the nailgun we have active.
            let cmd = Command {
                command: req.argv[0].clone(),
                args: req.argv[1..].to_vec(),
                env: req
                    .env
                    .iter()
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect(),
                working_dir: client_workdir,
            };
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
