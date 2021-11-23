package org.pantsbuild.example.app;

import org.pantsbuild.example.lib.ExampleLib
import com.google.common.truth.BadAndDangerous

class ExampleApp {
    def main(args: Array[String]): Unit = {
        println(BadAndDangerous.hello())
        com.google.common.truth.Truth.assertThat(new Object())
    }
}
