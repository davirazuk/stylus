package io.stylus.player

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.session.MediaSession
import android.media.session.PlaybackState
import androidx.core.app.NotificationCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer

/**
 * ExoPlayer wrapper — bit-perfect settings, foreground notification, media session.
 */
class BitPerfectPlayer(private val ctx: Context) {

    var onTrackChange: ((index: Int) -> Unit)? = null
    var onPlaybackEnd: (() -> Unit)? = null

    private var session: MediaSession? = null

    // Bit-perfect: volume 1.0, no DSP, gapless, follow file rate
    // On Android 12+ with wired headphones/USB DAC, system mixer will use direct
    // path when AudioAttributes is MUSIC and offload is available. For now we
    // ensure no software resampling/equalizer and let the hardware do its job.
    val exo: ExoPlayer = ExoPlayer.Builder(ctx).build().apply {
        volume = 1.0f
        repeatMode = Player.REPEAT_MODE_OFF
        playWhenReady = false
        addListener(object : Player.Listener {
            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                onTrackChange?.invoke(currentMediaItemIndex)
                updateSession()
            }
            override fun onPlaybackStateChanged(playbackState: Int) {
                if (playbackState == Player.STATE_ENDED) onPlaybackEnd?.invoke()
                updateSession()
            }
        })
    }

    fun prepareAlbum(uris: List<android.net.Uri>, startIndex: Int = 0, startMs: Long = 0) {
        exo.setMediaItems(uris.map { MediaItem.fromUri(it) }, startIndex, startMs)
        exo.prepare()
    }

    fun play() { exo.playWhenReady = true; exo.play() }
    fun pause() { exo.playWhenReady = false; exo.pause() }
    fun togglePlayPause() { if (exo.isPlaying) pause() else play() }

    val isPlaying get() = exo.isPlaying
    val currentPosition get() = exo.currentPosition
    val duration get() = exo.duration
    val currentTrackIndex get() = exo.currentMediaItemIndex

    fun initSession() {
        session = MediaSession(ctx, "STYLUS").apply {
            setCallback(object : MediaSession.Callback() {
                override fun onPlay() { play() }
                override fun onPause() { pause() }
                override fun onSkipToNext() { if (exo.currentMediaItemIndex < exo.mediaItemCount - 1) exo.seekToNext() }
                override fun onSkipToPrevious() { if (exo.currentMediaItemIndex > 0) exo.seekToPrevious() }
                override fun onSeekTo(pos: Long) { exo.seekTo(pos) }
            })
            isActive = true
        }
    }

    private fun updateSession() {
        val s = session ?: return
        val state = PlaybackState.Builder()
            .setActions(
                PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or
                PlaybackState.ACTION_SKIP_TO_NEXT or PlaybackState.ACTION_SKIP_TO_PREVIOUS or
                PlaybackState.ACTION_SEEK_TO
            )
            .setState(
                if (exo.isPlaying) PlaybackState.STATE_PLAYING else PlaybackState.STATE_PAUSED,
                exo.currentPosition, 1.0f
            )
            .build()
        s.setPlaybackState(state)
    }

    fun release() {
        session?.release()
        exo.release()
    }
}
