// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::cmp::max;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::convert::Into;
use std::io::Read;
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use crate::intrinsics::Intrinsics;
use crate::nodes::{ExecuteProcess, NodeKey, NodeOutput, NodeResult};
use crate::python::{throw, Failure};
use crate::session::{Session, Sessions};
use crate::tasks::{Rule, Tasks};
use crate::types::Types;

use cache::PersistentCache;
use fs::{GitignoreStyleExcludes, PosixFS};
use futures::FutureExt;
use graph::{Graph, InvalidationResult};
use hashing::Digest;
use log::{log, Level};
use parking_lot::Mutex;
// use docker::docker::{self, DOCKER, IMAGE_PULL_CACHE};
use docker::docker;
use process_execution::switched::SwitchedCommandRunner;
use process_execution::{
    self, bounded, local, CacheContentBehavior, CommandRunner, NamedCaches,
    ProcessExecutionStrategy,
};
use regex::Regex;
use remote::remote_cache::{RemoteCacheRunnerOptions, RemoteCacheWarningsBehavior};
use remote::{self, remote_cache};
use rule_graph::RuleGraph;
use store::{self, ImmutableInputs, RemoteProvider, RemoteStoreOptions, Store};
use task_executor::Executor;
use tokio::sync::RwLock;
use watch::{Invalidatable, InvalidateCaller, InvalidationWatcher};
use workunit_store::{Metric, RunningWorkunit};

// The reqwest crate has no support for ingesting multiple certificates in a single file,
// and requires single PEM blocks. There is a crate (https://crates.io/crates/pem) that can decode
// multiple certificates from a single buffer, but it is not suitable for our use because we don't
// want to decode the certificates, but rather pass them as source to reqwest. That crate also
// inappropriately squelches errors.
//
// Instead we make our own use of a copy of the regex used by the pem crate.  Note:
//   - The leading (?s) which sets the flag to allow . to match \n.
//   - The use of ungreedy repetition via .*?, so we get shortest instead of longest matches.
const PEM_RE_STR: &str =
    r"(?s)-----BEGIN (?P<begin>.*?)-----\s*(?P<data>.*?)-----END (?P<end>.*?)-----\s*";

///
/// The core context shared (via Arc) between the Scheduler and the Context objects of
/// all running Nodes.
///
pub struct Core {
    pub graph: Arc<InvalidatableGraph>,
    pub tasks: Tasks,
    pub rule_graph: RuleGraph<Rule>,
    pub types: Types,
    pub intrinsics: Intrinsics,
    pub executor: Executor,
    store: Store,
    /// The CommandRunners to use for execution, in ascending order of reliability (for the purposes
    /// of backtracking). For performance reasons, caching `CommandRunners` might skip validation of
    /// their outputs, and so should be listed before uncached `CommandRunners`.
    pub command_runners: Vec<Arc<dyn CommandRunner>>,
    pub http_client: reqwest::Client,
    pub local_cache: PersistentCache,
    pub vfs: PosixFS,
    pub watcher: Option<Arc<InvalidationWatcher>>,
    pub build_root: PathBuf,
    pub local_parallelism: usize,
    pub graceful_shutdown_timeout: Duration,
    pub sessions: Sessions,
    pub named_caches: NamedCaches,
    pub immutable_inputs: ImmutableInputs,
    pub local_execution_root_dir: PathBuf,
}

