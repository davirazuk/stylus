package io.stylus.player

import android.content.Context
import android.content.SharedPreferences
import android.os.Environment
import java.io.File

/**
 * Play history tracker — writes plays.tsv matching the PC format.
 * Format: timestamp\tartist\talbum\tpath
 *
 * Enables cross-platform shuffle forgetfulness and diary stats.
 * The sync agent (stylus-phone scrobbles) reads from /sdcard/stylus-scrobbles.tsv.
 */
object PlayTracker {

    private const val COOLDOWN_MS = 30_000L  // 30s cooldown, same as PC
    private const val PLAYS_FILE = "stylus-scrobbles.tsv"

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

        // Write to /sdcard/stylus-scrobbles.tsv for cross-platform sync
        try {
            val file = File(Environment.getExternalStorageDirectory(), PLAYS_FILE)
            val ts = (now / 1000).toInt()
            file.appendText("$ts\t${album.artist}\t${album.name}\tandroid:${album.id}\n")
        } catch (_: Exception) {}
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
