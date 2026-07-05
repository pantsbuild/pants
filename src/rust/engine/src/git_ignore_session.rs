// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::nodes::GitignoreStackForDir;
use crate::python::throw;
use crate::session::WeakSession;
use crate::{Failure, Session};
use fs::Dir;
use std::path::Path;
use watch::GitIgnoreProvider;

#[derive(Clone, Debug)]
pub struct GitIgnoreSession {
    session: WeakSession,
}

impl GitIgnoreSession {
    pub fn new(session: &Session) -> Self {
        GitIgnoreSession {
            session: session.downgrade(),
        }
    }

    fn test_path(
        path: &Path,
        is_dir: bool,
        session: Session,
        parent_dir: &Path,
    ) -> Result<bool, Failure> {
        let stack_node =
            GitignoreStackForDir::for_dir(Dir(parent_dir.to_path_buf())).map_err(throw)?;
        let gitignore_stack = session.core().executor.enter(|| {
            session.workunit_store().init_thread_state(None);
            session
                .core()
                .executor
                .block_on(session.graph_context().get(stack_node))
        })?;
        Ok(gitignore_stack.is_path_ignored_or_any_parent(path, is_dir))
    }
}

impl GitIgnoreProvider for GitIgnoreSession {
    fn is_ignored_or_child_of_ignored_path(&self, path: &Path, is_dir: bool) -> bool {
        // Always invalidate when .gitignore file changed
        if path.file_name() == Some(".gitignore".as_ref()) {
            return false;
        }
        if let Some(session) = self.session.upgrade() {
            return if let Some(parent_dir) = path.parent() {
                Self::test_path(path, is_dir, session, parent_dir).unwrap_or_else(|err| {
                    log::error!("Error testing {}: {}", path.display(), err);
                    false
                })
            } else {
                log::trace!("Path is root directory, not ignoring");
                false
            };
        };
        log::info!("Session has been freed, not testing path.");
        false
    }
}
