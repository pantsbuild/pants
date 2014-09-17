Push db changes
===============

Previously when publishing a single file would record the version information.
For example: build-support/ivy/pushdb/publish.properties

This file would update each time an artifact is published and then merged. However,
in larger repositories this often became a pain point since multiple users might be
updating the file at the same time.

So in this version the publish db file has been split into one per artifact.
For example: build-support/ivy/pushdb/com.twitter/finagle-core/publish.properties

In order to migrate between the old format and the new please run
migrations/0.0.24/src/python/publish_migration.py filename

You also need to change any BUILD files that specify repo config to not use
push_db pointing to a file, but instead push_db_basedir pointing to a dir.