/*
 * Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.backend.scala.scalapb

import java.util.jar.JarInputStream
import java.io.{File, FileInputStream}
import java.net.URLClassLoader
import protocbridge.{ProtocBridge, ProtocCodeGenerator, ProtocRunner, SandboxedJvmGenerator}
import scalapb.ScalaPbCodeGenerator


// Derived in part from ScalaPBC under Apache License v2.0. Introduced errors are mine.

case class Config(
  protocPath: Option[String] = None,
  throwException: Boolean = false,
  args: Seq[String] = Seq.empty,
  namedGenerators: Seq[(String, ProtocCodeGenerator)] = Seq("scala" -> ScalaPbCodeGenerator),
)

class ScalaPbcException(msg: String) extends RuntimeException(msg)

object ScalaPBShim {
  private val ProtocPathArgument     = "--protoc="

  def processArgs(args: Array[String]): Config = {
    case class State(cfg: Config, passThrough: Boolean)

    args
      .foldLeft(State(Config(), false)) { case (state, item) =>
        (state.passThrough, item) match {
          case (false, "--")      => state.copy(passThrough = true)
          case (false, "--throw") => state.copy(cfg = state.cfg.copy(throwException = true))
          case (false, p) if p.startsWith(ProtocPathArgument) =>
            state.copy(
              cfg = state.cfg
                .copy(protocPath = Some(p.substring(ProtocPathArgument.length)))
            )
          case (_, other) =>
            state.copy(passThrough = true, cfg = state.cfg.copy(args = state.cfg.args :+ other))
        }
      }
      .cfg
  }

  def findMainClass(f: File): Either[String, String] = {
    val jin = new JarInputStream(new FileInputStream(f))
    try {
      val manifest = jin.getManifest()
      Option(manifest.getMainAttributes().getValue("Main-Class"))
        .toRight("Could not find main class for plugin")
        .map(_ + "$")
    } finally {
      jin.close()
    }
  }

  private[scalapb] def runProtoc(config: Config): Int = {
    val protoc = config.protocPath.getOrElse(throw new RuntimeException("--protoc not specified"))

    ProtocBridge.runWithGenerators(
      ProtocRunner(protoc),
      namedGenerators = config.namedGenerators,
      params = config.args
    )
  }

  def main(args: Array[String]): Unit = {
    val config = processArgs(args)
    val code   = runProtoc(config)

    if (!config.throwException) {
      sys.exit(code)
    } else {
      if (code != 0) {
        throw new ScalaPbcException(s"Exit with code $code")
      }
    }
  }
}