#[derive(Clone, Debug)]
pub struct RemotingOptions {
    pub provider: RemoteProvider,
    pub execution_enable: bool,
    pub store_address: Option<String>,
    pub execution_address: Option<String>,
    pub execution_process_cache_namespace: Option<String>,
    pub instance_name: Option<String>,
    pub root_ca_certs_path: Option<PathBuf>,
    pub client_certs_path: Option<PathBuf>,
    pub client_key_path: Option<PathBuf>,
    pub store_headers: BTreeMap<String, String>,
    pub store_chunk_bytes: usize,
    pub store_rpc_retries: usize,
    pub store_rpc_concurrency: usize,
    pub store_rpc_timeout: Duration,
    pub store_batch_api_size_limit: usize,
    pub cache_warnings_behavior: RemoteCacheWarningsBehavior,
    pub cache_content_behavior: CacheContentBehavior,
    pub cache_rpc_concurrency: usize,
    pub cache_rpc_timeout: Duration,
    pub execution_headers: BTreeMap<String, String>,
    pub execution_overall_deadline: Duration,
    pub execution_rpc_concurrency: usize,
    pub append_only_caches_base_path: Option<String>,
}

impl RemotingOptions {
    fn to_remote_store_options(
        &self,
        tls_config: grpc_util::tls::Config,
    ) -> Result<RemoteStoreOptions, String> {
        let store_address = self
            .store_address
            .as_ref()
            .ok_or("Remote store required, but none configured")?
            .clone();

        Ok(RemoteStoreOptions {
            provider: self.provider,
            store_address,
            instance_name: self.instance_name.clone(),
            tls_config,
            headers: self.store_headers.clone(),
            chunk_size_bytes: self.store_chunk_bytes,
            timeout: self.store_rpc_timeout,
            retries: self.store_rpc_retries,
            concurrency_limit: self.store_rpc_concurrency,
            batch_api_size_limit: self.store_batch_api_size_limit,
        })
    }
}

#[derive(Clone, Debug)]
pub struct ExecutionStrategyOptions {
    pub local_parallelism: usize,
    pub remote_parallelism: usize,
    pub local_keep_sandboxes: local::KeepSandboxes,
    pub local_cache: bool,
    pub local_enable_nailgun: bool,
    pub remote_cache_read: bool,
    pub remote_cache_write: bool,
    pub child_max_memory: usize,
    pub child_default_memory: usize,
    pub graceful_shutdown_timeout: Duration,
}

#[derive(Clone, Debug)]
pub struct LocalStoreOptions {
    pub store_dir: PathBuf,
    pub process_cache_max_size_bytes: usize,
    pub files_max_size_bytes: usize,
    pub directories_max_size_bytes: usize,
    pub lease_time: Duration,
    pub shard_count: u8,
}

impl From<&LocalStoreOptions> for store::LocalOptions {
    fn from(lso: &LocalStoreOptions) -> Self {
        Self {
            files_max_size_bytes: lso.files_max_size_bytes,
            directories_max_size_bytes: lso.directories_max_size_bytes,
            lease_time: lso.lease_time,
            shard_count: lso.shard_count,
        }
    }
}

impl Core {
    async fn make_store(
        executor: &Executor,
        local_store_options: &LocalStoreOptions,
        local_execution_root_dir: &Path,
        enable_remote: bool,
        remoting_opts: &RemotingOptions,
        tls_config: grpc_util::tls::Config,
    ) -> Result<Store, String> {
        let local_only = Store::local_only_with_options(
            executor.clone(),
            local_store_options.store_dir.clone(),
            local_execution_root_dir,
            local_store_options.into(),
        )?;
        if enable_remote {
            local_only
                .into_with_remote(remoting_opts.to_remote_store_options(tls_config)?)
                .await
        } else {
            Ok(local_only)
        }
    }

