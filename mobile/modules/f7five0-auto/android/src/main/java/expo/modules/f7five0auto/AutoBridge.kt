package expo.modules.f7five0auto

import android.content.Context
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.support.v4.media.MediaBrowserCompat
import android.support.v4.media.MediaDescriptionCompat
import androidx.media.MediaBrowserServiceCompat
import org.json.JSONArray
import org.json.JSONObject

/**
 * Shared state between the JS-facing [F7FIVE0AutoModule] and the
 * [F7FIVE0BrowserService] that Android Auto binds to.
 *
 * - The root categories are native and static, so a head unit always sees the
 *   browse tree (Home, Recently Played, Mixes, Albums, Artists, Downloads).
 * - Children of a category come from JS (it owns the API client and the
 *   download list). They are cached in SharedPreferences so the car can browse
 *   the last known tree even before JS answers, then refreshed.
 * - Transport commands from the car are forwarded to JS, which drives
 *   react-native-track-player; JS mirrors playback state back via [setState].
 */
internal object AutoBridge {
  const val ROOT_ID = "__root__"
  private const val PREFS = "f7five0_auto"
  private const val PENDING_TIMEOUT_MS = 8000L

  @Volatile var module: F7FIVE0AutoModule? = null
  @Volatile var service: F7FIVE0BrowserService? = null
  @Volatile var lastState: JSONObject? = null

  private val main = Handler(Looper.getMainLooper())
  private val pending =
    HashMap<String, MutableList<MediaBrowserServiceCompat.Result<MutableList<MediaBrowserCompat.MediaItem>>>>()

  private val ROOTS = listOf(
    "home" to "Home",
    "recent" to "Recently Played",
    "mixes" to "Mixes",
    "albums" to "Albums",
    "artists" to "Artists",
    "downloads" to "Downloads",
  )

  fun rootItems(): MutableList<MediaBrowserCompat.MediaItem> =
    ROOTS.map { (id, title) -> item(id, title, null, null, true) }.toMutableList()

  private fun item(
    id: String,
    title: String,
    subtitle: String?,
    artUri: String?,
    browsable: Boolean,
  ): MediaBrowserCompat.MediaItem {
    val desc = MediaDescriptionCompat.Builder()
      .setMediaId(id)
      .setTitle(title)
      .apply {
        if (!subtitle.isNullOrEmpty()) setSubtitle(subtitle)
        if (!artUri.isNullOrEmpty()) setIconUri(Uri.parse(artUri))
      }
      .build()
    val flags = if (browsable) MediaBrowserCompat.MediaItem.FLAG_BROWSABLE else MediaBrowserCompat.MediaItem.FLAG_PLAYABLE
    return MediaBrowserCompat.MediaItem(desc, flags)
  }

  /** Parse `[{id,title,subtitle?,artUri?,browsable}]` from JS. Bad JSON -> empty. */
  fun parse(json: String): MutableList<MediaBrowserCompat.MediaItem> {
    val out = mutableListOf<MediaBrowserCompat.MediaItem>()
    try {
      val arr = JSONArray(json)
      for (i in 0 until arr.length()) {
        val o = arr.getJSONObject(i)
        val id = o.optString("id", "")
        if (id.isEmpty()) continue
        out.add(
          item(
            id,
            o.optString("title", ""),
            if (o.isNull("subtitle")) null else o.optString("subtitle"),
            if (o.isNull("artUri")) null else o.optString("artUri"),
            o.optBoolean("browsable", false),
          ),
        )
      }
    } catch (e: Exception) {
      // Leave the list empty; the car shows an empty folder rather than crashing.
    }
    return out
  }

  fun cached(ctx: Context, parentId: String): String? =
    ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("children:$parentId", null)

  @Synchronized
  fun addPending(
    parentId: String,
    result: MediaBrowserServiceCompat.Result<MutableList<MediaBrowserCompat.MediaItem>>,
  ) {
    pending.getOrPut(parentId) { mutableListOf() }.add(result)
    main.postDelayed({ expire(parentId) }, PENDING_TIMEOUT_MS)
  }

  @Synchronized
  private fun takePending(
    parentId: String,
  ): List<MediaBrowserServiceCompat.Result<MutableList<MediaBrowserCompat.MediaItem>>> =
    pending.remove(parentId) ?: emptyList()

  /** JS never answered: send whatever is cached (or nothing) so the car stops waiting. */
  private fun expire(parentId: String) {
    val waiting = takePending(parentId)
    if (waiting.isEmpty()) return
    val ctx = service ?: return
    val json = cached(ctx, parentId)
    for (r in waiting) r.sendResult(if (json != null) parse(json) else mutableListOf())
  }

  /** Children from JS: cache, answer anyone waiting, and tell the car if they changed. */
  fun setChildren(ctx: Context, parentId: String, json: String) {
    val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    val previous = prefs.getString("children:$parentId", null)
    prefs.edit().putString("children:$parentId", json).apply()
    val waiting = takePending(parentId)
    main.post {
      for (r in waiting) r.sendResult(parse(json))
      if (waiting.isEmpty() && previous != json) service?.notifyChildrenChanged(parentId)
    }
  }

  fun requestChildren(parentId: String) {
    module?.emit("onAutoLoadChildren", mapOf("parentId" to parentId))
  }

  fun command(name: String, mediaId: String? = null, positionMs: Long? = null) {
    module?.emit(
      "onAutoCommand",
      mapOf("command" to name, "mediaId" to mediaId, "positionMs" to positionMs?.toDouble()),
    )
  }

  /** Playback state mirrored from JS (react-native-track-player). */
  fun setState(json: String) {
    val o = try {
      JSONObject(json)
    } catch (e: Exception) {
      return
    }
    lastState = o
    main.post { service?.applyState(o) }
  }
}
