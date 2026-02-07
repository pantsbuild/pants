// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![type_length_limit = "1257309"]

use std::collections::{BTreeMap, BTreeSet};
use std::iter::{FromIterator, Iterator};
use std::path::PathBuf;
use std::process::exit;
use std::sync::Arc;
use std::time::Duration;

use clap::Parser;
use fs::{DirectoryDigest, Permissions, RelativePath};
use hashing::{Digest, Fingerprint};
use process_execution::{
    CacheContentBehavior, Context, InputDigests, NamedCaches, Platform, ProcessCacheScope,
    ProcessConcurrency, ProcessExecutionEnvironment, ProcessExecutionStrategy,
    local::KeepSandboxes,
};
use prost::Message;
use protos::pb::build::bazel::remote::execution::v2::{Action, Command};
use protos::pb::buildbarn::cas::UncachedActionResult;
use protos::require_digest;
use remote::remote_cache::RemoteCacheRunnerOptions;
use store::{ImmutableInputs, RemoteProvider, RemoteStoreOptions, Store, StoreCliOpt};
use tokio::sync::RwLock;
use workunit_store::{Level, WorkunitStore, in_workunit};

#[derive(Clone, Debug, Default)]
struct ProcessMetadata {
    instance_name: Option<String>,
    cache_key_gen_version: Option<String>,
}

#[derive(Parser)]
struct CommandSpec {
    #[arg(last = true)]
    argv: Vec<String>,

    /// Fingerprint (hex string) of the digest to use as the input file tree.
    #[arg(long)]
    input_digest: Option<Fingerprint>,

    /// Length of the proto-bytes whose digest to use as the input file tree.
    #[arg(long)]
    input_digest_length: Option<usize>,

    /// Extra platform properties to set on the execution request during remote execution.
    #[arg(long)]
    extra_platform_property: Vec<String>,

    /// Environment variables with which the process should be run.
    #[arg(long)]
    env: Vec<String>,

    /// Symlink a JDK from .jdk in the working directory.
    /// For local execution, symlinks to the value of this flag.
    /// For remote execution, just requests that some JDK is symlinked if this flag has any value.
    /// <https://github.com/pantsbuild/pants/issues/6416> will make this less weird in the future.
    #[arg(long)]
    jdk: Option<PathBuf>,

    /// Path to file that is considered to be output.
    #[arg(long)]
    output_file_path: Vec<PathBuf>,

    /// Path to directory that is considered to be output.
    #[arg(long)]
    output_directory_path: Vec<PathBuf>,

    /// Path to execute the binary at relative to its input digest root.
    #[arg(long)]
    working_directory: Option<PathBuf>,

    #[arg(long)]
    concurrency_available: Option<usize>,

    /// The number of cores to use for the process in the form of min,max or x (exclusive)
    #[arg(long)]
    concurrency: Option<ProcessConcurrency>,

    #[arg(long)]
    cache_key_gen_version: Option<String>,
}

#[derive(Parser)]
struct ActionDigestSpec {
    /// Fingerprint (hex string) of the digest of the action to run.
    #[arg(long)]
    action_digest: Option<Fingerprint>,

    /// Length of the proto-bytes whose digest is the action to run.
    #[arg(long)]
    action_digest_length: Option<usize>,
}

#[derive(Parser)]
#[command(name = "process_executor")]
struct Opt {
    #[command(flatten)]
    command: CommandSpec,

    #[command(flatten)]
    action_digest: ActionDigestSpec,

    #[command(flatten)]
    store_options: StoreCliOpt,

    #[arg(long)]
    buildbarn_url: Option<String>,

    #[arg(long)]
    run_under: Option<String>,

    /// The name of a directory (which may or may not exist), where the output tree will be materialized.
    #[arg(long)]
    materialize_output_to: Option<PathBuf>,

    /// Path to workdir.
    #[arg(long)]
    work_dir: Option<PathBuf>,

    /// Path to a directory to be used for named caches.
    #[arg(long)]
    named_cache_path: Option<PathBuf>,

    /// The host:port of the gRPC server to connect to. Forces remote execution.
    /// If unspecified, local execution will be performed.
    #[arg(long)]
    server: Option<String>,

    /// Path to file containing root certificate authority certificates for the execution server.
    /// If not set, TLS will not be used when connecting to the execution server.
    #[arg(long)]
    execution_root_ca_cert_file: Option<PathBuf>,

    /// Path to file containing oauth bearer token for communication with the execution server.
    /// If not set, no authorization will be provided to remote servers.
    #[arg(long)]
    execution_oauth_bearer_token_path: Option<PathBuf>,

    /// Number of concurrent requests to the execution service.
    #[arg(long, default_value = "128")]
    execution_rpc_concurrency: usize,

    /// Number of concurrent requests to the cache service.
    #[arg(long, default_value = "128")]
    cache_rpc_concurrency: usize,

    /// Overall timeout in seconds for each request from time of submission.
    #[arg(long, default_value = "600")]
    overall_deadline_secs: u64,
}

