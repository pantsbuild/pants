/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

import sbt._
import sbt.Keys._

object ZincBuild extends Build {
  val sbtVersion = "0.13.0-SNAPSHOT"

  val resolveSbtLocally = SettingKey[Boolean]("resolve-sbt-locally")

  lazy val buildSettings = Defaults.defaultSettings ++ Seq(
    organization := "com.typesafe.zinc",
    version := "0.3.0-SNAPSHOT",
    scalaVersion := "2.9.2",
    crossPaths := false
  )

  lazy val zinc = Project(
    "zinc",
    file("."),
    settings = buildSettings ++ Version.settings ++ Publish.settings ++ Scriptit.settings ++ Seq(
      resolveSbtLocally := false,
      resolvers <+= resolveSbtLocally { local => if (local) Resolver.mavenLocal else Opts.resolver.sonatypeSnapshots },
      resolvers += "typesafe-third-party" at "http://repo.typesafe.com/typesafe/third-party",
      libraryDependencies ++= Seq(
        "com.typesafe.sbt" % "incremental-compiler" % sbtVersion,
        "com.typesafe.sbt" % "compiler-interface" % sbtVersion classifier "sources",
        "jline" % "jline" % "1.0" % "optional",
        "com.martiansoftware" % "nailgun" % "0.7.1" % "optional"
      )
    )
  )

  lazy val dist = Project(
    id = "dist",
    base = file("dist"),
    settings = buildSettings ++ Dist.settings
  )
}
