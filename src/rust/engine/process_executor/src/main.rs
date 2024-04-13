// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![type_length_limit = "1257309"]

use std::collections::{BTreeMap, BTreeSet};
use std::iter::{FromIterator, Iterator};
use std::path::PathBuf;
use std::process::exit;
use std::sync::Arc;
use std::time::Duration;

use clap::StructOpt;
use fs::{DirectoryDigest, Permissions, RelativePath};
use hashing::{Digest, Fingerprint};
use process_execution::{
    local::KeepSandboxes, CacheContentBehavior, Context, InputDigests, NamedCaches, Platform,
    ProcessCacheScope, ProcessExecutionEnvironment, ProcessExecutionStrategy,
};
use prost::Message;
use protos::gen::build::bazel::remote::execution::v2::{Action, Command};
use protos::gen::buildbarn::cas::UncachedActionResult;
use protos::require_digest;
use remote::remote_cache::RemoteCacheRunnerOptions;
use store::{ImmutableInputs, RemoteProvider, RemoteStoreOptions, Store};
use workunit_store::{in_workunit, Level, WorkunitStore};

#[derive(Clone, Debug, Default)]
struct ProcessMetadata {
    instance_name: Option<String>,
    cache_key_gen_version: Option<String>,
}

#[derive(StructOpt)]
struct CommandSpec {
    #[structopt(last = true)]
    argv: Vec<String>,

    /// Fingerprint (hex string) of the digest to use as the input file tree.
    #[structopt(long)]
    input_digest: Option<Fingerprint>,

    /// Length of the proto-bytes whose digest to use as the input file tree.
    #[structopt(long)]
    input_digest_length: Option<usize>,

    /// Extra platform properties to set on the execution request during remote execution.
    #[structopt(long)]
    extra_platform_property: Vec<String>,

    /// Environment variables with which the process should be run.
    #[structopt(long)]
    env: Vec<String>,

    /// Symlink a JDK from .jdk in the working directory.
    /// For local execution, symlinks to the value of this flag.
    /// For remote execution, just requests that some JDK is symlinked if this flag has any value.
    /// <https://github.com/pantsbuild/pants/issues/6416> will make this less weird in the future.
    #[structopt(long)]
    jdk: Option<PathBuf>,

    /// Path to file that is considered to be output.
    #[structopt(long)]
    output_file_path: Vec<PathBuf>,

    /// Path to directory that is considered to be output.
    #[structopt(long)]
    output_directory_path: Vec<PathBuf>,

    /// Path to execute the binary at relative to its input digest root.
    #[structopt(long)]
    working_directory: Option<PathBuf>,

    #[structopt(long)]
    concurrency_available: Option<usize>,

    #[structopt(long)]
    cache_key_gen_version: Option<String>,
}

#[derive(StructOpt)]
struct ActionDigestSpec {
    /// Fingerprint (hex string) of the digest of the action to run.
    #[structopt(long)]
    action_digest: Option<Fingerprint>,

    /// Length of the proto-bytes whose digest is the action to run.
    #[structopt(long)]
    action_digest_length: Option<usize>,
}

#[derive(StructOpt)]
#[structopt(name = "process_executor", setting = clap::AppSettings::TrailingVarArg)]
struct Opt {
    #[structopt(flatten)]
    command: CommandSpec,

    #[structopt(flatten)]
    action_digest: ActionDigestSpec,

    #[structopt(long)]
    buildbarn_url: Option<String>,

    #[structopt(long)]
    run_under: Option<String>,

    /// The name of a directory (which may or may not exist), where the output tree will be materialized.
    #[structopt(long)]
    materialize_output_to: Option<PathBuf>,

    /// Path to workdir.
    #[structopt(long)]
    work_dir: Option<PathBuf>,

    ///Path to lmdb directory used for local file storage.
    #[structopt(long)]
    local_store_path: Option<PathBuf>,

    /// Path to a directory to be used for named caches.
    #[structopt(long)]
    named_cache_path: Option<PathBuf>,

    #[structopt(long)]
    remote_instance_name: Option<String>,

