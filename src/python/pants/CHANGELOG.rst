RELEASE HISTORY
===============

0.0.27 (12/19/2014)
-------------------

Bugfixes
~~~~~~~~

* Fix python doc: "repl" and "setup-py" are goals now, don't use "py"
  `RB #1302 <https://rbcommons.com/s/twitter/r/1302>`_

* Fix python thrift generation
  `RB #1517 <https://rbcommons.com/s/twitter/r/1517>`_

* Fixup migrate_config to use new Config API
  `RB #1514 <https://rbcommons.com/s/twitter/r/1514>`_

0.0.26 (12/17/2014)
-------------------

Bugfixes
~~~~~~~~

* Fix the `ScroogeGen` target selection predicate
  `RB #1497 <https://rbcommons.com/s/twitter/r/1497>`_

0.0.25 (12/17/2014)
-------------------

API Changes
~~~~~~~~~~~

* Flesh out and convert to the new options system introduced in `pantsbuild.pants` 0.0.24

  - Support loading config from multiple files
  - Support option reads via indexing
  - Add a `migrate_config` tool
  - Migrate tasks to the option registration system
  - Get rid of the old config registration mechanism
  - Add passthru arg support in the new options system
  - Support passthru args in tasks
  - Allow a task type know its own options scope
  - Support old-style flags even in the new flag system

  `RB #1093 <https://rbcommons.com/s/twitter/r/1093>`_
  `RB #1094 <https://rbcommons.com/s/twitter/r/1094>`_
  `RB #1095 <https://rbcommons.com/s/twitter/r/1095>`_
  `RB #1096 <https://rbcommons.com/s/twitter/r/1096>`_
  `RB #1097 <https://rbcommons.com/s/twitter/r/1097>`_
  `RB #1102 <https://rbcommons.com/s/twitter/r/1102>`_
  `RB #1109 <https://rbcommons.com/s/twitter/r/1109>`_
  `RB #1114 <https://rbcommons.com/s/twitter/r/1114>`_
  `RB #1124 <https://rbcommons.com/s/twitter/r/1124>`_
  `RB #1125 <https://rbcommons.com/s/twitter/r/1125>`_
  `RB #1127 <https://rbcommons.com/s/twitter/r/1127>`_
  `RB #1129 <https://rbcommons.com/s/twitter/r/1129>`_
  `RB #1131 <https://rbcommons.com/s/twitter/r/1131>`_
  `RB #1135 <https://rbcommons.com/s/twitter/r/1135>`_
  `RB #1138 <https://rbcommons.com/s/twitter/r/1138>`_
  `RB #1140 <https://rbcommons.com/s/twitter/r/1140>`_
  `RB #1146 <https://rbcommons.com/s/twitter/r/1146>`_
  `RB #1147 <https://rbcommons.com/s/twitter/r/1147>`_
  `RB #1170 <https://rbcommons.com/s/twitter/r/1170>`_
  `RB #1175 <https://rbcommons.com/s/twitter/r/1175>`_
  `RB #1183 <https://rbcommons.com/s/twitter/r/1183>`_
  `RB #1186 <https://rbcommons.com/s/twitter/r/1186>`_
  `RB #1192 <https://rbcommons.com/s/twitter/r/1192>`_
  `RB #1195 <https://rbcommons.com/s/twitter/r/1195>`_
  `RB #1203 <https://rbcommons.com/s/twitter/r/1203>`_
  `RB #1211 <https://rbcommons.com/s/twitter/r/1211>`_
  `RB #1212 <https://rbcommons.com/s/twitter/r/1212>`_
  `RB #1214 <https://rbcommons.com/s/twitter/r/1214>`_
  `RB #1218 <https://rbcommons.com/s/twitter/r/1218>`_
  `RB #1223 <https://rbcommons.com/s/twitter/r/1223>`_
  `RB #1225 <https://rbcommons.com/s/twitter/r/1225>`_
  `RB #1229 <https://rbcommons.com/s/twitter/r/1229>`_
  `RB #1230 <https://rbcommons.com/s/twitter/r/1230>`_
  `RB #1231 <https://rbcommons.com/s/twitter/r/1231>`_
  `RB #1232 <https://rbcommons.com/s/twitter/r/1232>`_
  `RB #1234 <https://rbcommons.com/s/twitter/r/1234>`_
  `RB #1236 <https://rbcommons.com/s/twitter/r/1236>`_
  `RB #1244 <https://rbcommons.com/s/twitter/r/1244>`_
  `RB #1248 <https://rbcommons.com/s/twitter/r/1248>`_
  `RB #1251 <https://rbcommons.com/s/twitter/r/1251>`_
  `RB #1258 <https://rbcommons.com/s/twitter/r/1258>`_
  `RB #1269 <https://rbcommons.com/s/twitter/r/1269>`_
  `RB #1270 <https://rbcommons.com/s/twitter/r/1270>`_
  `RB #1276 <https://rbcommons.com/s/twitter/r/1276>`_
  `RB #1281 <https://rbcommons.com/s/twitter/r/1281>`_
  `RB #1286 <https://rbcommons.com/s/twitter/r/1286>`_
  `RB #1289 <https://rbcommons.com/s/twitter/r/1289>`_
  `RB #1297 <https://rbcommons.com/s/twitter/r/1297>`_
  `RB #1300 <https://rbcommons.com/s/twitter/r/1300>`_
  `RB #1308 <https://rbcommons.com/s/twitter/r/1308>`_
  `RB #1309 <https://rbcommons.com/s/twitter/r/1309>`_
  `RB #1317 <https://rbcommons.com/s/twitter/r/1317>`_
  `RB #1320 <https://rbcommons.com/s/twitter/r/1320>`_
  `RB #1323 <https://rbcommons.com/s/twitter/r/1323>`_
  `RB #1328 <https://rbcommons.com/s/twitter/r/1328>`_
  `RB #1341 <https://rbcommons.com/s/twitter/r/1341>`_
  `RB #1343 <https://rbcommons.com/s/twitter/r/1343>`_
  `RB #1351 <https://rbcommons.com/s/twitter/r/1351>`_
  `RB #1357 <https://rbcommons.com/s/twitter/r/1357>`_
  `RB #1373 <https://rbcommons.com/s/twitter/r/1373>`_
  `RB #1375 <https://rbcommons.com/s/twitter/r/1375>`_
  `RB #1385 <https://rbcommons.com/s/twitter/r/1385>`_
  `RB #1389 <https://rbcommons.com/s/twitter/r/1389>`_
  `RB #1399 <https://rbcommons.com/s/twitter/r/1399>`_
  `RB #1409 <https://rbcommons.com/s/twitter/r/1409>`_
  `RB #1435 <https://rbcommons.com/s/twitter/r/1435>`_
  `RB #1441 <https://rbcommons.com/s/twitter/r/1441>`_
  `RB #1442 <https://rbcommons.com/s/twitter/r/1442>`_
  `RB #1443 <https://rbcommons.com/s/twitter/r/1443>`_
  `RB #1451 <https://rbcommons.com/s/twitter/r/1451>`_

