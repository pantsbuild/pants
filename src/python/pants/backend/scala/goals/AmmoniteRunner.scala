//package org.pantsbuild.jvm.ammonite
package ammonite.integration

import java.io.{InputStream, OutputStream, PrintStream}
import java.net.URLClassLoader
import java.nio.file.NoSuchFileException

import ammonite.main._

object AmmoniteRunner {
  def main(args: Array[String]): Unit = {
    // done by amm, should we do?
    // ProxyFromEnv.setPropProxyFromEnv()

//    val printErr = new PrintStream(System.err)
//    val printOut = new PrintStream(System.out)
//
//    val customName = s"Ammonite REPL [Pants Build EXTREME!], ${ammonite.Constants.version}"
//    Config.parser.constructEither(args, customName = customName) match {
//      case Left(msg) =>
//        printErr.println(msg)
//        sys.exit(1)
//      case Right(cliConfig) =>
//        val runner = new MainRunner(
//          cliConfig, printOut, printErr, System.in, System.out, System.err, os.pwd
//        )
//
//        runner.runRepl()
//    }

    ammonite.Main().run()
  }
}
