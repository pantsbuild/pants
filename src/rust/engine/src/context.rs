// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use tokio::runtime::Runtime;

use futures::Future;

use boxfuture::{BoxFuture, Boxable};
use core::{Failure, TypeId};
use fs::{safe_create_dir_all_ioerror, PosixFS, ResettablePool, Store};
use graph::{EntryId, Graph, NodeContext};
use handles::maybe_drop_handles;
use log::debug;
use nodes::{NodeKey, TryInto, WrappedNode};
use process_execution::{self, BoundedCommandRunner, CommandRunner};
use resettable::Resettable;
use rule_graph::RuleGraph;
use tasks::Tasks;
use types::Types;

///
/// The core context shared (via Arc) between the Scheduler and the Context objects of
/// all running Nodes.
///
/// Over time, most usage of `ResettablePool` (which wraps use of blocking APIs) should migrate
/// to the Tokio `Runtime`. The next candidate is likely to be migrating PosixFS to tokio-fs once
/// https://github.com/tokio-rs/tokio/issues/369 is resolved.
///
pub struct Core {
  pub graph: Graph<NodeKey>,
  pub tasks: Tasks,
  pub rule_graph: RuleGraph,
  pub types: Types,
  pub fs_pool: Arc<ResettablePool>,
  pub runtime: Resettable<Arc<Runtime>>,
  store_and_command_runner: Resettable<(Store, BoundedCommandRunner)>,
  pub vfs: PosixFS,
}

impl Core {
  #[cfg_attr(feature = "cargo-clippy", allow(too_many_arguments))]
  pub fn new(
    root_subject_types: Vec<TypeId>,
    tasks: Tasks,
    types: Types,
    build_root: &Path,
    ignore_patterns: &[String],
    work_dir: PathBuf,
    local_store_dir: PathBuf,
    remote_store_server: Option<String>,
    remote_execution_server: Option<String>,
    remote_instance_name: Option<String>,
    remote_root_ca_certs_path: Option<PathBuf>,
    remote_oauth_bearer_token_path: Option<PathBuf>,
    remote_store_thread_count: usize,
    remote_store_chunk_bytes: usize,
    remote_store_chunk_upload_timeout: Duration,
    process_execution_parallelism: usize,
    process_execution_cleanup_local_dirs: bool,
  ) -> Core {
    let fs_pool = Arc::new(ResettablePool::new("io-".to_string()));
    let runtime = Resettable::new(|| {
      Arc::new(Runtime::new().unwrap_or_else(|e| panic!("Could not initialize Runtime: {:?}", e)))
    });
    // We re-use these certs for both the execution and store service; they're generally tied together.
    let root_ca_certs = if let Some(path) = remote_root_ca_certs_path {
      Some(
        std::fs::read(&path)
          .unwrap_or_else(|err| panic!("Error reading root CA certs file {:?}: {}", path, err)),
      )
    } else {
      None
    };

    // We re-use this token for both the execution and store service; they're generally tied together.
    let oauth_bearer_token = if let Some(path) = remote_oauth_bearer_token_path {
      Some(
        std::fs::read_to_string(&path)
          .unwrap_or_else(|err| panic!("Error reading root CA certs file {:?}: {}", path, err)),
      )
    } else {
      None
    };

    let fs_pool2 = fs_pool.clone();
    let store_and_command_runner = Resettable::new(move || {
      let local_store_dir = local_store_dir.clone();
      let store = safe_create_dir_all_ioerror(&local_store_dir)
        .map_err(|e| format!("Error making directory {:?}: {:?}", local_store_dir, e))
        .and_then(|()| match &remote_store_server {
          Some(ref address) => Store::with_remote(
            local_store_dir,
            fs_pool2.clone(),
            address,
            remote_instance_name.clone(),
            root_ca_certs.clone(),
            oauth_bearer_token.clone(),
            remote_store_thread_count,
            remote_store_chunk_bytes,
            remote_store_chunk_upload_timeout,
          ),
          None => Store::local_only(local_store_dir, fs_pool2.clone()),
        }).unwrap_or_else(|e| panic!("Could not initialize Store: {:?}", e));

      let underlying_command_runner: Box<CommandRunner> = match &remote_execution_server {
        Some(ref address) => Box::new(process_execution::remote::CommandRunner::new(
          address,
          remote_instance_name.clone(),
          root_ca_certs.clone(),
          oauth_bearer_token.clone(),
          // Allow for some overhead for bookkeeping threads (if any).
          process_execution_parallelism + 2,
          store.clone(),
        )),
        None => Box::new(process_execution::local::CommandRunner::new(
          store.clone(),
          fs_pool2.clone(),
          work_dir.clone(),
          process_execution_cleanup_local_dirs,
        )),
      };

      let command_runner =
        BoundedCommandRunner::new(underlying_command_runner, process_execution_parallelism);

      (store, command_runner)
    });

    let rule_graph = RuleGraph::new(&tasks, root_subject_types);

    Core {
      graph: Graph::new(),
      tasks: tasks,
      rule_graph: rule_graph,
      types: types,
      fs_pool: fs_pool.clone(),
      runtime: runtime,
      store_and_command_runner: store_and_command_runner,
      // TODO: Errors in initialization should definitely be exposed as python
      // exceptions, rather than as panics.
      vfs: PosixFS::new(build_root, fs_pool, &ignore_patterns).unwrap_or_else(|e| {
        panic!("Could not initialize VFS: {:?}", e);
      }),
    }
  }

