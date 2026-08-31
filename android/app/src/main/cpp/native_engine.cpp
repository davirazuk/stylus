// Engineer the native audio path. Sintoma: o ExoPlayer tocava pelo AudioTrack
// do sistema — a reamostragem e os efeitos do MixPath eram do sistema, não do
// app, e nada que o app fizesse evitava. A saída é a mesma do UAPP: abrir o
// AAudio EXCLUSIVO na taxa do arquivo e escrever float cru — sem mixer.
// Fallback honesto: se o HAL não aceitar exclusive/float/taxa, cai para
// shared/i16 e LOGGA o que conseguiu (igual stylus-audio no desktop reporta).
#include <jni.h>
#include <oboe/Oboe.h>
#include <android/log.h>
#include <cstring>

#define TAG "StylusNative"
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)

struct Engine {
    oboe::AudioStream *stream = nullptr;
    int64_t framesWrittenTotal = 0;  // em amostras de saída (contados pelo app)
    int64_t framesReadTotal = 0;     // ground truth do HAL (framesRead)
};

static inline long atomicVoiceCountUpdated = 0;  // placeholder para debug

// open(sampleRate, channels, isFloat, preferExclusive) -> handle (0 = falha)
extern "C" JNIEXPORT jlong JNICALL
Java_io_stylus_player_StylusNative_open(
        JNIEnv *env, jclass, jint sampleRate, jint channels, jboolean isFloat, jboolean preferExclusive) {
    auto *e = new Engine();

    // Tenta em ordem até achar caminho que o HAL aceita:
    //  1. float+exclusive  2. i16+exclusive  3. float+shared  4. i16+shared
    const int tries = preferExclusive ? 4 : 2;
    for (int attempt = 0; attempt < tries; attempt++) {
        bool wantFloat = (attempt == 0 || attempt == 2);
        bool wantXcl   = (attempt == 0 || attempt == 1) && preferExclusive;
        if (!isFloat && wantFloat && attempt < 2) continue;  // caller só quer i16: pula float

        oboe::AudioStreamBuilder builder;
        builder.setDirection(oboe::Direction::Output);
        builder.setPerformanceMode(oboe::PerformanceMode::LowLatency);
        builder.setSharingMode(wantXcl ? oboe::SharingMode::Exclusive
                                       : oboe::SharingMode::Shared);
        builder.setFormat(wantFloat ? oboe::AudioFormat::Float
                                    : oboe::AudioFormat::I16);
        builder.setSampleRate(sampleRate);
        builder.setChannelCount(channels);
        builder.setFramesPerCallback(0);  // push mode

        oboe::Result result = builder.openStream(&e->stream);
        if (result == oboe::Result::OK) {
            const char *fmt = (e->stream->getFormat() == oboe::AudioFormat::Float) ? "float" : "i16";
            oboe::SharingMode got = e->stream->getSharingMode();
            const char *share = (got == oboe::SharingMode::Exclusive) ? "exclusive" : "shared";
            int actualRate = e->stream->getSampleRate();
            int burst = e->stream->getFramesPerBurst();
            if (actualRate != sampleRate) {
                LOGI("aaudio: rate %d requested -> %d got (RESAMPLED) %s %s", sampleRate, actualRate, fmt, share);
            } else {
                LOGI("aaudio: rate %d exclusive, %s %s", actualRate, fmt, share);
            }
            // Buffer para aguentar um latch do Renderer sem estourar
            e->stream->setBufferSizeInFrames(burst * 4);
            LOGI("stylus native ok: rate=%d ch=%d fmt=%s share=%s burst=%d",
                 actualRate, channels, fmt, share, burst);
            return reinterpret_cast<jlong>(e);
        }
        LOGE("stylus native open attempt %d (%s %s rate=%d): %s", attempt,
             wantFloat ? "float" : "i16", wantXcl ? "exclusive" : "shared", sampleRate,
             oboe::convertToText(result));
        e->stream = nullptr;
    }
    delete e;
    return 0;
}

// writeF(handle, floatArray, frames) -> frames realmente aceitos
extern "C" JNIEXPORT jint JNICALL
Java_io_stylus_player_StylusNative_writeF(JNIEnv *env, jclass, jlong h, jfloatArray data, jint frames) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e || !e->stream) return 0;
    jfloat *src = env->GetFloatArrayElements(data, nullptr);
    oboe::ResultWithValue<int32_t> n = e->stream->write(src, frames, 0);
    env->ReleaseFloatArrayElements(data, src, JNI_ABORT);
    if (n.error() != oboe::Result::OK) return 0;
    int32_t written = n.value();
    e->framesWrittenTotal += written;
    return written;
}