    ///
    /// Make the innermost / leaf runner. Will have concurrency control and process pooling, but
    /// will not have caching.
    ///
    async fn make_leaf_runner(
        full_store: &Store,
        local_runner_store: &Store,
        executor: &Executor,
        local_execution_root_dir: &Path,
        immutable_inputs: &ImmutableInputs,
        named_caches: &NamedCaches,
        instance_name: Option<String>,
        process_cache_namespace: Option<String>,
        tls_config: grpc_util::tls::Config,
        exec_strategy_opts: &ExecutionStrategyOptions,
        remoting_opts: &RemotingOptions,
    ) -> Result<Arc<dyn CommandRunner>, String> {
        // Lock shared between local command runner (and in future work) other "local" command runners
        // for spawning processes.
        let spawn_lock = Arc::new(RwLock::new(()));

        let local_command_runner = local::CommandRunner::new(
            local_runner_store.clone(),
            executor.clone(),
            local_execution_root_dir.to_path_buf(),
            named_caches.clone(),
            immutable_inputs.clone(),
            exec_strategy_opts.local_keep_sandboxes,
            spawn_lock.clone(),
        );

        let runner: Box<dyn CommandRunner> = if exec_strategy_opts.local_enable_nailgun {
            // We set the nailgun pool size to the number of instances that fit within the memory
            // parameters configured when a max child process memory has been given.
            // Otherwise, pool size will be double of the local parallelism so we can always keep
            // a jvm warmed up.
            let pool_size: usize = if exec_strategy_opts.child_max_memory > 0 {
                max(
                    1,
                    exec_strategy_opts.child_max_memory / exec_strategy_opts.child_default_memory,
                )
            } else {
                exec_strategy_opts.local_parallelism * 2
            };

            let nailgun_runner = pe_nailgun::CommandRunner::new(
                local_execution_root_dir.to_path_buf(),
                local_runner_store.clone(),
                executor.clone(),
                named_caches.clone(),
                immutable_inputs.clone(),
                pool_size,
            );

            Box::new(SwitchedCommandRunner::new(
                nailgun_runner,
                local_command_runner,
                |req| !req.input_digests.use_nailgun.is_empty(),
            ))
        } else {
            Box::new(local_command_runner)
        };

        // Note that the Docker command runner is only used if the Process sets docker_image. So,
        // it's safe to always create this command runner.
        let docker_runner = Box::new(docker::CommandRunner::new(
            local_runner_store.clone(),
            executor.clone(),
            &docker::DOCKER,
            &docker::IMAGE_PULL_CACHE,
            local_execution_root_dir.to_path_buf(),
            immutable_inputs.clone(),
            exec_strategy_opts.local_keep_sandboxes,
        )?);
        let runner = Box::new(SwitchedCommandRunner::new(docker_runner, runner, |req| {
            matches!(
                req.execution_environment.strategy,
                ProcessExecutionStrategy::Docker(_)
            )
        }));

        let mut runner: Box<dyn CommandRunner> = Box::new(bounded::CommandRunner::new(
            executor,
            runner,
            exec_strategy_opts.local_parallelism,
        ));

        if remoting_opts.execution_enable {
            // We always create the remote execution runner if it is globally enabled, but it may not
            // actually be used thanks to the `SwitchedCommandRunner` below. Only one of local execution
            // or remote execution will be used for any particular process.
            let remote_execution_runner = Box::new(
                remote::remote::CommandRunner::new(
                    // We unwrap because global_options.py will have already validated this is defined.
                    remoting_opts.execution_address.as_ref().unwrap(),
                    instance_name,
                    process_cache_namespace,
                    remoting_opts.append_only_caches_base_path.clone(),
                    tls_config.clone(),
                    remoting_opts.execution_headers.clone(),
                    full_store.clone(),
                    executor.clone(),
                    remoting_opts.execution_overall_deadline,
                    Duration::from_millis(100),
                    remoting_opts.execution_rpc_concurrency,
                )
                .await?,
            );
            let remote_execution_runner = Box::new(bounded::CommandRunner::new(
                executor,
                remote_execution_runner,
                exec_strategy_opts.remote_parallelism,
            ));
            runner = Box::new(SwitchedCommandRunner::new(
                remote_execution_runner,
                runner,
                |req| {
                    matches!(
                        req.execution_environment.strategy,
                        ProcessExecutionStrategy::RemoteExecution(_)
                    )
                },
            ));
        }

        Ok(Arc::new(runner))
    }

