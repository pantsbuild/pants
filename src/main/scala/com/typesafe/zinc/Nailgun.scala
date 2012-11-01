/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.zinc

import com.martiansoftware.nailgun.{ Alias, AliasManager, NGContext, NGServer }
import java.io.File
import sbt.Path

class Nailgun // for classOf

object Nailgun {
  val DefaultPort = 3030
  val DefaultTimeout = 0 // no timeout

  private[this] var shutdownTimer: Util.Alarm = _

  /**
   * Run the nailgun server. Accepts port number and idle timeout as arguments.
   */
  def main(args: Array[String]): Unit = {
    val port = try args(0).toInt catch { case _: Exception => DefaultPort }
    val timeout = try Util.duration(args(1), DefaultTimeout) catch { case _: Exception => DefaultTimeout }
    start(port, timeout)
  }

  /**
   * Start a nailgun server in a separate process.
   */
  def fork(options: Seq[String], classpath: Seq[File], port: Int = DefaultPort, timeout: String = "0"): Unit = {
    val classpathOpts = Seq("-classpath", Path.makeString(classpath))
    val mainOpts = Seq(classOf[Nailgun].getName, port.toString, timeout)
    val cmd = Seq("java") ++ addDefaultOptions(options) ++ classpathOpts ++ mainOpts
    Runtime.getRuntime.exec(cmd.toArray)
  }

  /**
   * Add default JVM options.
   */
  def addDefaultOptions(options: Seq[String]): Seq[String] = {
    var optMode, optXms, optXmx, optXXMaxPermSize, optXXReservedCodeCacheSize = ""
    var otherOpts = Seq.empty[String]
    for (opt <- options) {
      if (opt == "-client" || opt == "-server") optMode = opt
      else if (opt startsWith "-Xms") optXms = opt
      else if (opt startsWith "-Xmx") optXmx = opt
      else if (opt startsWith "-XX:MaxPermSize") optXXMaxPermSize = opt
      else if (opt startsWith "-XX:ReservedCodeCacheSize") optXXReservedCodeCacheSize = opt
      else otherOpts :+= opt
    }
    if (optMode.isEmpty) optMode = "-server"
    if (optXms.isEmpty && optXmx.isEmpty) { optXms = "-Xms1024m"; optXmx="-Xmx1024m" }
    if (optXXMaxPermSize.isEmpty) optXXMaxPermSize = "-XX:MaxPermSize=384m"
    if (optXXReservedCodeCacheSize.isEmpty) optXXReservedCodeCacheSize = "-XX:ReservedCodeCacheSize=192m"
    Seq(optMode, optXms, optXmx, optXXMaxPermSize, optXXReservedCodeCacheSize) ++ otherOpts
  }

  /**
   * Start the nailgun server.
   * Available aliased commands are 'zinc', 'status', and 'shutdown'.
   */
  def start(port: Int, timeout: Long): Unit = {
    val server = new NGServer(null, port)
    val am = server.getAliasManager
    am.addAlias(new Alias("zinc", "scala incremental compiler", classOf[Nailgun]))
    am.addAlias(new Alias("status", "status of nailgun server", classOf[Nailgun]))
    am.addAlias(new Alias("shutdown", "shutdown the nailgun server", classOf[Nailgun]))
    shutdownTimer = Util.timer(timeout) { server.shutdown(true) } // exitVM = true
    Runtime.getRuntime().addShutdownHook(new ShutdownHook(server))
    val thread = new Thread(server)
    thread.setName("ZincNailgun(%s)" format port)
    thread.start()
  }

  /**
   * Run a nailed command, based on the nailgun context.
   */
  def nailMain(context: NGContext): Unit = {
    shutdownTimer.reset()
    context.getCommand match {
      case "zinc"     => zinc(context)
      case "status"   => status(context)
      case "shutdown" => shutdown(context)
      case cmd        => context.err.println("Unknown command: " + cmd)
    }
  }

  /**
   * Run the zinc compile command, from the actual working directory.
   */
  def zinc(context: NGContext): Unit = {
    Main.run(context.getArgs, Some(new File(context.getWorkingDirectory)))
  }

  /**
   * Output all currently cached zinc compilers.
   */
  def status(context: NGContext): Unit = {
    val entries = Compiler.compilerCache.entries
    val counted = Util.counted(entries.size, "cached compiler", "", "s")
    context.out.println("Nailgun server running with " + counted)
    context.out.println("")
    context.out.println("Version = " + Setup.versionString)
    context.out.println("")
    context.out.println("Zinc compiler cache limit = " + Setup.Defaults.compilerCacheLimit)
    context.out.println("Resident scalac cache limit = " + Setup.Defaults.residentCacheLimit)
    context.out.println("Analysis cache limit = " + Setup.Defaults.analysisCacheLimit)
    entries foreach {
      case (setup, compiler) =>
        context.out.println("")
        context.out.println("%s [%s]" format (compiler, compiler.hashCode.toHexString))
        Setup.show(setup, context.out.println)
    }
  }

  /**
   * Shutdown the zinc nailgun server.
   */
  def shutdown(context: NGContext): Unit = {
    context.getNGServer.shutdown(true)
  }

  /**
   * Shutdown hook in case of interrupted exit.
   */
  class ShutdownHook(server: NGServer) extends Thread {
    override def run(): Unit = {
      server.shutdown(false) // exitVM = false
      // give some time to shutdown
      var count = 0
      while (server.isRunning && (count < 50)) {
        try { Thread.sleep(100) } catch { case _: InterruptedException => }
        count += 1
      }
    }
  }
}
