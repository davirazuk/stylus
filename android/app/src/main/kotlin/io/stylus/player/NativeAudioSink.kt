package io.stylus.player

import android.util.Log
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.PlaybackParameters
import androidx.media3.exoplayer.audio.AudioSink
import java.nio.ByteBuffer
import java.util.concurrent.atomic.AtomicReference
import androidx.media3.common.AudioAttributes
import androidx.media3.common.AuxEffectInfo

/**
 * AudioSink custom do Media3: o PCM sai do decodificador (FLAC etc.) e entra
 * AQUI — nunca no AudioTrack. O engenho nativo (Oboe/AAudio) abre a stream na
 * taxa do arquivo, exclusive quando o HAL aceita, e o float cru vai direto.
 *
 * Sintoma que matou o AudioTrack: o MixPath da Samsung reamostrava tudo para
 * 48k e pendurava Dolby/EQ depois do app. Não havia setParameters que saísse
 * disso — o mixer fica entre o app e o HAL. A única saída é não passar por ele.
 *
 * Fallbacks honestos (todos logados):
 *   - HAL sem exclusive  -> shared  (o app perde prioridade, o som segue certo)
 *   - HAL sem float      -> i16     (perfeito segue; só muda a caixa)
 *   - esse AudioSink é a porta de entrada do caminho USB DAC (bulk) quando o
 *     UsbDacSink estiver ativo — mesmo handleBuffer, sem mexer no renderer.
 */
class NativeAudioSink : AudioSink {

    private var listener: AudioSink.Listener? = null
    private var handle: Long = 0L
    private var sampleRate = 48000
    private var channels = 2
    private var isFloat = true
    private var started = false
    private var streamEnded = false
    private var playing = false
    private val position = java.util.concurrent.atomic.AtomicLong(0L) // frames consumidos p/ getCurrentPositionUs
    private var frameCount = 0L // frames CONTADOS pelo app desde o open (posição lógica)

    private val parameters = AtomicReference(PlaybackParameters.DEFAULT)
    private val audioAttributes = AtomicReference(AudioAttributes.DEFAULT)
    private var skipSilence = false

    override fun setListener(listener: AudioSink.Listener) { this.listener = listener }

    override fun supportsFormat(format: Format): Boolean {
        return format.sampleRate != Format.NO_VALUE && format.channelCount != Format.NO_VALUE
    }

    override fun getFormatSupport(format: Format) = AudioSink.SINK_FORMAT_SUPPORTED_DIRECTLY

    override fun getCurrentPositionUs(sourceEnded: Boolean): Long {
        // Usa framesRead do HAL (ground truth), senão os frames que aceitamos.
        if (handle == 0L) return position.get() * 1_000_000L / sampleRate
        val frames = StylusNative.framesRead(handle)
        if (frames > 0) position.set(frames)
        return position.get().coerceAtLeast(0L) * 1_000_000L / sampleRate
    }

    override fun configure(
        inputFormat: Format,
        specifiedBufferSizeUs: Int,
        outputChannels: IntArray?
    ) {
        sampleRate = inputFormat.sampleRate
        channels = outputChannels?.firstOrNull() ?: 2
        if (channels <= 0) channels = 2
        val enc = inputFormat.pcmEncoding
        val fileIsFloat = enc == C.ENCODING_PCM_FLOAT
        started = false
        streamEnded = false
        frameCount = 0L
        closeNative()
        handle = StylusNative.open(sampleRate, channels, fileIsFloat, true)
        if (handle == 0L) {
            Log.e("BitPerfect", "sink: AAudio open FALHOU em $sampleRate/ch$channels — sem som")
            val fmt = Format.Builder().setSampleRate(sampleRate).setChannelCount(channels).build()
            listener?.onAudioSinkError(
                AudioSink.InitializationException(
                    0, 1, 0, audioSessionId, fmt, false,
                    IllegalStateException("AAudio open failed: $sampleRate/$channels")
                )
            )
            return
        }
        // A caixa do HAL pode não ser a mesma do arquivo: seguimos o ACTUAL.
        isFloat = StylusNative.isFloatFormat(handle) == 1
        Log.i("BitPerfect", "sink: AAudio $sampleRate Hz ch$channels " +
            "fmt=${if (isFloat) "float" else "i16"} " +
            "exclusive=${StylusNative.isExclusive(handle) == 1}")
    }

