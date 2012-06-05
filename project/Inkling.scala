/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

import sbt._
import sbt.Keys._

object Inkling extends Build {
  val sbtVersion = "0.13.0-SNAPSHOT"

  lazy val buildSettings = Defaults.defaultSettings ++ Seq(
    organization := "com.typesafe.inkling",
    version := "0.1.0-SNAPSHOT",
    scalaVersion := "2.9.2",
    crossPaths := false
  )

  lazy val inkling = Project(
    "inkling",
    file("."),
    settings = buildSettings ++ Version.settings ++ Publish.settings ++ Seq(
      resolvers += "Sonatype Snapshots" at "https://oss.sonatype.org/content/repositories/snapshots",
      libraryDependencies ++= Seq(
        "com.typesafe.sbt" % "incremental-compiler" % sbtVersion,
        "com.typesafe.sbt" % "compiler-interface" % sbtVersion classifier "sources",
        "jline" % "jline" % "1.0"
      )
    )
  )

  lazy val dist = Project(
    id = "dist",
    base = file("dist"),
    settings = buildSettings ++ Dist.settings
  )
}
