// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.scalac.plugin

import tools.nsc.{Global, Phase}
import tools.nsc.plugins.{Plugin, PluginComponent}

/**
 * A very simple plugin that just logs its existence in the pipeline.
 *
 * @param global The compiler instance this plugin is installed in.
 */
class SimpleScalacPlugin(val global: Global) extends Plugin {
  // Required Plugin boilerplate.
  val name = "simple_scalac_plugin"
  val description = "Logs a greeting."
  val components = List[PluginComponent](Component)

  var pluginOpts: List[String] = Nil

  override def processOptions(options: List[String], error: String => Unit) = {
    pluginOpts = options
  }

  private[this] object Component extends PluginComponent {
    // Required PluginComponent boilerplate.
    val global: SimpleScalacPlugin.this.global.type = SimpleScalacPlugin.this.global
    val runsAfter = List[String]("parser")
    val phaseName = SimpleScalacPlugin.this.name

    def newPhase(prev: Phase): Phase = new SayHello(prev)

    private[this] class SayHello(prev: Phase) extends StdPhase(prev) {
      override def apply(unit: global.CompilationUnit) {
        var pluginOptsStr = pluginOpts.mkString(" ")
        global.inform(s"Hello ${unit.source}! SimpleScalacPlugin ran with " +
          s"${pluginOpts.length} args: ${pluginOptsStr}")
      }
    }
  }
}