    /// The host:port of the gRPC server to connect to. Forces remote execution.
    /// If unspecified, local execution will be performed.
    #[structopt(long)]
    server: Option<String>,

    /// Path to file containing root certificate authority certificates for the execution server.
    /// If not set, TLS will not be used when connecting to the execution server.
    #[structopt(long)]
    execution_root_ca_cert_file: Option<PathBuf>,

    /// Path to file containing oauth bearer token for communication with the execution server.
    /// If not set, no authorization will be provided to remote servers.
    #[structopt(long)]
    execution_oauth_bearer_token_path: Option<PathBuf>,

    /// The host:port of the gRPC CAS server to connect to.
    #[structopt(long)]
    cas_server: Option<String>,

    /// Path to file containing root certificate authority certificates for the CAS server.
    /// If not set, TLS will not be used when connecting to the CAS server.
    #[structopt(long)]
    cas_root_ca_cert_file: Option<PathBuf>,

    /// Path to file containing client certificates for the CAS server.
    /// If not set, client authentication will not be used when connecting to the CAS server.
    #[structopt(long)]
    cas_client_certs_file: Option<PathBuf>,

    /// Path to file containing client key for the CAS server.
    /// If not set, client authentication will not be used when connecting to the CAS server.
    #[structopt(long)]
    cas_client_key_file: Option<PathBuf>,

    /// Path to file containing oauth bearer token for communication with the CAS server.
    /// If not set, no authorization will be provided to remote servers.
    #[structopt(long)]
    cas_oauth_bearer_token_path: Option<PathBuf>,

    /// Number of bytes to include per-chunk when uploading bytes.
    /// grpc imposes a hard message-size limit of around 4MB.
    #[structopt(long, default_value = "3145728")]
    upload_chunk_bytes: usize,

    /// Number of retries per request to the store service.
    #[structopt(long, default_value = "3")]
    store_rpc_retries: usize,

    /// Number of concurrent requests to the store service.
    #[structopt(long, default_value = "128")]
    store_rpc_concurrency: usize,

    /// Total size of blobs allowed to be sent in a single API call.
    #[structopt(long, default_value = "4194304")]
    store_batch_api_size_limit: usize,

    /// Number of concurrent requests to the execution service.
    #[structopt(long, default_value = "128")]
    execution_rpc_concurrency: usize,

    /// Number of concurrent requests to the cache service.
    #[structopt(long, default_value = "128")]
    cache_rpc_concurrency: usize,

    /// Overall timeout in seconds for each request from time of submission.
    #[structopt(long, default_value = "600")]
    overall_deadline_secs: u64,

    /// Extra header to pass on remote execution request.
    #[structopt(long)]
    header: Vec<String>,
}

