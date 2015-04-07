// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.scalac.plugin

import tools.nsc.{Global, Phase}
import tools.nsc.plugins.{Plugin, PluginComponent}

/**
 * A very simple plugin that just logs its existence in the pipeline.
 *
 * @param global The compiler instance this plugin is installed in.
 */
class HelloScalac(val global: Global) extends Plugin {
  // Required Plugin boilerplate.
  val name = "hello_scalac"
  val description = "Logs a greeting."
  val components = List[PluginComponent](Component)

  private[this] object Component extends PluginComponent {
    // Required PluginComponent boilerplate.
    val global: HelloScalac.this.global.type = HelloScalac.this.global
    val runsAfter = List[String]("parser")
    val phaseName = HelloScalac.this.name

    def newPhase(prev: Phase): Phase = new SayHello(prev)

    private[this] class SayHello(prev: Phase) extends StdPhase(prev) {
      override def apply(unit: global.CompilationUnit) {
        global.inform("Hello Scalac!")
        super.run
      }
    }
  }
}
