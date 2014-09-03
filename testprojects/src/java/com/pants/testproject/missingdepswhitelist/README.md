The JVM dependency analyzer will tell users if a target a is using classes it does not correctly depend on.

However, in some cases (such as catching up on fixing these dependency issues) it is useful to have a
whitelist of targets to not report or fail builds on.

This project will generate a missing dep warning, but it is whitelisted so in the end it will not.