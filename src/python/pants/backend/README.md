/src/python/pants/backend/

Some Pants functionality can live in "plugins", as described at,
http://www.pantsbuild.org/howto_plugin.html . This code defines plugins normally built into
Pants itself. Most of the Pants code lives here.

NOTE: These are "v1" plugins, that register v1 tasks. See src/python/pants/backend2/ for
v2 plugins, that register v2 rules.
