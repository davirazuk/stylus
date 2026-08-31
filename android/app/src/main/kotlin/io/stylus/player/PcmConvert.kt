package io.stylus.player

import androidx.media3.common.C
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Conversão PCM do arquivo (i16 ou float) para a caixa que o engenho abriu.
 * Isolada de JNI/hardware para poder ser testada no host JVM.
 *
 * Sintoma que originou: o HAL da Samsung abria a stream como i16 para um
 * FLAC i16, e como float para gravação — se o app assumisse a caixa do ARQUIVO
 * sem conferir a da STREAM, mandava float para uma stream i16 e invertia bytes
 * (chiado metálico). O conversor aqui segue o que a stream REAL aceita.
 */
object PcmConvert {

    // Quantos canais * bytes por frame, por caixa de arquivo.
    fun bytesPerFrame(fileIsFloat: Boolean, channels: Int): Int =
        channels * (if (fileIsFloat) 4 else 2)

    // Total de frames inteiros contidos no buffer restante.
    fun frameCount(buffer: ByteBuffer, fileIsFloat: Boolean, channels: Int): Int {
        val bytes = buffer.remaining()
        val bpf = bytesPerFrame(fileIsFloat, channels)
        if (bpf <= 0) return 0
        return bytes / bpf
    }

    // Converte o conteúdo restante de [buffer] para a caixa float da stream,
    // avançando o position do buffer até o limite. Retorna null se não houver
    // frame inteiro (caso em que o buffer é consumido igual).
    fun toFloat(buffer: ByteBuffer, channels: Int, fileIsFloat: Boolean): FloatArray? {
        buffer.order(ByteOrder.nativeOrder())
        val frames = frameCount(buffer, fileIsFloat, channels)
        if (frames <= 0) { buffer.position(buffer.limit()); return null }
        val n = frames * channels
        val out = FloatArray(n)
        if (fileIsFloat) {
            buffer.asFloatBuffer().get(out)
        } else {
            val si = ShortArray(n)
            buffer.asShortBuffer().get(si)
            for (i in 0 until n) out[i] = si[i] / 32768f
        }
        buffer.position(buffer.limit())
        return out
    }

    // Converte o conteúdo restante de [buffer] para a caixa i16 da stream.
    fun toShort(buffer: ByteBuffer, channels: Int, fileIsFloat: Boolean): ShortArray? {
        buffer.order(ByteOrder.nativeOrder())
        val frames = frameCount(buffer, fileIsFloat, channels)
        if (frames <= 0) { buffer.position(buffer.limit()); return null }
        val n = frames * channels
        val out = ShortArray(n)
        if (fileIsFloat) {
            val fl = FloatArray(n)
            buffer.asFloatBuffer().get(fl)
            for (i in 0 until n) {
                val v = (fl[i] * 32767f).toInt().coerceIn(-32768, 32767)
                out[i] = v.toShort()
            }
        } else {
            buffer.asShortBuffer().get(out)
        }
        buffer.position(buffer.limit())
        return out
    }
}