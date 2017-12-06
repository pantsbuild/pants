# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.coursier_resolve import CoursierResolve
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants.util.contextutil import temporary_dir
from pants_test.base_test import BaseTest


class CoursierTest(BaseTest):
  def test_flatten_result(self):
    flat_resolution = CoursierResolve._flatten_resolution_by_root(
      {"dependencies": [{"dependencies": [{"dependencies": [], "coord": "com.thoughtworks.paranamer:paranamer:2.3"},
                                          {"dependencies": [{"dependencies": [], "coord": "org.tukaani:xz:1.0"}],
                                           "coord": "org.apache.commons:commons-compress:1.4.1"},
                                          {"dependencies": [], "coord": "org.codehaus.jackson:jackson-core-asl:1.8.8"},
                                          {"dependencies": [{"dependencies": [],
                                                             "coord": "org.codehaus.jackson:jackson-core-asl:1.8.8"}],
                                           "coord": "org.codehaus.jackson:jackson-mapper-asl:1.8.8"},
                                          {"dependencies": [], "coord": "org.slf4j:slf4j-api:1.6.4"},
                                          {"dependencies": [], "coord": "org.xerial.snappy:snappy-java:1.0.4.1"}],
                         "coord": "org.apache.avro:avro:1.7.4"},
                        {"dependencies": [{"dependencies": [], "coord": "org.hamcrest:hamcrest-core:1.3"}],
                         "coord": "junit:junit:4.12"},
                        {"dependencies": [{"dependencies": [], "coord": "org.hamcrest:hamcrest-core:1.3"}],
                         "coord": "org.hamcrest:hamcrest-library:1.3"}], "coord": "root"})

    self.assertEqual({
      "org.apache.avro:avro:1.7.4": [
        "com.thoughtworks.paranamer:paranamer:2.3",
        "org.tukaani:xz:1.0",
        "org.apache.commons:commons-compress:1.4.1",
        "org.codehaus.jackson:jackson-core-asl:1.8.8",
        "org.codehaus.jackson:jackson-core-asl:1.8.8",
        "org.codehaus.jackson:jackson-mapper-asl:1.8.8",
        "org.slf4j:slf4j-api:1.6.4",
        "org.xerial.snappy:snappy-java:1.0.4.1"
      ],
      "org.hamcrest:hamcrest-library:1.3": [
        "org.hamcrest:hamcrest-core:1.3"
      ],
      "junit:junit:4.12": [
        "org.hamcrest:hamcrest-core:1.3"
      ]
    }, flat_resolution)

  def test_coord_to_resolved_jars(self):
    with temporary_dir() as coursier_cache_path, temporary_dir() as pants_path:
      coord_to_jars = CoursierResolve._map_coord_to_resolved_jars({
        "conflict_resolution": {},
        "dependencies": [
          {
            "coord": "com.thoughtworks.paranamer:paranamer:2.3",
            "files": [
              [
                "sources",
                pants_path
              ]
            ],
            "dependencies": []
          },
          {
            "coord": "org.slf4j:slf4j-api:1.6.4",
            "files": [
              [
                "sources",
                pants_path
              ]
            ],
            "dependencies": []
          },
          {
            "coord": "org.xerial.snappy:snappy-java:1.0.4.1",
            "files": [
              [
                "sources",
                pants_path
              ]
            ],
            "dependencies": []
          },
          {
            "coord": "org.apache.commons:commons-compress:1.4.1",
            "files": [
              [
                "sources",
                pants_path
              ]
            ],
            "dependencies": [
              {
                "coord": "org.tukaani:xz:1.0",
                "files": [
                  [
                    "sources",
                    pants_path
                  ]
                ],
                "dependencies": []
              }
            ]
          },
          {
            "coord": "org.apache.avro:avro:1.7.4",
            "files": [
              [
                "sources",
                pants_path
              ]
            ],
            "dependencies": [
              {
                "coord": "com.thoughtworks.paranamer:paranamer:2.3",
                "files": [
                  [
                    "sources",
                    pants_path
                  ]
                ],
                "dependencies": []
              },
              {
                "coord": "org.apache.commons:commons-compress:1.4.1",
                "files": [
                  [
                    "sources",
                    pants_path
                  ]
                ],
                "dependencies": [
                  {
                    "coord": "org.tukaani:xz:1.0",
                    "files": [
                      [
                        "sources",
                        pants_path
                      ]
                    ],
                    "dependencies": []
                  }
                ]
              },
              {
                "coord": "org.codehaus.jackson:jackson-core-asl:1.8.8",
                "files": [
                  [
                    "sources",
                    pants_path
                  ]
                ],
                "dependencies": []
              },
              {
                "coord": "org.codehaus.jackson:jackson-mapper-asl:1.8.8",
                "files": [
                  [
                    "sources",
                    pants_path
                  ]
                ],
                "dependencies": [
                  {
                    "coord": "org.codehaus.jackson:jackson-core-asl:1.8.8",
                    "files": [
                      [
                        "sources",
                        pants_path
                      ]
                    ],
                    "dependencies": []
                  }
                ]
              },
              {
                "coord": "org.slf4j:slf4j-api:1.6.4",
                "files": [
                  [
                    "sources",
                    pants_path
                  ]
                ],
                "dependencies": []
              },
              {
                "coord": "org.xerial.snappy:snappy-java:1.0.4.1",
                "files": [
                  [
                    "sources",
                    pants_path
                  ]
                ],
                "dependencies": []
              }
            ]
          },
          {
            "coord": "org.tukaani:xz:1.0",
            "files": [
              [
                "sources",
                pants_path
              ]
            ],
            "dependencies": []
          },
          {
            "coord": "org.codehaus.jackson:jackson-mapper-asl:1.8.8",
            "files": [
              [
                "sources",
                pants_path
              ]
            ],
            "dependencies": [
              {
                "coord": "org.codehaus.jackson:jackson-core-asl:1.8.8",
                "files": [
                  [
                    "sources",
                    pants_path
                  ]
                ],
                "dependencies": []
              }
            ]
          },
          {
            "coord": "org.codehaus.jackson:jackson-core-asl:1.8.8",
            "files": [
              [
                "sources",
                pants_path
              ]
            ],
            "dependencies": []
          }
        ]
      },
        coursier_cache_path,
        # It is okay to use a hardcoded location here because we are only symlink somewhere in pants_dir into it,
        # so it does not matter whether it exists.
        pants_path)

      compress = coord_to_jars['org.apache.commons:commons-compress:1.4.1']
      self.assertEqual(1, len(compress))
      self.assertEqual(M2Coordinate('org.apache.commons', 'commons-compress', '1.4.1', 'sources'),
                       compress.__iter__().next().coordinate)

      jackson = coord_to_jars['org.codehaus.jackson:jackson-core-asl:1.8.8']
      self.assertEqual(1, len(jackson))
      self.assertEqual(M2Coordinate('org.codehaus.jackson', 'jackson-core-asl', '1.8.8', 'sources'),
                       jackson.__iter__().next().coordinate)