* Kill `Commands` and move all actions to `Tasks` in the goal infrastructure

  - Kill pants own use of the deprecated goal command
  - Restore the deprecation warning for specifying 'goal' on the cmdline
  - Get rid of the Command class completely
  - Enable passthru args for python run

  `RB #1321 <https://rbcommons.com/s/twitter/r/1321>`_
  `RB #1327 <https://rbcommons.com/s/twitter/r/1327>`_
  `RB #1394 <https://rbcommons.com/s/twitter/r/1394>`_
  `RB #1402 <https://rbcommons.com/s/twitter/r/1402>`_
  `RB #1448 <https://rbcommons.com/s/twitter/r/1448>`_
  `RB #1453 <https://rbcommons.com/s/twitter/r/1453>`_
  `RB #1465 <https://rbcommons.com/s/twitter/r/1465>`_
  `RB #1471 <https://rbcommons.com/s/twitter/r/1471>`_
  `RB #1476 <https://rbcommons.com/s/twitter/r/1476>`_
  `RB #1479 <https://rbcommons.com/s/twitter/r/1479>`_

* Add support for loading plugins via standard the pkg_resources entry points mechanism
  `RB #1429 <https://rbcommons.com/s/twitter/r/1429>`_
  `RB #1444 <https://rbcommons.com/s/twitter/r/1444>`_

* Many performance improvements and bugfixes to the artifact caching subsystem

  - Use a requests `Session` to enable connection pooling
  - Make CacheKey hash and pickle friendly
  - Multiprocessing Cache Check and Write
  - Skip compressing/writing artifacts that are already in the cache
  - Add the ability for JVM targets to refuse to allow themselves to be cached in the artifact cache
  - Fix name of non-fatal cache exception
  - Fix the issue of seeing "Error while writing to artifact cache: an integer is required"
    during [cache check]
  - Fix all uncompressed artifacts stored as just `.tar`

  `RB #981 <https://rbcommons.com/s/twitter/r/981>`_
  `RB #986 <https://rbcommons.com/s/twitter/r/986>`_
  `RB #1022 <https://rbcommons.com/s/twitter/r/1022>`_
  `RB #1197 <https://rbcommons.com/s/twitter/r/1197>`_
  `RB #1206 <https://rbcommons.com/s/twitter/r/1206>`_
  `RB #1233 <https://rbcommons.com/s/twitter/r/1233>`_
  `RB #1261 <https://rbcommons.com/s/twitter/r/1261>`_
  `RB #1264 <https://rbcommons.com/s/twitter/r/1264>`_
  `RB #1265 <https://rbcommons.com/s/twitter/r/1265>`_
  `RB #1272 <https://rbcommons.com/s/twitter/r/1272>`_
  `RB #1274 <https://rbcommons.com/s/twitter/r/1274>`_
  `RB #1249 <https://rbcommons.com/s/twitter/r/1249>`_
  `RB #1310 <https://rbcommons.com/s/twitter/r/1310>`_

* More enhancements to the `depmap` goal to support IDE plugins:

  - Add Pants Target Type to `depmap` to identify scala target VS java target
  - Add java_sources to the `depmap` info
  - Add transitive jar dependencies to `depmap` project info goal for intellij plugin

  `RB #1366 <https://rbcommons.com/s/twitter/r/1366>`_
  `RB #1324 <https://rbcommons.com/s/twitter/r/1324>`_
  `RB #1047 <https://rbcommons.com/s/twitter/r/1047>`_

* Port pants to pex 0.8.x
  `Issue #10 <https://github.com/pantsbuild/pex/issues/10>`_
  `Issue #19 <https://github.com/pantsbuild/pex/issues/19>`_
  `Issue #21 <https://github.com/pantsbuild/pex/issues/21>`_
  `Issue #22 <https://github.com/pantsbuild/pex/issues/22>`_
  `RB #778 <https://rbcommons.com/s/twitter/r/778>`_
  `RB #785 <https://rbcommons.com/s/twitter/r/785>`_
  `RB #1303 <https://rbcommons.com/s/twitter/r/1303>`_
  `RB #1378 <https://rbcommons.com/s/twitter/r/1378>`_
  `RB #1421 <https://rbcommons.com/s/twitter/r/1421>`_

* Remove support for __file__ in BUILDs
  `RB #1419 <https://rbcommons.com/s/twitter/r/1419>`_

* Allow setting the cwd for goals `run.jvm` and `test.junit`
  `RB #1344 <https://rbcommons.com/s/twitter/r/1344>`_

* Subclasses of `Exception` have strange deserialization
  `RB #1395 <https://rbcommons.com/s/twitter/r/1395>`_

* Remove outer (pants_exe) lock and serialized cmd
  `RB #1388 <https://rbcommons.com/s/twitter/r/1388>`_

* Make all access to `Context`'s lock via helpers
  `RB #1391 <https://rbcommons.com/s/twitter/r/1391>`_

* Allow adding entries to `source_roots`
  `RB #1359 <https://rbcommons.com/s/twitter/r/1359>`_

* Re-upload artifacts that encountered read-errors
  `RB #1361 <https://rbcommons.com/s/twitter/r/1361>`_

* Cache files created by (specially designed) annotation processors
  `RB #1250 <https://rbcommons.com/s/twitter/r/1250>`_

* Turn dependency dupes into errors
  `RB #1332 <https://rbcommons.com/s/twitter/r/1332>`_

* Add support for the Wire protobuf library
  `RB #1275 <https://rbcommons.com/s/twitter/r/1275>`_

* Pin pants support down to python2.7 - dropping 2.6
  `RB #1278 <https://rbcommons.com/s/twitter/r/1278>`_

* Add a new param for page target, links, a list of hyperlinked-to targets
  `RB #1242 <https://rbcommons.com/s/twitter/r/1242>`_

* Add git root calculation for idea goal
  `RB #1189 <https://rbcommons.com/s/twitter/r/1189>`_

* Minimal target "tags" support
  `RB #1227 <https://rbcommons.com/s/twitter/r/1227>`_

* Include traceback with failures (even without fail-fast)
  `RB #1226 <https://rbcommons.com/s/twitter/r/1226>`_

* Add support for updating the environment from prep_commands
  `RB #1222 <https://rbcommons.com/s/twitter/r/1222>`_

* Read arguments for thrift-linter from `pants.ini`
  `RB #1215 <https://rbcommons.com/s/twitter/r/1215>`_

* Configurable Compression Level for Cache Artifacts
  `RB #1194 <https://rbcommons.com/s/twitter/r/1194>`_

