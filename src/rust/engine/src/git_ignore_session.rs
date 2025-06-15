// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::session::WeakSession;
use crate::{Failure, Session};
use fs::{Dir, Vfs};
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
        let listing = session.core().executor.enter(|| {
            session.workunit_store().init_thread_state(None);
            session.core().executor.block_on(
                session
                    .graph_context()
                    .scandir(Dir(parent_dir.to_path_buf())),
            )
        })?;
        Ok(listing.1.is_path_ignored_or_any_parent(path, is_dir))
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