/// A binary which takes args of format:
///  process_executor --env=FOO=bar --env=SOME=value --input-digest=abc123 --input-digest-length=80
///    -- /path/to/binary --flag --otherflag
/// and runs /path/to/binary --flag --otherflag with FOO and SOME set.
/// It outputs its output/err to stdout/err, and exits with its exit code.
///
/// It does not perform $PATH lookup or shell expansion.
#[tokio::main]
async fn main() {
    env_logger::init();
    let workunit_store = WorkunitStore::new(false, log::Level::Debug);
    workunit_store.init_thread_state(None);

    let args = Opt::from_args();

    let mut headers: BTreeMap<String, String> = collection_from_keyvalues(args.header.iter());

    let executor = task_executor::Executor::new();

    let local_store_path = args
        .local_store_path
        .clone()
        .unwrap_or_else(Store::default_path);

    let local_only_store =
        Store::local_only(executor.clone(), local_store_path).expect("Error making local store");
    let store = match (&args.server, &args.cas_server) {
    (_, Some(cas_server)) => {
      let root_ca_certs = args
        .cas_root_ca_cert_file
        .as_ref()
        .map(|path| std::fs::read(path).expect("Error reading root CA certs file"));

      let client_certs = args
        .cas_client_certs_file
        .as_ref()
        .map(|path| std::fs::read(path).expect("Error reading client authentication certs file"));

      let client_key = args
        .cas_client_key_file
        .as_ref()
        .map(|path| std::fs::read(path).expect("Error reading client authentication key file"));

      let mtls_data = match (client_certs, client_key) {
        (Some(certs), Some(key)) => Some((certs, key)),
        (None, None) => None,
        _ => {
          panic!("Must specify both --cas-client-certs-file and --cas-client-key-file or neither")
        }
      };

      let mut headers = BTreeMap::new();
      if let Some(ref oauth_path) = args.cas_oauth_bearer_token_path {
        let token =
          std::fs::read_to_string(oauth_path).expect("Error reading oauth bearer token file");
        headers.insert(
          "authorization".to_owned(),
          format!("Bearer {}", token.trim()),
        );
      }

      let tls_config = grpc_util::tls::Config::new(root_ca_certs, mtls_data)
        .expect("failed parsing root CA certs");

      local_only_store
            .into_with_remote(RemoteStoreOptions {
                provider: RemoteProvider::Reapi,
          store_address: cas_server.to_owned(),
          instance_name: args.remote_instance_name.clone(),
          tls_config,
          headers,
          chunk_size_bytes: args.upload_chunk_bytes,
          timeout: Duration::from_secs(30),
          retries: args.store_rpc_retries,
          concurrency_limit: args.store_rpc_concurrency,

          batch_api_size_limit: args.store_batch_api_size_limit,
        })
        .await
    }
    (None, None) => Ok(local_only_store),
    _ => panic!("Can't specify --server without --cas-server"),
  }
  .expect("Error making remote store");

    let (mut request, process_metadata) = make_request(&store, &args)
        .await
        .expect("Failed to construct request");

    if let Some(run_under) = args.run_under {
        let run_under = shlex::split(&run_under).expect("Could not shlex --run-under arg");
        request.argv = run_under
            .into_iter()
            .chain(request.argv.into_iter())
            .collect();
    }
    let workdir = args.work_dir.unwrap_or_else(std::env::temp_dir);

    let runner: Box<dyn process_execution::CommandRunner> = match args.server {
        Some(address) => {
            let root_ca_certs = args
                .execution_root_ca_cert_file
                .map(|path| std::fs::read(path).expect("Error reading root CA certs file"));

            let client_certs = args
                .cas_client_certs_file
                .as_ref()
                .map(|path| std::fs::read(path).expect("Error reading root client certs file"));

            let client_key = args.cas_client_key_file.as_ref().map(|path| {
                std::fs::read(path).expect("Error reading client authentication key file")
            });

            let mtls_data = match (client_certs, client_key) {
                (Some(certs), Some(key)) => Some((certs, key)),
                (None, None) => None,
                _ => {
                    panic!("Must specify both --cas-client-certs-file and --cas-client-key-file or neither")
                }
            };

            let tls_config = grpc_util::tls::Config::new(root_ca_certs, mtls_data)
                .expect("failed parsing root CA certs");

            if let Some(oauth_path) = args.execution_oauth_bearer_token_path {
                let token = std::fs::read_to_string(oauth_path)
                    .expect("Error reading oauth bearer token file");
                headers.insert(
                    "authorization".to_owned(),
                    format!("Bearer {}", token.trim()),
                );
            }

            let remote_runner = remote::remote::CommandRunner::new(
                &address,
                process_metadata.instance_name.clone(),
                process_metadata.cache_key_gen_version.clone(),
                None,
                tls_config.clone(),
                headers.clone(),
                store.clone(),
                executor.clone(),
                Duration::from_secs(args.overall_deadline_secs),
                Duration::from_millis(100),
                args.execution_rpc_concurrency,
            )
            .await
            .expect("Failed to make remote command runner");

            let command_runner_box: Box<dyn process_execution::CommandRunner> = {
                Box::new(
                    remote::remote_cache::CommandRunner::from_provider_options(
                        RemoteCacheRunnerOptions {
                            inner: Arc::new(remote_runner),
                            instance_name: process_metadata.instance_name.clone(),
                            process_cache_namespace: process_metadata.cache_key_gen_version.clone(),
                            executor,
                            store: store.clone(),
                            cache_read: true,
                            cache_write: true,
                            warnings_behavior:
                                remote::remote_cache::RemoteCacheWarningsBehavior::Backoff,
                            cache_content_behavior: CacheContentBehavior::Defer,
                            append_only_caches_base_path: args
                                .named_cache_path
                                .map(|p| p.to_string_lossy().to_string()),
                        },
                        RemoteStoreOptions {
                            provider: RemoteProvider::Reapi,
                            instance_name: process_metadata.instance_name.clone(),
                            store_address: address,
                            tls_config,
                            headers,
                            concurrency_limit: args.cache_rpc_concurrency,
                            timeout: Duration::from_secs(2),
                            retries: 0,
                            batch_api_size_limit: 0,
                            chunk_size_bytes: 0,
                        },
                    )
                    .await
                    .expect("Failed to make remote cache command runner"),
                )
            };

            command_runner_box
        }
        None => Box::new(process_execution::local::CommandRunner::new(
            store.clone(),
            executor,
            workdir.clone(),
            NamedCaches::new_local(
                args.named_cache_path
                    .unwrap_or_else(NamedCaches::default_local_path),
            ),
            ImmutableInputs::new(store.clone(), &workdir).unwrap(),
            KeepSandboxes::Never,
        )) as Box<dyn process_execution::CommandRunner>,
    };

    let result = in_workunit!("process_executor", Level::Info, |workunit| async move {
        runner.run(Context::default(), workunit, request).await
    })
    .await
    .expect("Error executing");

    if let Some(output) = args.materialize_output_to {
        // NB: We use `output` as the root directory, because there is no need to
        // memoize a check for whether some other parent directory is hardlinkable.
        let output_root = output.clone();
        store
            .materialize_directory(
                output,
                &output_root,
                result.output_directory,
                false,
                &BTreeSet::new(),
                Permissions::Writable,
            )
            .await
            .unwrap();
    }

    let stdout: Vec<u8> = store
        .load_file_bytes_with(result.stdout_digest, |bytes| bytes.to_vec())
        .await
        .unwrap();

    let stderr: Vec<u8> = store
        .load_file_bytes_with(result.stderr_digest, |bytes| bytes.to_vec())
        .await
        .unwrap();

    print!("{}", String::from_utf8(stdout).unwrap());
    eprint!("{}", String::from_utf8(stderr).unwrap());
    exit(result.exit_code);
}

