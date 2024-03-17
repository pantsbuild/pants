// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use futures::future::{BoxFuture, FutureExt};
use indexmap::IndexMap;
use rule_graph::{DependencyKey, RuleId};

use crate::context::Context;
use crate::nodes::{NodeResult, RunId, SessionValues};
use crate::python::Value;
use crate::tasks::Intrinsic;
use crate::types::Types;

// Sub-modules with intrinsic implementations.
mod dep_inference;
mod digests;
mod docker;
mod interactive_process;
mod process;

use self::dep_inference::{parse_javascript_deps, parse_python_deps};
use self::digests::{
    add_prefix_request_to_digest, create_digest_to_digest, digest_subset_to_digest,
    digest_to_snapshot, directory_digest_to_digest_contents, directory_digest_to_digest_entries,
    download_file_to_digest, merge_digests_request_to_digest, path_globs_to_digest,
    path_globs_to_paths, remove_prefix_request_to_digest,
};
use self::docker::docker_resolve_image;
use self::interactive_process::interactive_process;
use self::process::process_request_to_process_result;

type IntrinsicFn =
    Box<dyn Fn(Context, Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> + Send + Sync>;

pub struct Intrinsics {
    intrinsics: IndexMap<Intrinsic, IntrinsicFn>,
}

impl Intrinsics {
    pub fn new(types: &Types) -> Intrinsics {
        let mut intrinsics: IndexMap<Intrinsic, IntrinsicFn> = IndexMap::new();
        intrinsics.insert(
            Intrinsic::new(
                "create_digest_to_digest",
                types.directory_digest,
                types.create_digest,
            ),
            Box::new(create_digest_to_digest),
        );
        intrinsics.insert(
            Intrinsic::new(
                "path_globs_to_digest",
                types.directory_digest,
                types.path_globs,
            ),
            Box::new(path_globs_to_digest),
        );
        intrinsics.insert(
            Intrinsic::new("path_globs_to_paths", types.paths, types.path_globs),
            Box::new(path_globs_to_paths),
        );
        intrinsics.insert(
            Intrinsic::new(
                "download_file_to_digest",
                types.directory_digest,
                types.native_download_file,
            ),
            Box::new(download_file_to_digest),
        );
        intrinsics.insert(
            Intrinsic::new("digest_to_snapshot", types.snapshot, types.directory_digest),
            Box::new(digest_to_snapshot),
        );
        intrinsics.insert(
            Intrinsic::new(
                "directory_digest_to_digest_contents",
                types.digest_contents,
                types.directory_digest,
            ),
            Box::new(directory_digest_to_digest_contents),
        );
        intrinsics.insert(
            Intrinsic::new(
                "directory_digest_to_digest_entries",
                types.digest_entries,
                types.directory_digest,
            ),
            Box::new(directory_digest_to_digest_entries),
        );
        intrinsics.insert(
            Intrinsic::new(
                "merge_digests_request_to_digest",
                types.directory_digest,
                types.merge_digests,
            ),
            Box::new(merge_digests_request_to_digest),
        );
        intrinsics.insert(
            Intrinsic::new(
                "remove_prefix_request_to_digest",
                types.directory_digest,
                types.remove_prefix,
            ),
            Box::new(remove_prefix_request_to_digest),
        );
        intrinsics.insert(
            Intrinsic::new(
                "add_prefix_request_to_digest",
                types.directory_digest,
                types.add_prefix,
            ),
            Box::new(add_prefix_request_to_digest),
        );
        intrinsics.insert(
            Intrinsic {
                id: RuleId::new("process_request_to_process_result"),
                product: types.process_result,
                inputs: vec![
                    DependencyKey::new(types.process),
                    DependencyKey::new(types.process_config_from_environment),
                ],
            },
            Box::new(process_request_to_process_result),
        );
        intrinsics.insert(
            Intrinsic::new(
                "digest_subset_to_digest",
                types.directory_digest,
                types.digest_subset,
            ),
            Box::new(digest_subset_to_digest),
        );
        intrinsics.insert(
            Intrinsic {
                id: RuleId::new("session_values"),
                product: types.session_values,
                inputs: vec![],
            },
            Box::new(session_values),
        );
        intrinsics.insert(
            Intrinsic {
                id: RuleId::new("run_id"),
                product: types.run_id,
                inputs: vec![],
            },
            Box::new(run_id),
        );
        intrinsics.insert(
            Intrinsic {
                id: RuleId::new("interactive_process"),
                product: types.interactive_process_result,
                inputs: vec![
                    DependencyKey::new(types.interactive_process),
                    DependencyKey::new(types.process_config_from_environment),
                ],
            },
            Box::new(interactive_process),
        );
        intrinsics.insert(
            Intrinsic {
                id: RuleId::new("docker_resolve_image"),
                product: types.docker_resolve_image_result,
                inputs: vec![DependencyKey::new(types.docker_resolve_image_request)],
            },
            Box::new(docker_resolve_image),
        );
        intrinsics.insert(
            Intrinsic {
                id: RuleId::new("parse_python_deps"),
                product: types.parsed_python_deps_result,
                inputs: vec![DependencyKey::new(types.deps_request)],
            },
            Box::new(parse_python_deps),
        );
        intrinsics.insert(
            Intrinsic {
                id: RuleId::new("parse_javascript_deps"),
                product: types.parsed_javascript_deps_result,
                inputs: vec![DependencyKey::new(types.deps_request)],
            },
            Box::new(parse_javascript_deps),
        );
        Intrinsics { intrinsics }
    }

    pub fn keys(&self) -> impl Iterator<Item = &Intrinsic> {
        self.intrinsics.keys()
    }

    pub async fn run(
        &self,
        intrinsic: &Intrinsic,
        context: Context,
        args: Vec<Value>,
    ) -> NodeResult<Value> {
        let function = self
            .intrinsics
            .get(intrinsic)
            .unwrap_or_else(|| panic!("Unrecognized intrinsic: {intrinsic:?}"));
        function(context, args).await
    }
}

fn session_values(context: Context, _args: Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> {
    async move { context.get(SessionValues).await }.boxed()
}

fn run_id(context: Context, _args: Vec<Value>) -> BoxFuture<'static, NodeResult<Value>> {
    async move { context.get(RunId).await }.boxed()
}