* Add a flexible directory re-mapper for the bundle
  `RB #1181 <https://rbcommons.com/s/twitter/r/1181>`_

* Adds the ability to pass a filter method for ZIP extraction
  `RB #1199 <https://rbcommons.com/s/twitter/r/1199>`_

* Print a diagnostic if a BUILD file references a source file that does not exist
  `RB #1198 <https://rbcommons.com/s/twitter/r/1198>`_

* Add support for running a command before tests
  `RB #1179 <https://rbcommons.com/s/twitter/r/1179>`_
  `RB #1177 <https://rbcommons.com/s/twitter/r/1177>`_

* Add `PantsRunIntegrationTest` into `pantsbuild.pants.testinfra` package
  `RB #1185 <https://rbcommons.com/s/twitter/r/1185>`_

* Refactor `jar_library` to be able to unwrap its list of jar_dependency objects
  `RB #1165 <https://rbcommons.com/s/twitter/r/1165>`_

* When resolving a tool dep, report back the `pants.ini` section with a reference that is failing
  `RB #1162 <https://rbcommons.com/s/twitter/r/1162>`_

* Add a list assertion for `python_requirement_library`'s requirements
  `RB #1142 <https://rbcommons.com/s/twitter/r/1142>`_

* Adding a list of dirs to exclude from the '::' scan in the `CmdLineSpecParser`
  `RB #1091 <https://rbcommons.com/s/twitter/r/1091>`_

* Protobuf and payload cleanups
  `RB #1099 <https://rbcommons.com/s/twitter/r/1099>`_

* Coalesce errors when parsing BUILDS in a spec
  `RB #1061 <https://rbcommons.com/s/twitter/r/1061>`_

* Refactor Payload
  `RB #1063 <https://rbcommons.com/s/twitter/r/1063>`_

* Add support for publishing plugins to pants.
  `RB #1021 <https://rbcommons.com/s/twitter/r/1021>`_

Bugfixes
~~~~~~~~

* Numerous doc improvements & generation fixes

  - Updates to the pants essentials tech talk based on another dry-run
  - On skinny displays, don't show navigation UI by default
  - Handy rbt status tip from RBCommons newsletter
  - Document how to create a simple plugin
  - Update many bash examples that used old-style flags
  - Update Pants+IntelliJ docs to say the Plugin's the new hotness, link to plugin's README
  - Publish docs the new way
  - Update the "Pants Essentials" tech talk slides
  - Convert `.rst` files -> `.md` files
  - For included code snippets, don't just slap in a pre, provide syntax highlighting
  - Add notes about JDK versions supported
  - Dust off the Task Developer's Guide and `rm` the "pagerank" example
  - Add a `sitegen` task, create site with better navigation
  - For 'goal builddict', generate `.rst` and `.html`, not just `.rst`
  - Narrow setup 'Operating System' classfiers to known-good

  `Issue #16 <https://github.com/pantsbuild/pex/issues/16>`_
  `Issue #461 <https://github.com/pantsbuild/pants/issues/461>`_
  `Issue #739 <https://github.com/pantsbuild/pants/issues/739>`_
  `RB #891 <https://rbcommons.com/s/twitter/r/891>`_
  `RB #1074 <https://rbcommons.com/s/twitter/r/1074>`_
  `RB #1075 <https://rbcommons.com/s/twitter/r/1075>`_
  `RB #1079 <https://rbcommons.com/s/twitter/r/1079>`_
  `RB #1084 <https://rbcommons.com/s/twitter/r/1084>`_
  `RB #1086 <https://rbcommons.com/s/twitter/r/1086>`_
  `RB #1088 <https://rbcommons.com/s/twitter/r/1088>`_
  `RB #1090 <https://rbcommons.com/s/twitter/r/1090>`_
  `RB #1101 <https://rbcommons.com/s/twitter/r/1101>`_
  `RB #1126 <https://rbcommons.com/s/twitter/r/1126>`_
  `RB #1128 <https://rbcommons.com/s/twitter/r/1128>`_
  `RB #1134 <https://rbcommons.com/s/twitter/r/1134>`_
  `RB #1136 <https://rbcommons.com/s/twitter/r/1136>`_
  `RB #1154 <https://rbcommons.com/s/twitter/r/1154>`_
  `RB #1155 <https://rbcommons.com/s/twitter/r/1155>`_
  `RB #1164 <https://rbcommons.com/s/twitter/r/1164>`_
  `RB #1166 <https://rbcommons.com/s/twitter/r/1166>`_
  `RB #1176 <https://rbcommons.com/s/twitter/r/1176>`_
  `RB #1178 <https://rbcommons.com/s/twitter/r/1178>`_
  `RB #1182 <https://rbcommons.com/s/twitter/r/1182>`_
  `RB #1191 <https://rbcommons.com/s/twitter/r/1191>`_
  `RB #1196 <https://rbcommons.com/s/twitter/r/1196>`_
  `RB #1205 <https://rbcommons.com/s/twitter/r/1205>`_
  `RB #1241 <https://rbcommons.com/s/twitter/r/1241>`_
  `RB #1263 <https://rbcommons.com/s/twitter/r/1263>`_
  `RB #1277 <https://rbcommons.com/s/twitter/r/1277>`_
  `RB #1284 <https://rbcommons.com/s/twitter/r/1284>`_
  `RB #1292 <https://rbcommons.com/s/twitter/r/1292>`_
  `RB #1295 <https://rbcommons.com/s/twitter/r/1295>`_
  `RB #1296 <https://rbcommons.com/s/twitter/r/1296>`_
  `RB #1298 <https://rbcommons.com/s/twitter/r/1298>`_
  `RB #1299 <https://rbcommons.com/s/twitter/r/1299>`_
  `RB #1301 <https://rbcommons.com/s/twitter/r/1301>`_
  `RB #1314 <https://rbcommons.com/s/twitter/r/1314>`_
  `RB #1315 <https://rbcommons.com/s/twitter/r/1315>`_
  `RB #1326 <https://rbcommons.com/s/twitter/r/1326>`_
  `RB #1348 <https://rbcommons.com/s/twitter/r/1348>`_
  `RB #1355 <https://rbcommons.com/s/twitter/r/1355>`_
  `RB #1356 <https://rbcommons.com/s/twitter/r/1356>`_
  `RB #1358 <https://rbcommons.com/s/twitter/r/1358>`_
  `RB #1363 <https://rbcommons.com/s/twitter/r/1363>`_
  `RB #1370 <https://rbcommons.com/s/twitter/r/1370>`_
  `RB #1377 <https://rbcommons.com/s/twitter/r/1377>`_
  `RB #1386 <https://rbcommons.com/s/twitter/r/1386>`_
  `RB #1387 <https://rbcommons.com/s/twitter/r/1387>`_
  `RB #1401 <https://rbcommons.com/s/twitter/r/1401>`_
  `RB #1407 <https://rbcommons.com/s/twitter/r/1407>`_
  `RB #1427 <https://rbcommons.com/s/twitter/r/1427>`_
  `RB #1430 <https://rbcommons.com/s/twitter/r/1430>`_
  `RB #1434 <https://rbcommons.com/s/twitter/r/1434>`_
  `RB #1440 <https://rbcommons.com/s/twitter/r/1440>`_
  `RB #1446 <https://rbcommons.com/s/twitter/r/1446>`_
  `RB #1464 <https://rbcommons.com/s/twitter/r/1464>`_
  `RB #1484 <https://rbcommons.com/s/twitter/r/1484>`_
  `RB #1491 <https://rbcommons.com/s/twitter/r/1491>`_