// writeS(handle, shortArray, frames) -> frames realmente aceitos
extern "C" JNIEXPORT jint JNICALL
Java_io_stylus_player_StylusNative_writeS(JNIEnv *env, jclass, jlong h, jshortArray data, jint frames) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e || !e->stream) return 0;
    jshort *src = env->GetShortArrayElements(data, nullptr);
    oboe::ResultWithValue<int32_t> n = e->stream->write(src, frames, 0);
    env->ReleaseShortArrayElements(data, src, JNI_ABORT);
    if (n.error() != oboe::Result::OK) return 0;
    int32_t written = n.value();
    e->framesWrittenTotal += written;
    return written;
}

extern "C" JNIEXPORT jint JNICALL
Java_io_stylus_player_StylusNative_start(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e || !e->stream) return 0;
    return (e->stream->start() == oboe::Result::OK);
}

extern "C" JNIEXPORT jint JNICALL
Java_io_stylus_player_StylusNative_pause(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e || !e->stream) return 0;
    return (e->stream->pause() == oboe::Result::OK);
}

// flush: para, descarta o que sobrou e volta pronto para escrever de novo.
extern "C" JNIEXPORT jint JNICALL
Java_io_stylus_player_StylusNative_flush(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e || !e->stream) return 0;
    oboe::Result r = e->stream->requestStop();
    if (r == oboe::Result::OK) {
        e->stream->waitForStateChange(oboe::StreamState::Stopping, nullptr, 200 * oboe::kNanosPerMillisecond);
    }
    // posição zera no próximo start: AAudio conta tudo desde o open, mas o
    // Media3 chamará flush em seek/discontinuidade e reescreverá do início.
    return (r == oboe::Result::OK);
}

extern "C" JNIEXPORT jint JNICALL
Java_io_stylus_player_StylusNative_stop(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e || !e->stream) return 0;
    return (e->stream->stop() == oboe::Result::OK);
}

extern "C" JNIEXPORT jlong JNICALL
Java_io_stylus_player_StylusNative_framesRead(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e || !e->stream) return 0;
    int64_t fr = e->stream->getFramesRead();
    return (fr < 0) ? 0 : fr;
}

extern "C" JNIEXPORT jint JNICALL
Java_io_stylus_player_StylusNative_sampleRate(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e || !e->stream) return 0;
    return e->stream->getSampleRate();
}

extern "C" JNIEXPORT jint JNICALL
Java_io_stylus_player_StylusNative_isExclusive(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e || !e->stream) return 0;
    return (e->stream->getSharingMode() == oboe::SharingMode::Exclusive);
}

extern "C" JNIEXPORT jint JNICALL
Java_io_stylus_player_StylusNative_isFloatFormat(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e || !e->stream) return 0;
    return (e->stream->getFormat() == oboe::AudioFormat::Float);
}

extern "C" JNIEXPORT void JNICALL
Java_io_stylus_player_StylusNative_close(JNIEnv *, jclass, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e) return;
    if (e->stream) { e->stream->close(); e->stream = nullptr; }
    delete e;
}

// isFloatSupported(): o sistema AO MENOS abre float? Usado para decidir qual
// encoding pedir ao Media3 antes de abrir a stream.
extern "C" JNIEXPORT jboolean JNICALL
Java_io_stylus_player_StylusNative_isFloatSupported(JNIEnv *, jclass, jint sampleRate, jint channels) {
    oboe::AudioStreamBuilder b;
    b.setDirection(oboe::Direction::Output);
    b.setPerformanceMode(oboe::PerformanceMode::LowLatency);
    b.setSharingMode(oboe::SharingMode::Shared);
    b.setFormat(oboe::AudioFormat::Float);
    b.setSampleRate(sampleRate);
    b.setChannelCount(channels);
    oboe::AudioStream *s = nullptr;
    oboe::Result r = b.openStream(&s);
    if (r == oboe::Result::OK && s) {
        // se abriu mas veio como I16, era do HAL ignorando o pedido
        bool ok = (s->getFormat() == oboe::AudioFormat::Float);
        s->close();
        return ok ? JNI_TRUE : JNI_FALSE;
    }
    return JNI_FALSE;
}