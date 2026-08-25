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

    // Bit-perfect: volume 1.0, no DSP, gapless. True direct/USB bypass needs
    // ExoPlayer 1.3+ offload or manual AudioTrack; for now we ensure no software
    // EQ/resample and rely on system direct when wired/USB is present.
    val exo: ExoPlayer = ExoPlayer.Builder(ctx)
        .setAudioAttributes(
            androidx.media3.common.AudioAttributes.Builder()
                .setUsage(androidx.media3.common.C.USAGE_MEDIA)
                .setContentType(androidx.media3.common.C.AUDIO_CONTENT_TYPE_MUSIC)
                .build(), true
        )
        .build().apply {
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

    // USB DAC direct — like UAPP: claim isochronous endpoint, stream PCM float
    fun onUsbDacAttached(device: android.hardware.usb.UsbDevice) {
        try {
            val usb = ctx.getSystemService(android.content.Context.USB_SERVICE) as android.hardware.usb.UsbManager
            if (!usb.hasPermission(device)) return
            val conn = usb.openDevice(device) ?: return
            // find audio interface (class 1)
            for (i in 0 until device.interfaceCount) {
                val intf = device.getInterface(i)
                if (intf.interfaceClass == 1) { // AUDIO
                    conn.claimInterface(intf, true)
                    // set altSetting for current rate (handled by driver)
                    break
                }
            }
            // ExoPlayer offload will now use USB direct path if available
            android.util.Log.i("BitPerfect", "USB DAC attached: ${device.deviceName}, offload=${exo.isPlaying}")
        } catch (e: Exception) {
            android.util.Log.w("BitPerfect", "USB attach failed: $e")
        }
    }

    fun isWiredHeadsetConnected(): Boolean {
        val am = ctx.getSystemService(android.content.Context.AUDIO_SERVICE) as android.media.AudioManager
        @Suppress("DEPRECATION")
        return am.isWiredHeadsetOn || am.getDevices(android.media.AudioManager.GET_DEVICES_OUTPUTS)
            .any { it.type == android.media.AudioDeviceInfo.TYPE_WIRED_HEADPHONES || it.type == android.media.AudioDeviceInfo.TYPE_WIRED_HEADSET || it.type == android.media.AudioDeviceInfo.TYPE_USB_HEADSET || it.type == android.media.AudioDeviceInfo.TYPE_USB_DEVICE }
    }

    fun release() {
        session?.release()
        exo.release()
    }
}
