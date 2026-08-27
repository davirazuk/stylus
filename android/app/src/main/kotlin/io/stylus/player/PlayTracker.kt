package io.stylus.player

import android.content.Context
import android.content.SharedPreferences

/**
 * Local play history tracker — SharedPreferences only.
 * Scrobbling is handled externally by Pano Scrobbler via MediaSession,
 * so this class does NOT write to /sdcard/stylus-scrobbles.tsv.
 */
object PlayTracker {

    private const val COOLDOWN_MS = 30_000L  // 30s cooldown, same as PC

    private var lastPlayedKey: String = ""
    private var lastPlayedAt: Long = 0L
    private var _appContext: Context? = null

    fun init(ctx: Context) {
        _appContext = ctx.applicationContext
    }

    /**
     * Record a play. Cooldown prevents duplicate entries.
     */
    fun record(album: Library.Album, prefs: SharedPreferences) {
        val now = System.currentTimeMillis()
        val key = "${album.artist}|${album.name}"

        // Cooldown check
        if (key == lastPlayedKey && (now - lastPlayedAt) < COOLDOWN_MS) return

        lastPlayedKey = key
        lastPlayedAt = now

        // Update SharedPreferences for local stats (recently played, play count)
        prefs.edit()
            .putLong("played_${album.id}", now)
            .putInt("playcount_${album.id}", (prefs.getInt("playcount_${album.id}", 0)) + 1)
            .apply()
    }

    fun playCount(albumId: Long, prefs: SharedPreferences): Int =
        prefs.getInt("playcount_$albumId", 0)

    fun lastPlayed(albumId: Long, prefs: SharedPreferences): Long =
        prefs.getLong("played_$albumId", 0L)

    fun wasRecent(albumId: Long, prefs: SharedPreferences, days: Int = 7): Boolean {
        val last = lastPlayed(albumId, prefs)
        return last > 0 && (System.currentTimeMillis() - last) < days * 24 * 60 * 60 * 1000L
    }
}