    ///
    /// Creates a single stack of cached runners around the given "leaf" CommandRunner.
    ///
    /// The given cache read/write flags override the relevant cache flags to allow this method
    /// to be called with all cache reads disabled, regardless of their configured values.
    ///
    async fn make_cached_runner(
        mut runner: Arc<dyn CommandRunner>,
        full_store: &Store,
        executor: &Executor,
        local_cache: &PersistentCache,
        instance_name: Option<String>,
        process_cache_namespace: Option<String>,
        tls_config: grpc_util::tls::Config,
        remoting_opts: &RemotingOptions,
        remote_cache_read: bool,
        remote_cache_write: bool,
        local_cache_read: bool,
        local_cache_write: bool,
    ) -> Result<Arc<dyn CommandRunner>, String> {
        if remote_cache_read || remote_cache_write {
            runner = Arc::new(
                remote_cache::CommandRunner::from_provider_options(
                    RemoteCacheRunnerOptions {
                        inner: runner,
                        instance_name: instance_name.clone(),
                        process_cache_namespace: process_cache_namespace.clone(),
                        executor: executor.clone(),
                        store: full_store.clone(),
                        cache_read: remote_cache_read,
                        cache_write: remote_cache_write,
                        warnings_behavior: remoting_opts.cache_warnings_behavior,
                        cache_content_behavior: remoting_opts.cache_content_behavior,
                        append_only_caches_base_path: remoting_opts
                            .append_only_caches_base_path
                            .clone(),
                    },
                    remoting_opts.to_remote_store_options(tls_config)?,
                )
                .await?,
            );
        }

        if local_cache_read || local_cache_write {
            runner = Arc::new(process_execution::cache::CommandRunner::new(
                runner,
                local_cache.clone(),
                full_store.clone(),
                local_cache_read,
                remoting_opts.cache_content_behavior,
                process_cache_namespace,
            ));
        }

        Ok(runner)
    }

    ///
    /// Creates the stack of CommandRunners for the purposes of backtracking.
    ///
    async fn make_command_runners(
        full_store: &Store,
        local_runner_store: &Store,
        executor: &Executor,
        local_cache: &PersistentCache,
        local_execution_root_dir: &Path,
        immutable_inputs: &ImmutableInputs,
        named_caches: &NamedCaches,
        instance_name: Option<String>,
        process_cache_namespace: Option<String>,
        tls_config: grpc_util::tls::Config,
        exec_strategy_opts: &ExecutionStrategyOptions,
        remoting_opts: &RemotingOptions,
    ) -> Result<Vec<Arc<dyn CommandRunner>>, String> {
        let leaf_runner = Self::make_leaf_runner(
            full_store,
            local_runner_store,
            executor,
            local_execution_root_dir,
            immutable_inputs,
            named_caches,
            instance_name.clone(),
            process_cache_namespace.clone(),
            tls_config.clone(),
            exec_strategy_opts,
            remoting_opts,
        )
        .await?;

        let remote_cache_read = exec_strategy_opts.remote_cache_read;
        let remote_cache_write = exec_strategy_opts.remote_cache_write;
        let local_cache_read_write = exec_strategy_opts.local_cache;

        // The first attempt is always with all caches.
        let mut runners = {
            let cached_runner = Self::make_cached_runner(
                leaf_runner.clone(),
                full_store,
                executor,
                local_cache,
                instance_name.clone(),
                process_cache_namespace.clone(),
                tls_config.clone(),
                remoting_opts,
                remote_cache_read,
                remote_cache_write,
                local_cache_read_write,
                local_cache_read_write,
            )
            .await?;

            vec![cached_runner]
        };
        // If any cache is both readable and writable, we additionally add a backtracking attempt which
        // disables all cache reads.
        if (remote_cache_read && remote_cache_write) || local_cache_read_write {
            let disabled_cached_runner = Self::make_cached_runner(
                leaf_runner.clone(),
                full_store,
                executor,
                local_cache,
                instance_name.clone(),
                process_cache_namespace.clone(),
                tls_config,
                remoting_opts,
                false,
                remote_cache_write,
                false,
                local_cache_read_write,
            )
            .await?;

            runners.push(disabled_cached_runner);
        }

        Ok(runners)
    }

