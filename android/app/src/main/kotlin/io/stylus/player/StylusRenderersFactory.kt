package io.stylus.player

import android.content.Context
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.audio.AudioSink

/**
 * RenderersFactory que decide o AudioSink em camadas:
 *
 * 1. DAC USB física + permissão + sem chamada ativa -> UsbDacSink (caminho
 *    UAPP: bulkTransfer direto no endpoint, sem mixer). É o bit-perfect real.
 * 2. Qualquer outra situação -> AudioTrack padrão (super).
 *
 * A primeira tentativa (AAudio exclusive via NativeAudioSink) pegava a saída
 * do telefone inteiro e tocava por cima de uma chamada em curso. Por isso a
 * factory NUNCA força um sink exclusivo: sem DAC físico, o som é o padrão.
 */
class StylusRenderersFactory(context: Context) : DefaultRenderersFactory(context) {

    override fun buildAudioSink(
        context: Context,
        enableFloatOutput: Boolean,
        enableAudioTrackPlaybackParams: Boolean
    ): AudioSink {
        val dacSink = UsbDacSink.tryOpen(context)
        if (dacSink != null) return dacSink
        // super pode declarar null (AudioSink? no Media3) se uma fábrica
        // customizada for configurada; o padrão nunca devolve null. Defensivo:
        return super.buildAudioSink(context, enableFloatOutput, enableAudioTrackPlaybackParams)
            ?: androidx.media3.exoplayer.audio.DefaultAudioSink.Builder(context).build()
    }
}