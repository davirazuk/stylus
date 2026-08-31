package io.stylus.player

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Testes de host JVM (sem telefone): a conversão PCM é a parte que decide se o
 * som chega inteiro no HAL. Roda com `./gradlew :app:testDebugUnitTest`.
 */
class PcmConvertTest {

    private fun shortBuf(vararg s: Short): ByteBuffer {
        val b = ByteBuffer.allocate(s.size * 2).order(ByteOrder.nativeOrder())
        s.forEach { b.putShort(it) }
        b.flip()
        return b
    }

    private fun floatBuf(vararg f: Float): ByteBuffer {
        val b = ByteBuffer.allocate(f.size * 4).order(ByteOrder.nativeOrder())
        f.forEach { b.putFloat(it) }
        b.flip()
        return b
    }

    @Test
    fun `i16 arquivo para float stream mantem valor`() {
        val buf = shortBuf(16384, -16384)
        val out = PcmConvert.toFloat(buf, 1, fileIsFloat = false)!!
        assertEquals(16384 / 32768f, out[0], 1e-6f)
        assertEquals(-16384 / 32768f, out[1], 1e-6f)
        assertEquals(0, buf.remaining())
    }

    @Test
    fun `float arquivo para i16 stream arredonda e corta`() {
        val buf = floatBuf(1.0f, -1.0f, 0.5f)
        val out = PcmConvert.toShort(buf, 1, fileIsFloat = true)!!
        assertEquals(32767.toShort(), out[0])
        assertEquals((-32767).toShort(), out[1]) // escala por 32767 mantém -1.0 -> -32767
        assertEquals((0.5f * 32767f).toInt().toShort(), out[2])
    }

    @Test
    fun `i16 para i16 passa limpo`() {
        val buf = shortBuf(1234, -5678)
        val out = PcmConvert.toShort(buf, 1, fileIsFloat = false)!!
        assertArrayEquals(shortArrayOf(1234, -5678), out)
    }

    @Test
    fun `float para float passa limpo`() {
        val buf = floatBuf(0.25f, -0.75f)
        val out = PcmConvert.toFloat(buf, 1, fileIsFloat = true)!!
        assertArrayEquals(floatArrayOf(0.25f, -0.75f), out, 0f)
    }

    @Test
    fun `frames por buffer nao conta meia frame`() {
        val buf = shortBuf(1, 2, 3) // 3 amostras mono i16
        assertEquals(3, PcmConvert.frameCount(buf, fileIsFloat = false, channels = 1))
        // estéreo: 3 amostras não fecha frame completo de 2 canais
        assertEquals(1, PcmConvert.frameCount(buf, fileIsFloat = false, channels = 2))
    }

    @Test
    fun `buffer vazio nao retorna nada`() {
        val b = ByteBuffer.allocate(0)
        assertNull(PcmConvert.toFloat(b, 1, fileIsFloat = false))
        assertNull(PcmConvert.toShort(b, 1, fileIsFloat = false))
    }

    @Test
    fun `stereo interleave mantem ordem de canais`() {
        val buf = shortBuf(100, 200, 300, 400)
        val out = PcmConvert.toShort(buf, 2, fileIsFloat = false)!!
        assertArrayEquals(shortArrayOf(100, 200, 300, 400), out)
    }
}