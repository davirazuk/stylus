package io.stylus.player

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.audiofx.BassBoost
import android.media.audiofx.Equalizer
import android.media.audiofx.Virtualizer
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.media.MediaMetadata
import android.os.Build
import android.util.Log
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer

/**
 * Bit-perfect player: desliga o que a Samsung pendura no caminho.
 *
 * O sistema equaliza depois do app: Dolby Atmos, Adapt Sound e EQ global são
 * efeitos no MIX de saída, não na sessão do app. Desligá-los na sessão já
 * resolve a maior parte do "grave inchado / palco fechado" relatado, e quando
 * o HAL aceita DIRECT o áudio nem passa pelo mixer — é o único ponto onde é
 * realmente bit-perfect (igual UAPP/Hiby fazem via driver USB exclusivo).
 */
class BitPerfectPlayer(private val ctx: Context) {

    var onTrackChange: ((index: Int) -> Unit)? = null
    var onPlaybackEnd: (() -> Unit)? = null

    private var session: MediaSession? = null
    private var metaTitle: String? = null
    private var metaArtist: String? = null
    private var metaAlbum: String? = null
    private var metaDuration: Long = 0L

    val exo: ExoPlayer = ExoPlayer.Builder(ctx, StylusRenderersFactory(ctx))
        .setAudioAttributes(
            androidx.media3.common.AudioAttributes.Builder()
                .setUsage(C.USAGE_MEDIA)
                .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
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
                override fun onPlayWhenReadyChanged(ready: Boolean, reason: Int) {
                    updateSession()
                }
                override fun onAudioSessionIdChanged(audioSessionId: Int) {
                    if (audioSessionId != C.AUDIO_SESSION_ID_UNSET) {
                        disableSystemEffects(audioSessionId)
                        try {
                            val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                            am.setParameters("dolby_enabled=false")
                            am.setParameters("DA_enabled=false")
                            am.setParameters("surround_enabled=false")
                            am.setParameters("DA_surround_enabled=false")
                            am.setParameters("audio_param_spatializer_enabled=false")
                            if (Build.VERSION.SDK_INT >= 32) {
                                try {
                                    @Suppress("DEPRECATION")
                                    am.setParameters("spatializer_enabled=false")
                                } catch (_: Exception) {}
                            }
                        } catch (_: Exception) {}
                        Log.i("BitPerfect", "audioSession=$audioSessionId")
                    }
                }
            })
        }

    init {
        initSession()
        detectUsbDac()
        registerUsbReceiver()
    }

    // ── USB DAC detection ──────────────────────────────────────────────

    private var usbDeviceId: Int = -1
    private var usbReceiver: BroadcastReceiver? = null

    private fun findUsbDac(): AudioDeviceInfo? {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        return am.getDevices(AudioManager.GET_DEVICES_OUTPUTS).firstOrNull {
            it.type == AudioDeviceInfo.TYPE_USB_DEVICE ||
                    it.type == AudioDeviceInfo.TYPE_USB_HEADSET
        }
    }

    private fun detectUsbDac() {
        val usb = findUsbDac()
        if (usb != null) {
            val rates = usb.sampleRates?.toList()?.filter { it > 0 }?.sortedDescending()
            Log.i("BitPerfect", "USB DAC: ${usb.productName} — rates=${rates?.joinToString()}Hz, id=${usb.id}")
            usbDeviceId = usb.id
        } else {
            val gone = usbDeviceId
            usbDeviceId = -1
            if (gone != -1) Log.i("BitPerfect", "USB DAC disconnected — back to default sink")
        }
    }

    private fun registerUsbReceiver() {
        val filter = IntentFilter().apply {
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        usbReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                detectUsbDac()
            }
        }
        ctx.registerReceiver(usbReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
    }

    private fun disableSystemEffects(sessionId: Int) {
        try {
            val eq = Equalizer(0, sessionId)
            if (eq.enabled) eq.enabled = false
            eq.release()
        } catch (e: Exception) { Log.d("BitPerfect", "EQ $e") }
        try {
            val bb = BassBoost(0, sessionId)
            if (bb.enabled) bb.enabled = false
            bb.release()
        } catch (e: Exception) { Log.d("BitPerfect", "BB $e") }
        try {
            val virt = Virtualizer(0, sessionId)
            if (virt.enabled) virt.enabled = false
            virt.release()
        } catch (e: Exception) { Log.d("BitPerfect", "virt $e") }
        // DynamicsProcessing / LoudnessEnhancer deixados de lado no caminho 1.2.1
        // são FX opcionais; o principal (EQ/Bass/Virtualizer) já cobre o Dolby.
    }

    fun prepareAlbum(uris: List<android.net.Uri>, startIndex: Int = 0, startMs: Long = 0) {
        exo.setMediaItems(uris.map { MediaItem.fromUri(it) }, startIndex, startMs)
        exo.prepare()
    }

    fun play() { exo.playWhenReady = true }
    fun pause() { exo.playWhenReady = false; exo.pause() }
    fun togglePlayPause() { if (exo.isPlaying) pause() else play() }

    val isPlaying get() = exo.isPlaying
    val currentPosition get() = exo.currentPosition
    val duration get() = exo.duration
    val currentTrackIndex get() = exo.currentMediaItemIndex
    val trackCount get() = exo.mediaItemCount

    fun skipToNext() { if (exo.currentMediaItemIndex < exo.mediaItemCount - 1) exo.seekToNext() }
    fun skipToPrev() {
        // Restart current track if >3s in, otherwise go to previous
        if (exo.currentPosition > 3000) {
            exo.seekTo(0)
        } else if (exo.currentMediaItemIndex > 0) {
            exo.seekToPrevious()
        }
    }

    var shuffleMode = false
    var repeatMode = Player.REPEAT_MODE_OFF  // OFF=0, ONE=1, ALL=2

    fun toggleShuffle() {
        shuffleMode = !shuffleMode
        exo.shuffleModeEnabled = shuffleMode
    }

    fun toggleRepeat() {
        repeatMode = when (repeatMode) {
            Player.REPEAT_MODE_OFF -> Player.REPEAT_MODE_ONE
            Player.REPEAT_MODE_ONE -> Player.REPEAT_MODE_ALL
            else -> Player.REPEAT_MODE_OFF
        }
        exo.repeatMode = repeatMode
    }

    fun initSession() {
        if (session != null) return
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
        updateSession()
    }

    /** Pano Scrobbler / notification: call on each track change with track metadata */
    fun setTrackInfo(title: String?, artist: String?, album: String?, durationMs: Long) {
        metaTitle = title
        metaArtist = artist
        metaAlbum = album
        metaDuration = durationMs
        updateSession()
    }

    private fun updateSession() {
        val s = session ?: return
        // Playback state
        val state = PlaybackState.Builder()
            .setActions(
                PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or
                    PlaybackState.ACTION_SKIP_TO_NEXT or PlaybackState.ACTION_SKIP_TO_PREVIOUS or
                    PlaybackState.ACTION_SEEK_TO or PlaybackState.ACTION_STOP
            )
            .setState(
                if (exo.isPlaying) PlaybackState.STATE_PLAYING else PlaybackState.STATE_PAUSED,
                exo.currentPosition, 1.0f
            )
            .build()
        s.setPlaybackState(state)
        // Metadata — Pano Scrobbler reads these to scrobble
        val md = MediaMetadata.Builder()
            .putString(MediaMetadata.METADATA_KEY_TITLE, metaTitle)
            .putString(MediaMetadata.METADATA_KEY_ARTIST, metaArtist)
            .putString(MediaMetadata.METADATA_KEY_ALBUM, metaAlbum)
            .putLong(MediaMetadata.METADATA_KEY_DURATION, metaDuration)
            .putString(MediaMetadata.METADATA_KEY_DISPLAY_TITLE, metaTitle)
            .putString(MediaMetadata.METADATA_KEY_DISPLAY_SUBTITLE, metaArtist)
            .putString(MediaMetadata.METADATA_KEY_DISPLAY_DESCRIPTION, metaAlbum)
            .build()
        s.setMetadata(md)
        // Notify service to update its foreground notification with MediaStyle
        onMetadataChanged?.invoke(s.sessionToken, metaTitle ?: "", metaArtist ?: "", metaAlbum ?: "", exo.isPlaying)
    }

    /** Callback to update the foreground service notification — set by the service */
    var onMetadataChanged: ((token: android.media.session.MediaSession.Token, title: String, artist: String, album: String, playing: Boolean) -> Unit)? = null

    // ── duas funções saíram daqui ──────────────────────────────────────
    //
    // `onUsbDacAttached(device)`: abria o DAC pelo UsbManager e RECLAMAVA a
    // interface de áudio com `claimInterface(intf, true)` — o `true` é
    // "force", que arranca o driver do sistema de cima do aparelho. Ela
    // soltava tudo no `finally` e o único resultado era uma linha de log:
    // um nada perigoso, porque arrancar o driver no meio de uma faixa é
    // exatamente o tipo de coisa que corta o som. E ninguém a chamava — o
    // que o receptor de USB chama é o `detectUsbDac()`, que é a metade útil
    // (acha o DAC e anota as taxas que ele aceita) e continua aqui.
    //
    // `isWiredHeadsetConnected()`: nada perguntava, e nada perguntava a
    // mesma coisa por outro caminho. Saiu como estado morto sai.

    fun release() {
        try { usbReceiver?.let { ctx.unregisterReceiver(it) } } catch (_: Exception) {}
        session?.release()
        exo.release()
    }
}
