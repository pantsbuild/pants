/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

import sbt._
import sbt.Keys._

object ZincBuild extends Build {
  val sbtVersion = "0.13.7"

  val resolveSbtLocally = settingKey[Boolean]("resolve-sbt-locally")

  lazy val buildSettings = Seq(
    organization := "com.typesafe.zinc",
    version := "0.3.7",
    scalaVersion := "2.10.4",
    crossPaths := false
  )

  lazy val zinc = Project(
    "zinc",
    file("."),
    settings = buildSettings ++ Version.settings ++ Publish.settings ++ Dist.settings ++ Scriptit.settings ++ Seq(
      resolveSbtLocally := false,
      resolvers += (if (resolveSbtLocally.value) Resolver.mavenLocal else Opts.resolver.sonatypeSnapshots),
      libraryDependencies ++= Seq(
        "com.typesafe.sbt" % "incremental-compiler" % sbtVersion,
        "com.typesafe.sbt" % "compiler-interface" % sbtVersion classifier "sources",
        "com.martiansoftware" % "nailgun-server" % "0.9.1" % "optional"
      ),
      scalacOptions ++= Seq("-feature", "-deprecation", "-Xlint")
    )
  )
}