* CmdLineProcessor uses `binary class name
  <http://docs.oracle.com/javase/specs/jvms/se7/html/jvms-4.html#jvms-4.2.1>`_
  `RB #1489 <https://rbcommons.com/s/twitter/r/1489>`_

* Use subscripting for looking up targets in resources_by_products
  `RB #1380 <https://rbcommons.com/s/twitter/r/1380>`_

* Fix/refactor checkstyle
  `RB #1432 <https://rbcommons.com/s/twitter/r/1432>`_

* Fix missing import
  `RB #1483 <https://rbcommons.com/s/twitter/r/1483>`_

* Make `./pants help` and `./pants help <goal>` work properly
  `Issue #839 <https://github.com/pantsbuild/pants/issues/839>`_
  `RB #1482 <https://rbcommons.com/s/twitter/r/1482>`_

* Cleanup after custom options bootstrapping in reflect
  `RB #1468 <https://rbcommons.com/s/twitter/r/1468>`_

* Handle UTF-8 in thrift files for python
  `RB #1459 <https://rbcommons.com/s/twitter/r/1459>`_

* Optimize goal changed
  `RB #1470 <https://rbcommons.com/s/twitter/r/1470>`_

* Fix a bug where a request for help wasn't detected
  `RB #1467 <https://rbcommons.com/s/twitter/r/1467>`_

* Always relativize the classpath where possible
  `RB #1455 <https://rbcommons.com/s/twitter/r/1455>`_

* Gracefully handle another run creating latest link
  `RB #1396 <https://rbcommons.com/s/twitter/r/1396>`_

* Properly detect existence of a symlink
  `RB #1437 <https://rbcommons.com/s/twitter/r/1437>`_

* Avoid throwing in `ApacheThriftGen.__init__`
  `RB #1428 <https://rbcommons.com/s/twitter/r/1428>`_

* Fix error message in scrooge_gen
  `RB #1426 <https://rbcommons.com/s/twitter/r/1426>`_

* Fixup `BuildGraph` to handle mixes of synthetic and BUILD targets
  `RB #1420 <https://rbcommons.com/s/twitter/r/1420>`_

* Fix antlr package derivation
  `RB #1410 <https://rbcommons.com/s/twitter/r/1410>`_

* Exit workers on sigint rather than ignore
  `RB #1405 <https://rbcommons.com/s/twitter/r/1405>`_

* Fix error in string formatting
  `RB #1416 <https://rbcommons.com/s/twitter/r/1416>`_

* Add missing class
  `RB #1414 <https://rbcommons.com/s/twitter/r/1414>`_

* Add missing import for dedent in `resource_mapping.py`
  `RB #1403 <https://rbcommons.com/s/twitter/r/1403>`_

* Replace twitter commons dirutil Lock with lockfile wrapper
  `RB #1390 <https://rbcommons.com/s/twitter/r/1390>`_

* Make `interpreter_cache` a property, acquire lock in accessor
  `Issue #819 <https://github.com/pantsbuild/pants/issues/819>`_
  `RB #1392 <https://rbcommons.com/s/twitter/r/1392>`_

* Fix `.proto` files with unicode characters in the comments
  `RB #1330 <https://rbcommons.com/s/twitter/r/1330>`_

* Make `pants goal run` for Python exit with error code 1 if the python program exits non-zero
  `RB #1374 <https://rbcommons.com/s/twitter/r/1374>`_

* Fix a bug related to adding sibling resource bases
  `RB #1367 <https://rbcommons.com/s/twitter/r/1367>`_

* Support for the `--kill-nailguns` option was inadvertently removed, this puts it back
  `RB #1352 <https://rbcommons.com/s/twitter/r/1352>`_

* fix string formatting so `test -h` does not crash
  `RB #1353 <https://rbcommons.com/s/twitter/r/1353>`_

* Fix java_sources missing dep detection
  `RB #1336 <https://rbcommons.com/s/twitter/r/1336>`_

* Fix a nasty bug when injecting target closures in BuildGraph
  `RB #1337 <https://rbcommons.com/s/twitter/r/1337>`_

* Switch `src/*` usages of `Config.load` to use `Config.from_cache` instead
  `RB #1319 <https://rbcommons.com/s/twitter/r/1319>`_

* Optimize `what_changed`, remove un-needed extra sort
  `RB #1291 <https://rbcommons.com/s/twitter/r/1291>`_

* Fix `DetectDuplicate`'s handling of an `append`-type flag
  `RB #1282 <https://rbcommons.com/s/twitter/r/1282>`_

* Deeper selection of internal targets during publishing
  `RB #1213 <https://rbcommons.com/s/twitter/r/1213>`_

* Correctly parse named_is_latest entries from the pushdb
  `RB #1245 <https://rbcommons.com/s/twitter/r/1245>`_

* Fix error message: add missing space
  `RB #1266 <https://rbcommons.com/s/twitter/r/1266>`_

* WikiArtifact instances also have provides; limit ivy to jvm
  `RB #1259 <https://rbcommons.com/s/twitter/r/1259>`_

* Fix `[run.junit]` -> `[test.junit]`
  `RB #1256 <https://rbcommons.com/s/twitter/r/1256>`_

* Fix signature in `goal targets` and BUILD dictionary
  `RB #1253 <https://rbcommons.com/s/twitter/r/1253>`_

* Fix the regression introduced in https://rbcommons.com/s/twitter/r/1186
  `RB #1254 <https://rbcommons.com/s/twitter/r/1254>`_

* Temporarily change `stderr` log level to silence `log.init` if `--quiet`
  `RB #1243 <https://rbcommons.com/s/twitter/r/1243>`_

* Add the environment's `PYTHONPATH` to `sys.path` when running dev pants
  `RB #1237 <https://rbcommons.com/s/twitter/r/1237>`_

* Remove `java_sources` as target roots for scala library in `depmap` project info
  `Issue #670 <https://github.com/pantsbuild/pants/issues/670>`_
  `RB #1190 <https://rbcommons.com/s/twitter/r/1190>`_