    fn load_certificates(
        ca_certs_path: Option<PathBuf>,
    ) -> Result<Vec<reqwest::Certificate>, String> {
        let certs = match ca_certs_path {
            Some(ref path) => {
                let mut content = String::new();
                std::fs::File::open(path)
                    .and_then(|mut f| f.read_to_string(&mut content))
                    .map_err(|err| {
                        format!(
                            "Error reading root CA certs file {}: {}",
                            path.display(),
                            err
                        )
                    })?;
                let pem_re = Regex::new(PEM_RE_STR).unwrap();
                let certs_res: Result<Vec<reqwest::Certificate>, _> = pem_re
                    .find_iter(&content)
                    .map(|mat| reqwest::Certificate::from_pem(mat.as_str().as_bytes()))
                    .collect();
                certs_res.map_err(|err| {
                    format!(
                        "Error parsing PEM from root CA certs file {}: {}",
                        path.display(),
                        err
                    )
                })?
            }
            None => Vec::new(),
        };
        Ok(certs)
    }

    pub async fn new(
        executor: Executor,
        tasks: Tasks,
        types: Types,
        intrinsics: Intrinsics,
        build_root: PathBuf,
        ignore_patterns: Vec<String>,
        use_gitignore: bool,
        watch_filesystem: bool,
        local_execution_root_dir: PathBuf,
        named_caches_dir: PathBuf,
        ca_certs_path: Option<PathBuf>,
        local_store_options: LocalStoreOptions,
        remoting_opts: RemotingOptions,
        exec_strategy_opts: ExecutionStrategyOptions,
    ) -> Result<Core, String> {
        // We re-use these certs for both the execution and store service; they're generally tied together.
        let root_ca_certs = if let Some(ref path) = remoting_opts.root_ca_certs_path {
            Some(
                std::fs::read(path)
                    .map_err(|err| format!("Error reading root CA certs file {path:?}: {err}"))?,
            )
        } else {
            None
        };

        let client_certs = remoting_opts
            .client_certs_path
            .as_ref()
            .map(|path| {
                std::fs::read(path).map_err(|err| {
                    format!("Error reading client authentication certs file {path:?}: {err}")
                })
            })
            .transpose()?;

        let client_key = remoting_opts
            .client_key_path
            .as_ref()
            .map(|path| {
                std::fs::read(path).map_err(|err| {
                    format!("Error reading client authentication key file {path:?}: {err}")
                })
            })
            .transpose()?;

        let mtls_data = match (client_certs.as_ref(), client_key.as_ref()) {
      (Some(cert), Some(key)) => Some((cert.deref(), key.deref())),
      (None, None) => None,
      _ => {
        return Err(
			"Both remote_client_certs_path and remote_client_key_path must be specified to enable client authentication, but only one was provided."
            .to_owned(),
        )
      }
    };

        let tls_config = grpc_util::tls::Config::new(root_ca_certs.as_deref(), mtls_data)?;

        let need_remote_store = remoting_opts.execution_enable
            || exec_strategy_opts.remote_cache_read
            || exec_strategy_opts.remote_cache_write;

        std::fs::create_dir_all(&local_store_options.store_dir).map_err(|e| {
            format!(
                "Error making directory {:?}: {:?}",
                local_store_options.store_dir, e
            )
        })?;

        let full_store = Self::make_store(
            &executor,
            &local_store_options,
            &local_execution_root_dir,
            need_remote_store,
            &remoting_opts,
            tls_config.clone(),
        )
        .await
        .map_err(|e| format!("Could not initialize Store: {e:?}"))?;

        let local_cache = PersistentCache::new(
            &local_store_options.store_dir,
            // TODO: Rename.
            local_store_options.process_cache_max_size_bytes,
            executor.clone(),
            local_store_options.lease_time,
            local_store_options.shard_count,
        )?;

        let store = if (exec_strategy_opts.remote_cache_read
            || exec_strategy_opts.remote_cache_write)
            && remoting_opts.cache_content_behavior == CacheContentBehavior::Fetch
            && !remoting_opts.execution_enable
        {
            // In remote cache mode with eager fetching, the only interaction with the remote CAS
            // should be through the remote cache code paths. Thus, the store seen by the rest of the
            // code base should be the local-only store.
            full_store.clone().into_local_only()
        } else {
            // Otherwise, the remote CAS should be visible everywhere.
            //
            // With remote execution, we do not always write remote results into the local cache, so it's
            // important to always have access to the remote cache or else we will get missing digests.
            full_store.clone()
        };

        let immutable_inputs = ImmutableInputs::new(store.clone(), &local_execution_root_dir)?;
        let named_caches = NamedCaches::new_local(named_caches_dir);
        let command_runners = Self::make_command_runners(
            &full_store,
            &store,
            &executor,
            &local_cache,
            &local_execution_root_dir,
            &immutable_inputs,
            &named_caches,
            remoting_opts.instance_name.clone(),
            remoting_opts.execution_process_cache_namespace.clone(),
            tls_config.clone(),
            &exec_strategy_opts,
            &remoting_opts,
        )
        .await?;
        log::debug!("Using {command_runners:?} for process execution.");

        let graph = Arc::new(InvalidatableGraph(Graph::new(executor.clone())));

        // These certs are for downloads, not to be confused with the ones used for remoting.
        let ca_certs = Self::load_certificates(ca_certs_path)?;

        let http_client_builder = ca_certs
            .iter()
            .fold(reqwest::Client::builder(), |builder, cert| {
                builder.add_root_certificate(cert.clone())
            });
        let http_client = http_client_builder
            .build()
            .map_err(|err| format!("Error building HTTP client: {err}"))?;
        let rule_graph = RuleGraph::new(tasks.rules().clone(), tasks.queries().clone())?;

        let gitignore_files = if use_gitignore {
            GitignoreStyleExcludes::gitignore_file_paths(&build_root)
        } else {
            vec![]
        };

        let ignorer =
            GitignoreStyleExcludes::create_with_gitignore_files(ignore_patterns, gitignore_files)
                .map_err(|e| format!("Could not parse build ignore patterns: {e:?}"))?;

        let watcher = if watch_filesystem {
            let w =
                InvalidationWatcher::new(executor.clone(), build_root.clone(), ignorer.clone())?;
            w.start(&graph)?;
            Some(w)
        } else {
            None
        };

        let sessions = Sessions::new(&executor)?;

        Ok(Core {
            graph,
            tasks,
            rule_graph,
            types,
            intrinsics,
            executor: executor.clone(),
            store,
            command_runners,
            http_client,
            local_cache,
            vfs: PosixFS::new(&build_root, ignorer, executor)
                .map_err(|e| format!("Could not initialize Vfs: {e:?}"))?,
            build_root,
            watcher,
            local_parallelism: exec_strategy_opts.local_parallelism,
            graceful_shutdown_timeout: exec_strategy_opts.graceful_shutdown_timeout,
            sessions,
            named_caches,
            immutable_inputs,
            local_execution_root_dir,
        })
    }