    private var audioSessionId = 0

    private fun closeNative() {
        if (handle != 0L) { StylusNative.close(handle); handle = 0L }
    }

    override fun handleBuffer(buffer: ByteBuffer, presentationTimeUs: Long, encoding: Int): Boolean {
        if (handle == 0L) return true

        val fileIsFloat = encoding == C.ENCODING_PCM_FLOAT
        val frames = PcmConvert.frameCount(buffer, fileIsFloat, channels)
        if (frames <= 0) { buffer.position(buffer.limit()); return true }

        // AAudio só aceita write() com a stream startada — senão o primeiro
        // handleBuffer devolveria false para sempre e o renderer travaria.
        if (!started) { started = true; startInternal() }

        var done = 0
        if (isFloat) {
            val fl = PcmConvert.toFloat(buffer, channels, fileIsFloat) ?: return true
            while (done < frames) {
                val f = fl.copyOfRange(done * channels, frames * channels)
                val n = StylusNative.writeF(handle, f, f.size / channels)
                if (n <= 0) break
                done += n
                frameCount += n
                position.set(StylusNative.framesRead(handle))
            }
        } else {
            val si = PcmConvert.toShort(buffer, channels, fileIsFloat) ?: return true
            while (done < frames) {
                val s = si.copyOfRange(done * channels, frames * channels)
                val n = StylusNative.writeS(handle, s, s.size / channels)
                if (n <= 0) break
                done += n
                frameCount += n
                position.set(StylusNative.framesRead(handle))
            }
        }
        return done == frames
    }

    private fun startInternal() {
        if (handle != 0L) {
            if (StylusNative.start(handle) == 1) playing = true
        }
    }

    override fun play() { playing = true; if (handle != 0L) StylusNative.start(handle) }

    override fun handleDiscontinuity() { frameCount = 0L; position.set(0) }

    override fun playToEndOfStream() {
        // esvazia o backlog (na prática write já era síncrono)
        streamEnded = true
    }

    override fun isEnded() = streamEnded

    override fun hasPendingData() = (!streamEnded) && (frameCount - position.get() > 0)

    override fun setPlaybackParameters(playbackParameters: PlaybackParameters) {
        parameters.set(playbackParameters)
        // AAudio não faz pitch/speed — só aceitamos o padrão
        if (playbackParameters.speed != 1f || playbackParameters.pitch != 1f) {
            listener?.onAudioSinkError(
                IllegalArgumentException("AAudio bit-perfect: não faz speed/pitch")
            )
        }
    }
    override fun getPlaybackParameters() = parameters.get()

    override fun setSkipSilenceEnabled(enabled: Boolean) { skipSilence = enabled }
    override fun getSkipSilenceEnabled() = skipSilence

    override fun setAudioAttributes(audioAttributes: AudioAttributes) { this.audioAttributes.set(audioAttributes) }
    override fun getAudioAttributes() = audioAttributes.get()

    override fun setAudioSessionId(audioSessionId: Int) { this.audioSessionId = audioSessionId }
    override fun setAuxEffectInfo(auxEffectInfo: AuxEffectInfo) {}
    override fun enableTunnelingV21() {}
    override fun disableTunneling() {}

    override fun setVolume(volume: Float) {}

    override fun pause() {
        playing = false
        if (handle != 0L) StylusNative.pause(handle)
    }

    override fun flush() {
        frameCount = 0L
        position.set(0)
        streamEnded = false
        if (handle != 0L) { StylusNative.flush(handle); started = false; playing = false }
    }

    override fun reset() {
        closeNative()
        frameCount = 0L
        position.set(0)
        started = false
        playing = false
        streamEnded = false
    }
}