* Allow UTF-8 characters in changelog
  `RB #1228 <https://rbcommons.com/s/twitter/r/1228>`_

* Ensure proper semantics when replacing all tasks in a goal
  `RB #1220 <https://rbcommons.com/s/twitter/r/1220>`_
  `RB #1221 <https://rbcommons.com/s/twitter/r/1221>`_

* Fix reading of `scalac` plugin info from config
  `RB #1217 <https://rbcommons.com/s/twitter/r/1217>`_

* Dogfood bintray for pants support binaries
  `RB #1208 <https://rbcommons.com/s/twitter/r/1208>`_

* Do not crash on unicode filenames
  `RB #1193 <https://rbcommons.com/s/twitter/r/1193>`_
  `RB #1209 <https://rbcommons.com/s/twitter/r/1209>`_

* In the event of an exception in `jvmdoc_gen`, call `get()` on the remaining futures
  `RB #1202 <https://rbcommons.com/s/twitter/r/1202>`_

* Move `workdirs` creation from `__init__` to `pre_execute` in jvm_compile & Remove
  `QuietTaskMixin` from several tasks
  `RB #1173 <https://rbcommons.com/s/twitter/r/1173>`_

* Switch from `os.rename` to `shutil.move` to support cross-fs renames when needed
  `RB #1157 <https://rbcommons.com/s/twitter/r/1157>`_

* Fix scalastyle task, wire it up, make configs optional
  `RB #1145 <https://rbcommons.com/s/twitter/r/1145>`_

* Fix issue 668: make `release.sh` execute packaged pants without loading internal backends
  during testing
  `Issue #668 <https://github.com/pantsbuild/pants/issues/668>`_
  `RB #1158 <https://rbcommons.com/s/twitter/r/1158>`_

* Add `payload.get_field_value()` to fix KeyError from `pants goal idea testprojects::`
  `RB #1150 <https://rbcommons.com/s/twitter/r/1150>`_

* Remove `debug_args` from `pants.ini`
  `Issue #650 <https://github.com/pantsbuild/pants/issues/650>`_
  `RB #1137 <https://rbcommons.com/s/twitter/r/1137>`_

* When a jvm doc tool (e.g. scaladoc) fails in combined mode, throw an exception
  `RB #1116 <https://rbcommons.com/s/twitter/r/1116>`_

* Remove hack to add java_sources in context
  `RB #1130 <https://rbcommons.com/s/twitter/r/1130>`_

* Memoize `Address.__hash__` computation
  `RB #1118 <https://rbcommons.com/s/twitter/r/1118>`_

* Add missing coverage deps
  `RB #1117 <https://rbcommons.com/s/twitter/r/1117>`_

* get `goal targets` using similar codepath to `goal builddict`
  `RB #1112 <https://rbcommons.com/s/twitter/r/1112>`_

* Memoize fingerprints by the FPStrategy hash
  `RB #1119 <https://rbcommons.com/s/twitter/r/1119>`_

* Factor in the jvm version string into the nailgun executor fingerprint
  `RB #1122 <https://rbcommons.com/s/twitter/r/1122>`_

* Fix some error reporting issues
  `RB #1113 <https://rbcommons.com/s/twitter/r/1113>`_

* Retry on failed scm push; also, pull with rebase to increase the odds of success
  `RB #1083 <https://rbcommons.com/s/twitter/r/1083>`_

* Make sure that 'option java_package' always overrides 'package' in protobuf_gen
  `RB #1108 <https://rbcommons.com/s/twitter/r/1108>`_

* Fix order-dependent force handling: if a version is forced in one place, it is forced everywhere
  `RB #1085 <https://rbcommons.com/s/twitter/r/1085>`_

* Survive targets without derivations
  `RB #1066 <https://rbcommons.com/s/twitter/r/1066>`_

* Make `internal_backend` plugins 1st class local pants plugins
  `RB #1073 <https://rbcommons.com/s/twitter/r/1073>`_

0.0.24 (9/23/2014)
------------------

API Changes
~~~~~~~~~~~

* Add a whitelist to jvm dependency analyzer
  `RB #888 <https://rbcommons.com/s/twitter/r/888>`_

* Refactor exceptions in build_file.py and build_file_parser.py to derive from a common baseclass
  and eliminate throwing `IOError`.
  `RB #954 <https://rbcommons.com/s/twitter/r/954>`_

* Support absolute paths on the command line when they start with the build root
  `RB #867 <https://rbcommons.com/s/twitter/r/867>`_

* Make `::` fail for an invalid dir much like `:` does for a dir with no BUILD file.
  `Issue #484 <https://github.com/pantsbuild/pants/issues/484>`_
  `RB #907 <https://rbcommons.com/s/twitter/r/907>`_

* Deprecate `pants` & `dependencies` aliases and remove `config`, `goal`, `phase`,
  `get_scm` & `set_scm` aliases
  `RB #899 <https://rbcommons.com/s/twitter/r/899>`_
  `RB #903 <https://rbcommons.com/s/twitter/r/903>`_
  `RB #912 <https://rbcommons.com/s/twitter/r/912>`_

* Export test infrastructure for plugin writers to use in `pantsbuild.pants.testinfra` sdist
  `Issue #539 <https://github.com/pantsbuild/pants/issues/539>`_
  `RB #997 <https://rbcommons.com/s/twitter/r/997>`_
  `RB #1004 <https://rbcommons.com/s/twitter/r/1004>`_

* Publishing improvements:

  - Add support for doing remote publishes with an explicit snapshot name
  - One publish/push db file per artifact

  `RB #923 <https://rbcommons.com/s/twitter/r/923>`_
  `RB #994 <https://rbcommons.com/s/twitter/r/994>`_

* Several improvements to `IdeGen` derived goals:

  - Adds the `--<goal>-use-source-root` for IDE project generation tasks
  - Added `--idea-exclude-maven-target` to keep IntelliJ from indexing 'target' directories
  - Changes the behavior of goal idea to create a subdirectory named for the project name
  - Added `exclude-folders` option in pants.ini, defaulted to excluding a few dirs in `.pants.d`

  `Issue #564 <https://github.com/pantsbuild/pants/issues/564>`_
  `RB #1006 <https://rbcommons.com/s/twitter/r/1006>`_
  `RB #1017 <https://rbcommons.com/s/twitter/r/1017>`_
  `RB #1019 <https://rbcommons.com/s/twitter/r/1019>`_
  `RB #1023 <https://rbcommons.com/s/twitter/r/1023>`_