    pub fn store(&self) -> Store {
        self.store.clone()
    }

    ///
    /// Shuts down this Core.
    ///
    pub async fn shutdown(&self, timeout: Duration) {
        // Shutdown the Sessions, which will prevent new work from starting and then await any ongoing
        // work.
        if let Err(msg) = self.sessions.shutdown(timeout).await {
            log::warn!("During shutdown: {}", msg);
        }
        // Then clear the Graph to ensure that drop handlers run (particularly for running processes).
        self.graph.clear();

        // Allow command runners to cleanly shutdown in an async context to avoid issues with
        // waiting for async code to run in a non-async drop context.
        let shutdown_futures = self
            .command_runners
            .iter()
            .map(|runner| runner.shutdown().boxed());
        let shutdown_results = futures::future::join_all(shutdown_futures).await;
        for shutdown_result in shutdown_results {
            if let Err(err) = shutdown_result {
                log::warn!("Command runner failed to shutdown cleanly: {err}");
            }
        }
    }
}

pub struct InvalidatableGraph(Graph<NodeKey>);

fn caller_to_logging_info(caller: InvalidateCaller) -> (Level, &'static str) {
    match caller {
        // An external invalidation is driven by some other pants operation, and thus isn't as
        // interesting, there's likely to be output about that action already, hence this can be logged
        // quieter.
        InvalidateCaller::External => (Level::Debug, "external"),
        // A notify invalidation may have been triggered by a user-driven action that isn't otherwise
        // visible in logs (e.g. file editing, branch switching), hence log it louder.
        InvalidateCaller::Notify => (Level::Info, "notify"),
    }
}

