package expo.modules.f7five0stamp

import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/**
 * JS side: `readStamp()` resolves to the stamp JSON the server put in this
 * app's APK when it was downloaded, or null (built locally, installed from a
 * GitHub release, or unreadable). See ApkStamp.
 */
class F7FIVE0StampModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("F7FIVE0Stamp")

    AsyncFunction("readStamp") {
      val path = appContext.reactContext?.applicationInfo?.sourceDir
      if (path == null) null else ApkStamp.read(path)
    }
  }
}
