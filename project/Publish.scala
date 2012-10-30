/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

import sbt._
import sbt.Keys._

object Publish {
  val publishLocally = SettingKey[Boolean]("publish-locally")

  lazy val settings: Seq[Setting[_]] = Seq(
    publishMavenStyle := true,
    publishLocally := false,
    publishTo <<= (version, publishLocally) { (v, local) =>
      if (local) Some(Opts.resolver.mavenLocalFile)
      else if (v.endsWith("SNAPSHOT")) Some(Opts.resolver.sonatypeSnapshots)
      else Some(Opts.resolver.sonatypeStaging)
    },
    credentials += Credentials(Path.userHome / ".ivy2" / "sonatype-credentials"),
    publishArtifact in Test := false,
    homepage := Some(url("https://github.com/typesafehub/zinc")),
    licenses := Seq("Apache 2" -> url("http://www.apache.org/licenses/LICENSE-2.0")),
    pomExtra := {
      <scm>
        <url>https://github.com/typesafehub/zinc</url>
        <connection>scm:git:git@github.com:typesafehub/zinc.git</connection>
      </scm>
      <developers>
        <developer>
          <id>harrah</id>
          <name>Mark Harrah</name>
          <url>https://github.com/harrah</url>
        </developer>
        <developer>
          <id>pvlugter</id>
          <name>Peter Vlugter</name>
          <url>https://github.com/pvlugter</url>
        </developer>
      </developers>
    },
    pomIncludeRepository := { _ => false }
  )
}
