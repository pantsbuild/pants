/src/python/pants/backend/

Pants functionality can be extended via backends. 

There are v1 backends, that provide task definitions and v2 backends that provide rule definitions.

This directory contains code for the official v1 and v2 backends supported by the core pants team. 

A backend is defined by a `register.py` file containing v1 and v2 registration entrypoints.

Note that a single package can provide both a v1 and a v2 backend, depending on the entrypoints
it defines.