impl Invalidatable for InvalidatableGraph {
    fn invalidate(&self, paths: &HashSet<PathBuf>, caller: InvalidateCaller) -> usize {
        let InvalidationResult { cleared, dirtied } =
            self.invalidate_from_roots(false, move |node| {
                if let Some(fs_subject) = node.fs_subject() {
                    paths.contains(fs_subject)
                } else {
                    false
                }
            });
        let (level, caller) = caller_to_logging_info(caller);
        log!(
            level,
            "{} invalidation: cleared {} and dirtied {} nodes for: {:?}",
            caller,
            cleared,
            dirtied,
            paths
        );
        cleared + dirtied
    }

    fn invalidate_all(&self, caller: InvalidateCaller) -> usize {
        let InvalidationResult { cleared, dirtied } =
            self.invalidate_from_roots(false, |node| node.fs_subject().is_some());
        let (level, caller) = caller_to_logging_info(caller);
        log!(
            level,
            "{} invalidation: cleared {} and dirtied {} nodes for all paths",
            caller,
            cleared,
            dirtied
        );
        cleared + dirtied
    }
}

impl Deref for InvalidatableGraph {
    type Target = Graph<NodeKey>;

    fn deref(&self) -> &Graph<NodeKey> {
        &self.0
    }
}

pub type Context = graph::Context<NodeKey>;

pub struct SessionCore {
    // TODO: This field is also accessible via the Session: move to an accessor.
    pub core: Arc<Core>,
    pub session: Session,
    /// The number of attempts which have been made to backtrack to a particular ExecuteProcess node.
    ///
    /// Presence in this map at process runtime indicates that the process is being retried, and that
    /// there was something invalid or unusable about previous attempts. Successive attempts should
    /// run in a different mode (skipping caches, etc) to attempt to produce a valid result.
    backtrack_levels: Arc<Mutex<HashMap<ExecuteProcess, usize>>>,
    /// The Digests that we have successfully invalidated a Node for.
    backtrack_digests: Arc<Mutex<HashSet<Digest>>>,
}

impl SessionCore {
    pub fn new(session: Session) -> Self {
        Self {
            core: session.core().clone(),
            session,
            backtrack_levels: Arc::default(),
            backtrack_digests: Arc::default(),
        }
    }