* Enhancements to the `depmap` goal to support IDE plugins:

  - Add flag to dump project info output to file
  - Add missing resources to targets
  - Add content type to project Info

  `Issue #5 <https://github.com/pantsbuild/intellij-pants-plugin/issues/5>`_
  `RB #964 <https://rbcommons.com/s/twitter/r/964>`_
  `RB #987 <https://rbcommons.com/s/twitter/r/987>`_
  `RB #998 <https://rbcommons.com/s/twitter/r/998>`_

* Make `SourceRoot` fundamentally understand a rel_path
  `RB #1036 <https://rbcommons.com/s/twitter/r/1036>`_

* Added thrift-linter to pants
  `RB #1044 <https://rbcommons.com/s/twitter/r/1044>`_

* Support limiting coverage measurements globally by module or path
  `Issue #328 <https://github.com/pantsbuild/pants/issues/328>`_
  `Issue #369 <https://github.com/pantsbuild/pants/issues/369>`_
  `RB #1034 <https://rbcommons.com/s/twitter/r/1034>`_

* Update interpreter_cache.py to support a repo-wide interpreter requirement
  `RB #1025 <https://rbcommons.com/s/twitter/r/1025>`_

* Changed goal markdown:

  - Writes output to `./dist/markdown/`
  - Pages can include snippets from source files
    `<http://pantsbuild.github.io/page.html#include-a-file-snippet>`_

  `Issue #535 <https://github.com/pantsbuild/pants/issues/535>`_
  `RB #949 <https://rbcommons.com/s/twitter/r/949>`_
  `RB #961 <https://rbcommons.com/s/twitter/r/961>`_

* Rename `Phase` -> `Goal`
  `RB #856 <https://rbcommons.com/s/twitter/r/856>`_
  `RB #879 <https://rbcommons.com/s/twitter/r/879>`_
  `RB #880 <https://rbcommons.com/s/twitter/r/880>`_
  `RB #887 <https://rbcommons.com/s/twitter/r/887>`_
  `RB #890 <https://rbcommons.com/s/twitter/r/890>`_
  `RB #910 <https://rbcommons.com/s/twitter/r/910>`_
  `RB #913 <https://rbcommons.com/s/twitter/r/913>`_
  `RB #915 <https://rbcommons.com/s/twitter/r/915>`_
  `RB #931 <https://rbcommons.com/s/twitter/r/931>`_

* Android support additions:

  - Add `AaptBuild` task
  - Add `JarsignerTask` and `Keystore` target

  `RB #859 <https://rbcommons.com/s/twitter/r/859>`_
  `RB #883 <https://rbcommons.com/s/twitter/r/883>`_

* Git/Scm enhancements:

  - Allow the buildroot to be a subdirectory of the git worktree
  - Support getting the commit date of refs
  - Add merge-base and origin url properties to git

  `Issue #405 <https://github.com/pantsbuild/pants/issues/405>`_
  `RB #834 <https://rbcommons.com/s/twitter/r/834>`_
  `RB #871 <https://rbcommons.com/s/twitter/r/871>`_
  `RB #884 <https://rbcommons.com/s/twitter/r/884>`_
  `RB #886 <https://rbcommons.com/s/twitter/r/886>`_

Bugfixes
~~~~~~~~

* Numerous doc improvements & generation fixes
  `Issue #397 <https://github.com/pantsbuild/pants/issues/397>`_
  `Issue #451 <https://github.com/pantsbuild/pants/issues/451>`_
  `Issue #475 <https://github.com/pantsbuild/pants/issues/475>`_
  `RB #863 <https://rbcommons.com/s/twitter/r/863>`_
  `RB #865 <https://rbcommons.com/s/twitter/r/865>`_
  `RB #873 <https://rbcommons.com/s/twitter/r/873>`_
  `RB #876 <https://rbcommons.com/s/twitter/r/876>`_
  `RB #885 <https://rbcommons.com/s/twitter/r/885>`_
  `RB #938 <https://rbcommons.com/s/twitter/r/938>`_
  `RB #953 <https://rbcommons.com/s/twitter/r/953>`_
  `RB #960 <https://rbcommons.com/s/twitter/r/960>`_
  `RB #965 <https://rbcommons.com/s/twitter/r/965>`_
  `RB #992 <https://rbcommons.com/s/twitter/r/992>`_
  `RB #995 <https://rbcommons.com/s/twitter/r/995>`_
  `RB #1007 <https://rbcommons.com/s/twitter/r/1007>`_
  `RB #1008 <https://rbcommons.com/s/twitter/r/1008>`_
  `RB #1018 <https://rbcommons.com/s/twitter/r/1018>`_
  `RB #1020 <https://rbcommons.com/s/twitter/r/1020>`_
  `RB #1048 <https://rbcommons.com/s/twitter/r/1048>`_

* Fixup missing 'page.mustache' resource for `markdown` goal
  `Issue #498 <https://github.com/pantsbuild/pants/issues/498>`_
  `RB #918 <https://rbcommons.com/s/twitter/r/918>`_

* Publishing fixes:

  - Fix credentials fetching during publishing
  - Skipping a doc phase should result in transitive deps being skipped as well

  `RB #901 <https://rbcommons.com/s/twitter/r/901>`_
  `RB #1011 <https://rbcommons.com/s/twitter/r/1011>`_

* Several `IdeGen` derived task fixes:

  - Fix eclipse_gen & idea_gen for targets with both java and scala
  - Fixup EclipseGen resources globs to include prefs.
  - When a directory contains both `java_library` and `junit_tests` targets, make sure the IDE
    understands this is a test path, not a lib path

  `RB #857 <https://rbcommons.com/s/twitter/r/857>`_
  `RB #916 <https://rbcommons.com/s/twitter/r/916>`_
  `RB #996 <https://rbcommons.com/s/twitter/r/996>`_

* Fixes to the `depmap` goal to support IDE plugins:

  - Fixed source roots in project info in case of `ScalaLibrary` with `java_sources`
  - Fix `--depmap-project-info` for scala sources with the same package_prefix
  - Fix depmap KeyError

  `RB #955 <https://rbcommons.com/s/twitter/r/955>`_
  `RB #990 <https://rbcommons.com/s/twitter/r/990>`_
  `RB #1015 <https://rbcommons.com/s/twitter/r/1015>`_

* Make a better error message when os.symlink fails during bundle
  `RB #1037 <https://rbcommons.com/s/twitter/r/1037>`_

* Faster source root operations - update the internal data structure to include a tree
  `RB #1003 <https://rbcommons.com/s/twitter/r/1003>`_

* The goal filter's --filter-ancestor parameter works better now
  `Issue #506 <https://github.com/pantsbuild/pants/issues/506>`_
  `RB #925 <https://rbcommons.com/s/twitter/r/925/>`_

* Fix: goal markdown failed to load page.mustache
  `Issue #498 <https://github.com/pantsbuild/pants/issues/498>`_
  `RB #918 <https://rbcommons.com/s/twitter/r/918>`_