  pub fn fork_context<F, T>(&self, f: F) -> T
  where
    F: Fn() -> T,
  {
    // Only one fork may occur at a time, but draining the Runtime and Graph requires that the
    // Graph lock is not actually held during draining (as that would not allow the Runtime's
    // threads to observe the draining value). So we attempt to mark the Graph draining (similar
    // to a CAS loop), and treat a successful attempt as indication that our thread has permission
    // to execute the fork.
    //
    // An alternative would be to have two locks in the Graph: one outer lock for the draining
    // bool, and one inner lock for Graph mutations. But forks should be rare enough that busy
    // waiting is not too contentious.
    while let Err(()) = self.graph.mark_draining(true) {
      debug!("Waiting to enter fork_context...");
      thread::sleep(Duration::from_millis(10));
    }
    let t = self.runtime.with_reset(|| {
      self.graph.with_exclusive(|| {
        self
          .fs_pool
          .with_shutdown(|| self.store_and_command_runner.with_reset(f))
      })
    });
    self
      .graph
      .mark_draining(false)
      .expect("Multiple callers should not be in the fork context at once.");
    t
  }

  pub fn store(&self) -> Store {
    self.store_and_command_runner.get().0
  }

  pub fn command_runner(&self) -> BoundedCommandRunner {
    self.store_and_command_runner.get().1
  }
}

#[derive(Clone)]
pub struct Context {
  pub entry_id: EntryId,
  pub core: Arc<Core>,
}

impl Context {
  pub fn new(entry_id: EntryId, core: Arc<Core>) -> Context {
    Context {
      entry_id: entry_id,
      core: core,
    }
  }

  ///
  /// Get the future value for the given Node implementation.
  ///
  pub fn get<N: WrappedNode>(&self, node: N) -> BoxFuture<N::Item, Failure> {
    // TODO: Odd place for this... could do it periodically in the background?
    maybe_drop_handles();
    self
      .core
      .graph
      .get(self.entry_id, self, node.into())
      .map(|node_result| {
        node_result
          .try_into()
          .unwrap_or_else(|_| panic!("A Node implementation was ambiguous."))
      }).to_boxed()
  }
}

impl NodeContext for Context {
  type Node = NodeKey;

  ///
  /// Clones this Context for a new EntryId. Because the Core of the context is an Arc, this
  /// is a shallow clone.
  ///
  fn clone_for(&self, entry_id: EntryId) -> Context {
    Context {
      entry_id: entry_id,
      core: self.core.clone(),
    }
  }

  fn graph(&self) -> &Graph<NodeKey> {
    &self.core.graph
  }

  fn spawn<F>(&self, future: F)
  where
    F: Future<Item = (), Error = ()> + Send + 'static,
  {
    self.core.runtime.get().executor().spawn(future);
  }
}
