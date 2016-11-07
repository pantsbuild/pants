# Clean Cached Pants Artifacts

## Problem

You want to clean out your Pants build cache, perhaps because you're seeing compilation or other errors that could stem from the presence of stray build artifacts.

## Solution

The `clean-all` goal will delete all cached artifacts (much like `sbt clean` or `mvn clean`):

    ::bash
    $ ./pants clean-all

Once you've done that, retry what you were previously attempting to do and see if it changes things. This may not address your issue, but it's worth trying if you get stuck.