* Fix the `changed` goal so it can be run in a repo with a directory called 'build'
  `RB #872 <https://rbcommons.com/s/twitter/r/872>`_

* Patch `JvmRun` to accept `JvmApp`s
  `RB #893 <https://rbcommons.com/s/twitter/r/893>`_

* Add python as default codegen product
  `RB #894 <https://rbcommons.com/s/twitter/r/894>`_

* Fix the `filedeps` goal - it was using a now-gone .expand_files() API
  `Issue #437 <https://github.com/pantsbuild/pants/issues/437>`_,
  `RB #939 <https://rbcommons.com/s/twitter/r/939>`_

* Put back error message that shows path to missing BUILD files
  `RB #929 <https://rbcommons.com/s/twitter/r/929>`_

* Make sure the `junit_run` task only runs on targets that are junit compatible
  `Issue #508 <https://github.com/pantsbuild/pants/issues/508>`_
  `RB #924 <https://rbcommons.com/s/twitter/r/924>`_

* Fix `./pants goal targets`
  `Issue #333 <https://github.com/pantsbuild/pants/issues/333>`_
  `RB #796 <https://rbcommons.com/s/twitter/r/796>`_
  `RB #914 <https://rbcommons.com/s/twitter/r/914>`_

* Add `derived_from` to `ScroogeGen` synthetic targets
  `RB #926 <https://rbcommons.com/s/twitter/r/926>`_

* Properly order resources for pants goal test and pants goal run
  `RB #845 <https://rbcommons.com/s/twitter/r/845>`_

* Fixup Dependencies to be mainly target-type agnostic.
  `Issue #499 <https://github.com/pantsbuild/pants/issues/499>`_
  `RB #920 <https://rbcommons.com/s/twitter/r/920>`_

* Fixup JvmRun only-write-cmd-line flag to accept relative paths.
  `Issue #494 <https://github.com/pantsbuild/pants/issues/494>`_
  `RB #908 <https://rbcommons.com/s/twitter/r/908>`_
  `RB #911 <https://rbcommons.com/s/twitter/r/911>`_

* Fix the `--ivy-report` option and add integration test
  `RB #976 <https://rbcommons.com/s/twitter/r/976>`_

* Fix a regression in Emma/Cobertura and add tests
  `Issue #508 <https://github.com/pantsbuild/pants/issues/508>`_
  `RB #935 <https://rbcommons.com/s/twitter/r/935>`_

0.0.23 (8/11/2014)
------------------

API Changes
~~~~~~~~~~~

* Remove unused Task.invalidate_for method and unused extra_data variable
  `RB #849 <https://rbcommons.com/s/twitter/r/849>`_

* Add DxCompile task to android backend
  `RB #840 <https://rbcommons.com/s/twitter/r/840>`_

* Change all Task subclass constructor args to (\*args, \**kwargs)
  `RB #846 <https://rbcommons.com/s/twitter/r/846>`_

* The public API for the new options system
  `Issue #425 <https://github.com/pantsbuild/pants/pull/425>`_
  `RB #831 <https://rbcommons.com/s/twitter/r/831>`_
  `RB #819 <https://rbcommons.com/s/twitter/r/819>`_

* Rename pants.goal.goal.Goal to pants.goal.task_registrar.TaskRegistrar
  `Issue #345 <https://github.com/pantsbuild/pants/pull/345>`_
  `RB #843 <https://rbcommons.com/s/twitter/r/843>`_

Bugfixes
~~~~~~~~

* Better validation for AndroidTarget manifest field
  `RB #860 <https://rbcommons.com/s/twitter/r/860>`_

* Remove more references to /BUILD:target notation in docs
  `RB #855 <https://rbcommons.com/s/twitter/r/855>`_
  `RB #853 <https://rbcommons.com/s/twitter/r/853>`_

* Fix up the error message when attempting to publish without any configured repos
  `RB #850 <https://rbcommons.com/s/twitter/r/850>`_

* Miscellaneous fixes to protobuf codegen including handling collisions deterministically
  `RB #720 <https://rbcommons.com/s/twitter/r/720>`_

* Migrate some reasonable default values from pants.ini into 'defaults' in the pants source
  `Issue #455 <https://github.com/pantsbuild/pants/pull/455>`_
  `Issue #456 <https://github.com/pantsbuild/pants/pull/456>`_
  `Issue #458 <https://github.com/pantsbuild/pants/pull/458>`_
  `RB #852 <https://rbcommons.com/s/twitter/r/852>`_

* Updated the basename and name of some targets to prevent colliding bundles in dist/
  `RB #847 <https://rbcommons.com/s/twitter/r/847>`_

* Provide a better error message when referencing the wrong path to a BUILD file
  `RB #841 <https://rbcommons.com/s/twitter/r/841>`_

* Add assert_list to ensure an argument is a list - use this to better validate many targets
  `RB #811 <https://rbcommons.com/s/twitter/r/811>`_

* Update front-facing help and error messages for Android targets/tasks
  `RB #837 <https://rbcommons.com/s/twitter/r/837>`_

* Use JvmFingerprintStrategy in cache manager
  `RB #835 <https://rbcommons.com/s/twitter/r/835>`_

0.0.22 (8/4/2014)
-----------------

API Changes
~~~~~~~~~~~

* Upgrade pex dependency from twitter.common.python 0.6.0 to pex 0.7.0
  `RB #825 <https://rbcommons.com/s/twitter/r/825>`_

* Added a --spec-exclude command line flag to exclude specs by regular expression
  `RB #747 <https://rbcommons.com/s/twitter/r/747>`_

* Upgrade requests, flip to a ranged requirement to help plugins
  `RB #771 <https://rbcommons.com/s/twitter/r/771>`_

* New goal ``ensime`` to generate Ensime projects for Emacs users.
  `RB #753 <https://rbcommons.com/s/twitter/r/753>`_

Bugfixes
~~~~~~~~

* `goal repl` consumes targets transitively
  `RB #781 <https://rbcommons.com/s/twitter/r/781>`_

* Fixup JvmCompile to always deliver non-None products that were required by downstream
  `RB #794 <https://rbcommons.com/s/twitter/r/794>`_

* Relativize classpath for non-ng java execution
  `RB #804 <https://rbcommons.com/s/twitter/r/804>`_

* Added some docs and a bugfix on debugging a JVM tool (like jar-tool or checkstyle) locally
  `RB #791 <https://rbcommons.com/s/twitter/r/791>`_

* Added an excludes attribute that is set to an empty set for all SourcePayload subclasses
  `Issue #414 <https://github.com/pantsbuild/pants/pull/414>`_
  `RB #793 <https://rbcommons.com/s/twitter/r/793>`_

* Add binary fetching support for OSX 10.10 and populate thrift and protoc binaries
  `RB #789 <https://rbcommons.com/s/twitter/r/789>`_