async fn make_request(
    store: &Store,
    args: &Opt,
) -> Result<(process_execution::Process, ProcessMetadata), String> {
    let execution_environment = if args.server.is_some() {
        let strategy = ProcessExecutionStrategy::RemoteExecution(collection_from_keyvalues(
            args.command.extra_platform_property.iter(),
        ));
        ProcessExecutionEnvironment {
            name: None,
            // TODO: Make configurable.
            platform: Platform::Linux_x86_64,
            strategy,
        }
    } else {
        ProcessExecutionEnvironment {
            name: None,
            platform: Platform::current().unwrap(),
            strategy: ProcessExecutionStrategy::Local,
        }
    };

    match (
    args.command.input_digest,
    args.command.input_digest_length,
    args.action_digest.action_digest,
    args.action_digest.action_digest_length,
    args.buildbarn_url.as_ref(),
  ) {
    (Some(input_digest), Some(input_digest_length), None, None, None) => {
      make_request_from_flat_args(store, args, Digest::new(input_digest, input_digest_length), execution_environment).await
    }
    (None, None, Some(action_fingerprint), Some(action_digest_length), None) => {
      extract_request_from_action_digest(
        store,
        Digest::new(action_fingerprint, action_digest_length),
        execution_environment,
        args.remote_instance_name.clone(),
        args.command.cache_key_gen_version.clone(),
      ).await
    }
    (None, None, None, None, Some(buildbarn_url)) => {
      extract_request_from_buildbarn_url(
        store,
        buildbarn_url,
        execution_environment,
        args.command.cache_key_gen_version.clone()
      ).await
    }
    (None, None, None, None, None) => {
      Err("Must specify either action input digest or action digest or buildbarn URL".to_owned())
    }
    _ => {
      Err("Unsupported combination of arguments - can only set one of action digest or all other action-specifying flags".to_owned())
    }
  }
}

