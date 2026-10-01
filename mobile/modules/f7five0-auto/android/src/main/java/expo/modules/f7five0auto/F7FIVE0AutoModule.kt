package expo.modules.f7five0auto

import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/**
 * JS side of the Android Auto bridge. JS answers browse requests
 * (`onAutoLoadChildren` -> `setChildren`), handles transport commands from the
 * car (`onAutoCommand`) and mirrors playback state (`setState`).
 */
class F7FIVE0AutoModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("F7FIVE0Auto")

    Events("onAutoCommand", "onAutoLoadChildren")

    OnCreate {
      AutoBridge.module = this@F7FIVE0AutoModule
    }

    OnDestroy {
      if (AutoBridge.module === this@F7FIVE0AutoModule) AutoBridge.module = null
    }

    Function("setChildren") { parentId: String, itemsJson: String ->
      val ctx = appContext.reactContext
      if (ctx != null) AutoBridge.setChildren(ctx, parentId, itemsJson)
      ctx != null
    }

    Function("setState") { stateJson: String ->
      AutoBridge.setState(stateJson)
      true
    }

    Function("isCarConnected") {
      AutoBridge.service != null
    }
  }

  internal fun emit(name: String, body: Map<String, Any?>) {
    sendEvent(name, body)
  }
}
