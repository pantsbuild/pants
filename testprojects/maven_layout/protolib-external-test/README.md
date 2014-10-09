This directory contains a maven project that is used to publish an
artifact containing .proto sources to the Sonatype Central Repository
https://oss.sonatype.org/

This artifact is meant to be referenced as a test of the external_artifact()
target feature.

Release to the central repository with:
mvn clean deploy