    ///
    /// If the given Result is a Failure::MissingDigest, attempts to invalidate the Node which was
    /// the source of the Digest, potentially causing indirect retry of the Result.
    ///
    /// If we successfully locate and restart the source of the Digest, converts the Result into a
    /// `Failure::Invalidated`, which will cause retry at some level above us.
    ///
    /// TODO: This takes both `self` and `context: Context`, but could take `self: Context` after
    /// the `arbitrary_self_types` feature has stabilized.
    ///
    pub fn maybe_backtrack(
        &self,
        context: &Context,
        result: NodeResult<NodeOutput>,
        workunit: &mut RunningWorkunit,
    ) -> NodeResult<NodeOutput> {
        let digest = if let Err(Failure::MissingDigest(_, d)) = result.as_ref() {
            *d
        } else {
            return result;
        };

        // Locate live source(s) of this Digest and their backtracking levels.
        // TODO: Currently needs a combination of `visit_live` and `invalidate_from_roots` because
        // `invalidate_from_roots` cannot view `Node` results. Would be more efficient as a merged
        // method.
        let mut candidate_roots = Vec::new();
        self.core.graph.visit_live(context, |k, v| match k {
            NodeKey::ExecuteProcess(p) if v.digests().contains(&digest) => {
                if let NodeOutput::ProcessResult(pr) = v {
                    candidate_roots.push((p.clone(), pr.backtrack_level));
                }
            }
            _ => (),
        });

        if candidate_roots.is_empty() {
            // If there are no live sources of the Digest, see whether any have already been invalidated
            // by other consumers.
            if self.backtrack_digests.lock().get(&digest).is_some() {
                // Some other consumer has already identified and invalidated the source of this Digest: we
                // can wait for the attempt to complete.
                return Err(Failure::Invalidated);
            } else {
                // There are no live or invalidated sources of this Digest. Directly fail.
                return result.map_err(|e| {
                    throw(format!(
                        "Could not identify a process to backtrack to for: {e}"
                    ))
                });
            }
        } else {
            // We have identified a Node to backtrack on. Record it.
            self.backtrack_digests.lock().insert(digest);
        }

        // Attempt to trigger backtrack attempts for the matched Nodes. It's possible that we are not
        // the first consumer to notice that this Node needs to backtrack, so we only actually report
        // that we're backtracking if the new level is an increase from the old level.
        let roots = candidate_roots
            .into_iter()
            .filter_map(|(root, invalid_level)| {
                let next_level = invalid_level + 1;
                let maybe_new_level = {
                    let mut backtrack_levels = self.backtrack_levels.lock();
                    if let Some(old_backtrack_level) = backtrack_levels.get_mut(&root) {
                        if next_level > *old_backtrack_level {
                            *old_backtrack_level = next_level;
                            Some(next_level)
                        } else {
                            None
                        }
                    } else {
                        backtrack_levels.insert((*root).clone(), next_level);
                        Some(next_level)
                    }
                };
                if let Some(new_level) = maybe_new_level {
                    workunit.increment_counter(Metric::BacktrackAttempts, 1);
                    let description = &root.process.description;
                    // TODO: This message should likely be at `info`, or eventually, debug.
                    //   see https://github.com/pantsbuild/pants/issues/15867
                    log::warn!(
            "Making attempt {new_level} to backtrack and retry `{description}`, due to \
              missing digest {digest:?}."
          );
                    Some(root)
                } else {
                    None
                }
            })
            .collect::<HashSet<_>>();

        // Invalidate the matched roots.
        self.core
            .graph
            .invalidate_from_roots(true, move |node| match node {
                NodeKey::ExecuteProcess(p) => roots.contains(p),
                _ => false,
            });

        // We invalidated a Node, and the caller (at some level above us in the stack) should retry.
        // Complete this node with the Invalidated state.
        // TODO: Differentiate the reasons for Invalidation (filesystem changes vs missing digests) to
        // improve warning messages. See https://github.com/pantsbuild/pants/issues/15867
        Err(Failure::Invalidated)
    }

    ///
    /// Called before executing a process to determine whether it is backtracking.
    ///
    /// A process which has not been marked backtracking will always return 0.
    ///
    pub fn maybe_start_backtracking(&self, node: &ExecuteProcess) -> usize {
        self.backtrack_levels.lock().get(node).cloned().unwrap_or(0)
    }
}
