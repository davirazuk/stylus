package io.stylus.player

/**
 * Ligação JNI com o engenho nativo (app/src/main/cpp/native_engine.cpp).
 * A stream é Oboe/AAudio: exclusive quando o HAL aceita, taxa do arquivo,
 * float. Tudo é push — quem manda é o NativeAudioSink, sem callback thread.
 */
object StylusNative {
    init { System.loadLibrary("stylus_native") }

    /** @JvmStatic: vira método estático — é o que a JNI (jclass) espera. */
    @JvmStatic external fun open(sampleRate: Int, channels: Int, isFloat: Boolean, preferExclusive: Boolean): Long
    @JvmStatic external fun writeF(handle: Long, data: FloatArray, frames: Int): Int
    @JvmStatic external fun writeS(handle: Long, data: ShortArray, frames: Int): Int
    @JvmStatic external fun start(handle: Long): Int
    @JvmStatic external fun pause(handle: Long): Int
    @JvmStatic external fun flush(handle: Long): Int
    @JvmStatic external fun stop(handle: Long): Int
    @JvmStatic external fun framesRead(handle: Long): Long
    @JvmStatic external fun sampleRate(handle: Long): Int
    @JvmStatic external fun isExclusive(handle: Long): Int
    @JvmStatic external fun isFloatFormat(handle: Long): Int
    @JvmStatic external fun close(handle: Long)

    /** Testa se o HAL abre float (p/ o decoder escolher o encoding certo). */
    @JvmStatic external fun isFloatSupported(sampleRate: Int, channels: Int): Boolean
}