async fn make_request_from_flat_args(
    store: &Store,
    args: &Opt,
    input_files: Digest,
    execution_environment: ProcessExecutionEnvironment,
) -> Result<(process_execution::Process, ProcessMetadata), String> {
    let output_files = args
        .command
        .output_file_path
        .iter()
        .map(RelativePath::new)
        .collect::<Result<BTreeSet<_>, _>>()?;
    let output_directories = args
        .command
        .output_directory_path
        .iter()
        .map(RelativePath::new)
        .collect::<Result<BTreeSet<_>, _>>()?;

    let working_directory = args
        .command
        .working_directory
        .clone()
        .map(|path| {
            RelativePath::new(path)
                .map_err(|err| format!("working-directory must be a relative path: {err:?}"))
        })
        .transpose()?;

    // TODO: Add support for immutable inputs.
    let input_digests = InputDigests::new(
        store,
        DirectoryDigest::from_persisted_digest(input_files),
        BTreeMap::default(),
        BTreeSet::default(),
    )
    .await
    .map_err(|e| format!("Could not create input digest for process: {e:?}"))?;

    let process = process_execution::Process {
        argv: args.command.argv.clone(),
        env: collection_from_keyvalues(args.command.env.iter()),
        working_directory,
        input_digests,
        output_files,
        output_directories,
        timeout: Some(Duration::new(15 * 60, 0)),
        description: "process_executor".to_string(),
        level: Level::Info,
        append_only_caches: BTreeMap::new(),
        jdk_home: args.command.jdk.clone(),
        execution_slot_variable: None,
        concurrency_available: args.command.concurrency_available.unwrap_or(0),
        cache_scope: ProcessCacheScope::Always,
        execution_environment,
        remote_cache_speculation_delay: Duration::from_millis(0),
        attempt: 0,
    };
    let metadata = ProcessMetadata {
        instance_name: args.remote_instance_name.clone(),
        cache_key_gen_version: args.command.cache_key_gen_version.clone(),
    };
    Ok((process, metadata))
}

#[allow(clippy::redundant_closure)] // False positives for prost::Message::decode: https://github.com/rust-lang/rust-clippy/issues/5939
async fn extract_request_from_action_digest(
    store: &Store,
    action_digest: Digest,
    execution_environment: ProcessExecutionEnvironment,
    instance_name: Option<String>,
    cache_key_gen_version: Option<String>,
) -> Result<(process_execution::Process, ProcessMetadata), String> {
    let action = store
        .load_file_bytes_with(action_digest, |bytes| Action::decode(bytes))
        .await
        .map_err(|e| e.enrich("Could not load action proto from CAS").to_string())?
        .map_err(|err| format!("Error deserializing action proto {action_digest:?}: {err:?}"))?;

    let command_digest = require_digest(&action.command_digest)
        .map_err(|err| format!("Bad Command digest: {err:?}"))?;
    let command = store
        .load_file_bytes_with(command_digest, |bytes| Command::decode(bytes))
        .await
        .map_err(|e| {
            e.enrich("Could not load command proto from CAS")
                .to_string()
        })?
        .map_err(|err| format!("Error deserializing command proto {command_digest:?}: {err:?}"))?;
    let working_directory = if command.working_directory.is_empty() {
        None
    } else {
        Some(
            RelativePath::new(command.working_directory)
                .map_err(|err| format!("working-directory must be a relative path: {err:?}"))?,
        )
    };

    let input_digests = InputDigests::with_input_files(DirectoryDigest::from_persisted_digest(
        require_digest(&action.input_root_digest)
            .map_err(|err| format!("Bad input root digest: {err:?}"))?,
    ));

    // In case the local Store doesn't have the input root Directory,
    // have it fetch it and identify it as a Directory, so that it doesn't get confused about the unknown metadata.
    store
        .load_directory(input_digests.complete.as_digest())
        .await
        .map_err(|e| e.to_string())?;

    let process = process_execution::Process {
        argv: command.arguments,
        env: command
            .environment_variables
            .iter()
            .filter(|env| {
                // Filter out environment variables which will be (re-)set by ExecutionRequest
                // construction.
                env.name != process_execution::CACHE_KEY_TARGET_PLATFORM_ENV_VAR_NAME
            })
            .map(|env| (env.name.clone(), env.value.clone()))
            .collect(),
        working_directory,
        input_digests,
        output_files: command
            .output_files
            .iter()
            .map(RelativePath::new)
            .collect::<Result<_, _>>()?,
        output_directories: command
            .output_directories
            .iter()
            .map(RelativePath::new)
            .collect::<Result<_, _>>()?,
        timeout: action.timeout.map(|timeout| {
            Duration::from_nanos(timeout.nanos as u64 + timeout.seconds as u64 * 1000000000)
        }),
        execution_slot_variable: None,
        concurrency_available: 0,
        description: "".to_string(),
        level: Level::Error,
        append_only_caches: BTreeMap::new(),
        jdk_home: None,
        cache_scope: ProcessCacheScope::Always,
        execution_environment,
        remote_cache_speculation_delay: Duration::from_millis(0),
        attempt: 0,
    };

    let metadata = ProcessMetadata {
        instance_name,
        cache_key_gen_version,
    };

    Ok((process, metadata))
}

