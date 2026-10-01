package expo.modules.f7five0auto

import android.net.Uri
import android.os.Bundle
import android.support.v4.media.MediaBrowserCompat
import android.support.v4.media.MediaMetadataCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.media.MediaBrowserServiceCompat
import org.json.JSONObject

/**
 * Android Auto media browser service (spec J, criterion 44).
 *
 * The head unit binds here, browses the tree served by [AutoBridge], and sends
 * transport commands to this service's media session. Commands are forwarded to
 * JS, which plays through react-native-track-player; JS mirrors the playback
 * state back so the car's now-playing screen stays in sync.
 */
class F7FIVE0BrowserService : MediaBrowserServiceCompat() {
  private var session: MediaSessionCompat? = null

  override fun onCreate() {
    super.onCreate()
    val s = MediaSessionCompat(this, "F7FIVE0-auto")
    s.setCallback(object : MediaSessionCompat.Callback() {
      override fun onPlay() = AutoBridge.command("play")
      override fun onPause() = AutoBridge.command("pause")
      override fun onStop() = AutoBridge.command("stop")
      override fun onSkipToNext() = AutoBridge.command("next")
      override fun onSkipToPrevious() = AutoBridge.command("previous")
      override fun onSeekTo(pos: Long) = AutoBridge.command("seek", null, pos)
      override fun onPlayFromMediaId(mediaId: String?, extras: Bundle?) =
        AutoBridge.command("playFromMediaId", mediaId)
    })
    s.setPlaybackState(
      PlaybackStateCompat.Builder()
        .setActions(ACTIONS)
        .setState(PlaybackStateCompat.STATE_NONE, 0L, 1f)
        .build(),
    )
    s.isActive = true
    session = s
    sessionToken = s.sessionToken
    AutoBridge.service = this
    AutoBridge.lastState?.let { applyState(it) }
  }

  override fun onDestroy() {
    if (AutoBridge.service === this) AutoBridge.service = null
    session?.isActive = false
    session?.release()
    session = null
    super.onDestroy()
  }

  override fun onGetRoot(
    clientPackageName: String,
    clientUid: Int,
    rootHints: Bundle?,
  ): MediaBrowserServiceCompat.BrowserRoot = MediaBrowserServiceCompat.BrowserRoot(AutoBridge.ROOT_ID, null)

  override fun onLoadChildren(
    parentId: String,
    result: MediaBrowserServiceCompat.Result<MutableList<MediaBrowserCompat.MediaItem>>,
  ) {
    if (parentId == AutoBridge.ROOT_ID) {
      result.sendResult(AutoBridge.rootItems())
      return
    }
    val cached = AutoBridge.cached(this, parentId)
    if (cached != null) {
      result.sendResult(AutoBridge.parse(cached))
      AutoBridge.requestChildren(parentId)
      return
    }
    if (AutoBridge.module == null) {
      // App JS isn't running and nothing is cached yet.
      result.sendResult(mutableListOf())
      return
    }
    result.detach()
    AutoBridge.addPending(parentId, result)
    AutoBridge.requestChildren(parentId)
  }

  /** Apply `{state, positionMs, durationMs, title, artist, album, artUri}` from JS. */
  fun applyState(o: JSONObject) {
    val s = session ?: return
    val state = when (o.optString("state", "none")) {
      "playing" -> PlaybackStateCompat.STATE_PLAYING
      "paused" -> PlaybackStateCompat.STATE_PAUSED
      "buffering", "loading" -> PlaybackStateCompat.STATE_BUFFERING
      "stopped", "ended" -> PlaybackStateCompat.STATE_STOPPED
      "error" -> PlaybackStateCompat.STATE_ERROR
      else -> PlaybackStateCompat.STATE_NONE
    }
    val speed = if (state == PlaybackStateCompat.STATE_PLAYING) 1f else 0f
    s.setPlaybackState(
      PlaybackStateCompat.Builder()
        .setActions(ACTIONS)
        .setState(state, o.optLong("positionMs", 0L), speed)
        .build(),
    )
    val meta = MediaMetadataCompat.Builder()
      .putString(MediaMetadataCompat.METADATA_KEY_TITLE, o.optString("title", ""))
      .putString(MediaMetadataCompat.METADATA_KEY_ARTIST, o.optString("artist", ""))
      .putString(MediaMetadataCompat.METADATA_KEY_ALBUM, o.optString("album", ""))
      .putLong(MediaMetadataCompat.METADATA_KEY_DURATION, o.optLong("durationMs", 0L))
    val art = o.optString("artUri", "")
    if (art.isNotEmpty()) {
      meta.putString(MediaMetadataCompat.METADATA_KEY_ALBUM_ART_URI, art)
      meta.putString(MediaMetadataCompat.METADATA_KEY_DISPLAY_ICON_URI, Uri.parse(art).toString())
    }
    s.setMetadata(meta.build())
  }

  companion object {
    private const val ACTIONS =
      PlaybackStateCompat.ACTION_PLAY or
        PlaybackStateCompat.ACTION_PAUSE or
        PlaybackStateCompat.ACTION_PLAY_PAUSE or
        PlaybackStateCompat.ACTION_STOP or
        PlaybackStateCompat.ACTION_SKIP_TO_NEXT or
        PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS or
        PlaybackStateCompat.ACTION_SEEK_TO or
        PlaybackStateCompat.ACTION_PLAY_FROM_MEDIA_ID
  }
}
