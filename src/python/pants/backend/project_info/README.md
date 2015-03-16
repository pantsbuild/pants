This backend contains tasks which are not intended to be specific to one
particular language or backend, but cannot go in 'core' because they may
depend on multiple language backends.

Tasks that belong here include:
- IDE Support
- Tasks that have knowledge of external artifacts
- Tasks that have knowledge of binary and app targets

Historically, these sources used to be marked as 'hairball violator' TODOs.
Future refactoring make make it possible for some of this code to be migrated
into the core backend.
