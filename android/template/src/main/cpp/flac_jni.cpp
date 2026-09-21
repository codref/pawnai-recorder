#include <android/log.h>
#include <jni.h>

#include <cstdint>
#include <string>
#include <vector>

#include "FLAC/stream_encoder.h"

#define LOG_TAG "PawnAI.Flac"
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

namespace {

constexpr int kBitsPerSample = 16;
constexpr unsigned kChannels = 1;
// libFLAC default is 5; 5 is a good size/CPU tradeoff for speech chunks.
constexpr unsigned kCompressionLevel = 5u;

jint throwIllegalState(JNIEnv *env, const char *message) {
    jclass cls = env->FindClass("java/lang/IllegalStateException");
    if (cls != nullptr) {
        env->ThrowNew(cls, message);
    }
    return JNI_ERR;
}

}  // namespace

extern "C" JNIEXPORT void JNICALL
Java_com_pawnai_recorder_audio_FlacEncoder_encodeMonoPcm16(
        JNIEnv *env,
        jclass /* clazz */,
        jstring path_j,
        jint sample_rate,
        jbyteArray pcm_j) {
    if (path_j == nullptr || pcm_j == nullptr) {
        throwIllegalState(env, "FLAC encode requires path and PCM");
        return;
    }
    if (sample_rate <= 0) {
        throwIllegalState(env, "FLAC sample rate must be positive");
        return;
    }

    const char *path = env->GetStringUTFChars(path_j, nullptr);
    if (path == nullptr) {
        throwIllegalState(env, "Failed to read FLAC output path");
        return;
    }
    std::string out_path(path);
    env->ReleaseStringUTFChars(path_j, path);

    const jsize pcm_len = env->GetArrayLength(pcm_j);
    if (pcm_len < 0 || (pcm_len % 2) != 0) {
        throwIllegalState(env, "PCM length must be even (16-bit samples)");
        return;
    }
    const size_t sample_count = static_cast<size_t>(pcm_len) / 2;

    jbyte *pcm_bytes = env->GetByteArrayElements(pcm_j, nullptr);
    if (pcm_bytes == nullptr) {
        throwIllegalState(env, "Failed to access PCM buffer");
        return;
    }

    std::vector<FLAC__int32> samples(sample_count);
    const auto *le = reinterpret_cast<const uint8_t *>(pcm_bytes);
    for (size_t i = 0; i < sample_count; ++i) {
        const int16_t s = static_cast<int16_t>(le[i * 2] | (le[i * 2 + 1] << 8));
        samples[i] = s;
    }
    env->ReleaseByteArrayElements(pcm_j, pcm_bytes, JNI_ABORT);

    FLAC__StreamEncoder *encoder = FLAC__stream_encoder_new();
    if (encoder == nullptr) {
        throwIllegalState(env, "FLAC__stream_encoder_new failed");
        return;
    }

    auto fail = [&](const char *msg) {
        LOGE("%s (state=%s)", msg, FLAC__stream_encoder_get_resolved_state_string(encoder));
        FLAC__stream_encoder_delete(encoder);
        throwIllegalState(env, msg);
    };

    if (!FLAC__stream_encoder_set_verify(encoder, false) ||
        !FLAC__stream_encoder_set_compression_level(encoder, kCompressionLevel) ||
        !FLAC__stream_encoder_set_channels(encoder, kChannels) ||
        !FLAC__stream_encoder_set_bits_per_sample(encoder, kBitsPerSample) ||
        !FLAC__stream_encoder_set_sample_rate(encoder, static_cast<uint32_t>(sample_rate)) ||
        !FLAC__stream_encoder_set_total_samples_estimate(encoder, sample_count)) {
        fail("Failed to configure FLAC encoder");
        return;
    }

    const FLAC__StreamEncoderInitStatus init_status =
            FLAC__stream_encoder_init_file(encoder, out_path.c_str(), nullptr, nullptr);
    if (init_status != FLAC__STREAM_ENCODER_INIT_STATUS_OK) {
        fail("FLAC__stream_encoder_init_file failed");
        return;
    }

    if (sample_count > 0) {
        if (!FLAC__stream_encoder_process_interleaved(
                    encoder, samples.data(), static_cast<uint32_t>(sample_count))) {
            fail("FLAC__stream_encoder_process_interleaved failed");
            return;
        }
    }

    if (!FLAC__stream_encoder_finish(encoder)) {
        fail("FLAC__stream_encoder_finish failed");
        return;
    }

    FLAC__stream_encoder_delete(encoder);
}