* Fix the pants script exit status when bootstrapping fails
  `RB #779 <https://rbcommons.com/s/twitter/r/779>`_

* Added benchmark target to maven_layout()
  `RB #780 <https://rbcommons.com/s/twitter/r/780>`_

* Fixup a hole in external dependency listing wrt encoding
  `RB #776 <https://rbcommons.com/s/twitter/r/776>`_

* Force parsing for filtering specs
  `RB #775 <https://rbcommons.com/s/twitter/r/775>`_

* Fix a scope bug for java agent manifest writing
  `RB #768 <https://rbcommons.com/s/twitter/r/768>`_
  `RB #770 <https://rbcommons.com/s/twitter/r/770>`_

* Plumb ivysettings.xml location to the publish template
  `RB #764 <https://rbcommons.com/s/twitter/r/764>`_

* Fix goal markdown: README.html pages clobbered each other
  `RB #750 <https://rbcommons.com/s/twitter/r/750>`_

0.0.21 (7/25/2014)
------------------

Bugfixes
~~~~~~~~

* Fixup NailgunTasks with missing config_section overrides
  `RB # 762 <https://rbcommons.com/s/twitter/r/762>`_

0.0.20 (7/25/2014)
------------------

API Changes
~~~~~~~~~~~

* Hide stack traces by default
  `Issue #326 <https://github.com/pantsbuild/pants/issues/326>`_
  `RB #655 <https://rbcommons.com/s/twitter/r/655>`_

* Upgrade to ``twitter.common.python`` 0.6.0 and adjust to api change
  `RB #746 <https://rbcommons.com/s/twitter/r/746>`_

* Add support for `Cobertura <http://cobertura.github.io/cobertura>`_ coverage
  `Issue #70 <https://github.com/pantsbuild/pants/issues/70>`_
  `RB #637 <https://rbcommons.com/s/twitter/r/637>`_

* Validate that ``junit_tests`` targets have non-empty sources
  `RB #619 <https://rbcommons.com/s/twitter/r/619>`_

* Add support for the `Ragel <http://www.complang.org/ragel>`_ state-machine generator
  `Issue #353 <https://github.com/pantsbuild/pants/issues/353>`_
  `RB #678 <https://rbcommons.com/s/twitter/r/678>`_

* Add ``AndroidTask`` and ``AaptGen`` tasks
  `RB #672 <https://rbcommons.com/s/twitter/r/672>`_
  `RB #676 <https://rbcommons.com/s/twitter/r/676>`_
  `RB #700 <https://rbcommons.com/s/twitter/r/700>`_

Bugfixes
~~~~~~~~

* Numerous doc fixes
  `Issue #385 <https://github.com/pantsbuild/pants/issues/385>`_
  `Issue #387 <https://github.com/pantsbuild/pants/issues/387>`_
  `Issue #395 <https://github.com/pantsbuild/pants/issues/395>`_
  `RB #728 <https://rbcommons.com/s/twitter/r/728>`_
  `RB #729 <https://rbcommons.com/s/twitter/r/729>`_
  `RB #730 <https://rbcommons.com/s/twitter/r/730>`_
  `RB #738 <https://rbcommons.com/s/twitter/r/738>`_

* Expose types needed to specify ``jvm_binary.deploy_jar_rules``
  `Issue #383 <https://github.com/pantsbuild/pants/issues/383>`_
  `RB #727 <https://rbcommons.com/s/twitter/r/727>`_

* Require information about jars in ``depmap`` with ``--depmap-project-info``
  `RB #721 <https://rbcommons.com/s/twitter/r/721>`_

0.0.19 (7/23/2014)
------------------

API Changes
~~~~~~~~~~~

* Enable Nailgun Per Task
  `RB #687 <https://rbcommons.com/s/twitter/r/687>`_

Bugfixes
~~~~~~~~

* Numerous doc fixes
  `RB #699 <https://rbcommons.com/s/twitter/r/699>`_
  `RB #703 <https://rbcommons.com/s/twitter/r/703>`_
  `RB #704 <https://rbcommons.com/s/twitter/r/704>`_

* Fixup broken ``bundle`` alias
  `Issue #375 <https://github.com/pantsbuild/pants/issues/375>`_
  `RB #722 <https://rbcommons.com/s/twitter/r/722>`_

* Remove dependencies on ``twitter.common.{dirutil,contextutils}``
  `RB #710 <https://rbcommons.com/s/twitter/r/710>`_
  `RB #713 <https://rbcommons.com/s/twitter/r/713>`_
  `RB #717 <https://rbcommons.com/s/twitter/r/717>`_
  `RB #718 <https://rbcommons.com/s/twitter/r/718>`_
  `RB #719 <https://rbcommons.com/s/twitter/r/719>`_
  `RB #726 <https://rbcommons.com/s/twitter/r/726>`_

* Fixup missing ``JunitRun`` resources requirement
  `RB #709 <https://rbcommons.com/s/twitter/r/709>`_

* Fix transitive dependencies for ``GroupIterator``/``GroupTask``
  `RB #706 <https://rbcommons.com/s/twitter/r/706>`_

* Ensure resources are prepared after compile
  `Issue #373 <http://github.com/pantsbuild/pants/issues/373>`_
  `RB #708 <https://rbcommons.com/s/twitter/r/708>`_

* Upgrade to ``twitter.common.python`` 0.5.10 to brings in the following bugfix::

    Update the mtime on retranslation of existing distributions.

    1bff97e stopped existing distributions from being overwritten, to
    prevent subtle errors. However without updating the mtime these
    distributions will appear to be permanently expired wrt the ttl.

  `RB #707 <https://rbcommons.com/s/twitter/r/707>`_

* Resurrected pants goal idea with work remaining on source and javadoc jar mapping
  `RB #695 <https://rbcommons.com/s/twitter/r/695>`_

* Fix BinaryUtil raise of BinaryNotFound
  `Issue #367 <https://github.com/pantsbuild/pants/issues/367>`_
  `RB #705 <https://rbcommons.com/s/twitter/r/705>`_

0.0.18 (7/16/2014)
------------------

API Changes
~~~~~~~~~~~

* Lock globs into ``rootdir`` and below
  `Issue #348 <https://github.com/pantsbuild/pants/issues/348>`_
  `RB #686 <https://rbcommons.com/s/twitter/r/686>`_

Bugfixes
~~~~~~~~

* Several doc fixes
  `RB #654 <https://rbcommons.com/s/twitter/r/654>`_
  `RB #693 <https://rbcommons.com/s/twitter/r/693>`_

* Fix relativity of antlr sources
  `RB #679 <https://rbcommons.com/s/twitter/r/679>`_

0.0.17 (7/15/2014)
------------------

* Initial published version of ``pantsbuild.pants``.

