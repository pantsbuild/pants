/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

import sbt._
import sbt.Keys._

object ZincBuild extends Build {
  val sbtVersion = "0.13.2-SNAPSHOT"

  val resolveSbtLocally = SettingKey[Boolean]("resolve-sbt-locally")

  lazy val buildSettings = Defaults.defaultSettings ++ Seq(
    organization := "com.typesafe.zinc",
    version := "0.3.1-SNAPSHOT",
    scalaVersion := "2.10.3",
    crossPaths := false
  )

  lazy val zinc = Project(
    "zinc",
    file("."),
    settings = buildSettings ++ Version.settings ++ Publish.settings ++ Scriptit.settings ++ Seq(
      resolveSbtLocally := false,
      resolvers <+= resolveSbtLocally { local => if (local) Resolver.mavenLocal else Opts.resolver.sonatypeSnapshots },
      libraryDependencies ++= Seq(
        "com.typesafe.sbt" % "incremental-compiler" % sbtVersion,
        "com.typesafe.sbt" % "compiler-interface" % sbtVersion classifier "sources",
        "com.martiansoftware" % "nailgun-server" % "0.9.1" % "optional"
      ),
      scalacOptions ++= Seq("-feature", "-deprecation", "-Xlint")
    )
  )

  lazy val dist = Project(
    id = "dist",
    base = file("dist"),
    settings = buildSettings ++ Dist.settings
  )
}