/// A binary which takes args of format:
///  process_executor --env=FOO=bar --env=SOME=value --input-digest=abc123 --input-digest-length=80
///    -- /path/to/binary --flag --otherflag
/// and runs /path/to/binary --flag --otherflag with FOO and SOME set.
/// It outputs its output/err to stdout/err, and exits with its exit code.
///
/// It does not perform $PATH lookup or shell expansion.
#[tokio::main]
async fn main() -> Result<(), String> {
    env_logger::init();
    let workunit_store = WorkunitStore::new(false, log::Level::Debug);
    workunit_store.init_thread_state(None);

    let args = Opt::parse();

    let executor = task_executor::Executor::new();

    let store = args.store_options.create_store(executor.clone()).await?;

    if args.server.is_some() && store.is_local_only() {
        return Err("Can't specify --server without --cas-server".to_string());
    }

    let (mut request, process_metadata) = make_request(&store, &args).await?;

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
            let tls_config = grpc_util::tls::Config::new_from_files(
                args.execution_root_ca_cert_file.as_deref(),
                args.store_options.cas_client_certs_file.as_deref(),
                args.store_options.cas_client_key_file.as_deref(),
            )?;
            let headers = args
                .store_options
                .get_headers(&args.execution_oauth_bearer_token_path)?;

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
                            batch_load_enabled: false,
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
            // This process is single-threaded and so doesn't suffer from the issues the sandboxer solves.
            None,
            executor,
            workdir.clone(),
            NamedCaches::new_local(
                args.named_cache_path
                    .unwrap_or_else(NamedCaches::default_local_path),
            ),
            ImmutableInputs::new(store.clone(), &workdir).unwrap(),
            Arc::new(RwLock::new(())),
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
            local_keep_sandboxes: KeepSandboxes::Never,
        }
    } else {
        ProcessExecutionEnvironment {
            name: None,
            platform: Platform::current().unwrap(),
            strategy: ProcessExecutionStrategy::Local,
            local_keep_sandboxes: KeepSandboxes::Never,
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
        args.store_options.remote_instance_name.clone(),
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
        concurrency: args.command.concurrency.clone(),
        cache_scope: ProcessCacheScope::Always,
        execution_environment,
        remote_cache_speculation_delay: Duration::from_millis(0),
        attempt: 0,
    };
    let metadata = ProcessMetadata {
        instance_name: args.store_options.remote_instance_name.clone(),
        cache_key_gen_version: args.command.cache_key_gen_version.clone(),
    };
    Ok((process, metadata))
}

#[allow(clippy::redundant_closure)] // False positives for prost::Message::decode: https://github.com/rust-lang/rust-clippy/issues/5939
#[allow(deprecated)] // TODO: Move to REAPI `output_path` instead of `output_files` and `output_directories`.
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
        concurrency: None,
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

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;

    #[test]
    fn test_process_args() {
        let test_cases = vec![
            (vec![], None),
            (
                vec!["--concurrency=1"],
                Some(ProcessConcurrency::Range {
                    min: Some(1),
                    max: Some(1),
                }),
            ),
            (
                vec!["--concurrency=2,4"],
                Some(ProcessConcurrency::Range {
                    min: Some(2),
                    max: Some(4),
                }),
            ),
            (
                vec!["--concurrency=1,4"],
                Some(ProcessConcurrency::Range {
                    min: Some(1),
                    max: Some(4),
                }),
            ),
            (vec!["--concurrency=x"], Some(ProcessConcurrency::Exclusive)),
        ];

        for (args, expected_concurrency) in test_cases {
            let mut full_args = vec!["process_executor"];
            full_args.extend(args);
            full_args.extend(vec!["--", "/bin/echo", "test"]);

            let opt = Opt::try_parse_from(full_args).unwrap();
            assert_eq!(opt.command.concurrency, expected_concurrency);
        }
    }

    #[test]
    fn test_process_args_errors() {
        let test_cases = vec![
            (
                vec!["--concurrency=0"],
                "error: invalid value '0' for '--concurrency <CONCURRENCY>': Concurrency must be at least 1, got: 0",
            ),
            (
                vec!["--concurrency=4,2"],
                "error: invalid value '4,2' for '--concurrency <CONCURRENCY>': Maximum concurrency must be at least the minimum concurrency, got: 2 and 4",
            ),
            (
                vec!["--concurrency=1,2,3"],
                "error: invalid value '1,2,3' for '--concurrency <CONCURRENCY>': Expected two values for concurrency range, got: 1,2,3",
            ),
            (
                vec!["--concurrency=abc"],
                "error: invalid value 'abc' for '--concurrency <CONCURRENCY>': Invalid concurrency value: invalid digit found in string",
            ),
            (
                vec!["--concurrency=1,abc"],
                "error: invalid value '1,abc' for '--concurrency <CONCURRENCY>': Invalid max value: invalid digit found in string",
            ),
        ];

        for (args, expected_error) in test_cases {
            let mut full_args = vec!["process_executor"];
            full_args.extend(args);
            full_args.extend(vec!["--", "/bin/echo", "test"]);

            let result = Opt::try_parse_from(full_args);
            match result {
                Ok(opt) => {
                    assert!(
                        false,
                        "Expected error '{}' but got '{:?}'",
                        expected_error, opt.command.concurrency
                    );
                }
                Err(e) => {
                    // remove \n\nFor more information, try '--help'.\n if present
                    let original_error = e.to_string();
                    let error_message = original_error
                        .split("\n\nFor more information, try '--help'.\n")
                        .next()
                        .unwrap();
                    assert_eq!(error_message, expected_error);
                }
            }
        }
    }
}