async fn extract_request_from_buildbarn_url(
    store: &Store,
    buildbarn_url: &str,
    execution_environment: ProcessExecutionEnvironment,
    cache_key_gen_version: Option<String>,
) -> Result<(process_execution::Process, ProcessMetadata), String> {
    let url_parts: Vec<&str> = buildbarn_url.trim_end_matches('/').split('/').collect();
    if url_parts.len() < 4 {
        return Err("Buildbarn URL didn't have enough parts".to_owned());
    }
    let interesting_parts = &url_parts[url_parts.len() - 4..url_parts.len()];
    let kind = interesting_parts[0];
    let instance = interesting_parts[1];

    let action_digest = match kind {
        "action" => {
            let action_fingerprint = Fingerprint::from_hex_string(interesting_parts[2])?;
            let action_digest_length: usize = interesting_parts[3].parse().map_err(|err| {
                format!("Couldn't parse action digest length as a number: {err:?}")
            })?;
            Digest::new(action_fingerprint, action_digest_length)
        }
        "uncached_action_result" => {
            let action_result_fingerprint = Fingerprint::from_hex_string(interesting_parts[2])?;
            let action_result_digest_length: usize =
                interesting_parts[3].parse().map_err(|err| {
                    format!(
                        "Couldn't parse uncached action digest result length as a number: {err:?}"
                    )
                })?;
            let action_result_digest =
                Digest::new(action_result_fingerprint, action_result_digest_length);

            let action_result = store
                .load_file_bytes_with(action_result_digest, |bytes| {
                    UncachedActionResult::decode(bytes)
                })
                .await
                .map_err(|e| e.enrich("Could not load action result proto").to_string())?
                .map_err(|err| format!("Error deserializing action result proto: {err:?}"))?;

            require_digest(&action_result.action_digest)?
        }
        _ => {
            return Err(format!(
                "Wrong kind in buildbarn URL; wanted action or uncached_action_result, got {kind}"
            ));
        }
    };

    extract_request_from_action_digest(
        store,
        action_digest,
        execution_environment,
        Some(instance.to_owned()),
        cache_key_gen_version,
    )
    .await
}

fn collection_from_keyvalues<Str, It, Col>(keyvalues: It) -> Col
where
    Str: AsRef<str>,
    It: Iterator<Item = Str>,
    Col: FromIterator<(String, String)>,
{
    keyvalues
        .map(|kv| {
            let mut parts = kv.as_ref().splitn(2, '=');
            (
                parts.next().unwrap().to_string(),
                parts.next().unwrap_or_default().to_string(),
            )
        })
        .collect()
}
