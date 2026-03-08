/**
 * aaudio_recorder.c — minimal AAudio capture wrapper (Android API 26+)
 *
 * Exported C API (called via ctypes from Python):
 *   int  recorder_open(int sample_rate, int channels, int frames_per_burst)
 *   int  recorder_start()
 *   int  recorder_read(int16_t *buf, int32_t num_frames)
 *   void recorder_stop()
 *   void recorder_close()
 */

#include <aaudio/AAudio.h>
#include <android/log.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

#define LOG_TAG "PawnRecNative"
#define LOGI(...)  __android_log_print(ANDROID_LOG_INFO,  LOG_TAG, __VA_ARGS__)
#define LOGE(...)  __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static AAudioStream *g_stream = NULL;

int recorder_open(int sample_rate, int channels, int frames_per_burst) {
    AAudioStreamBuilder *builder = NULL;
    aaudio_result_t res;

    res = AAudio_createStreamBuilder(&builder);
    if (res != AAUDIO_OK) {
        LOGE("createStreamBuilder failed: %s", AAudio_convertResultToText(res));
        return -1;
    }

    AAudioStreamBuilder_setDirection(builder, AAUDIO_DIRECTION_INPUT);
    AAudioStreamBuilder_setSampleRate(builder, sample_rate);
    AAudioStreamBuilder_setChannelCount(builder, channels);
    AAudioStreamBuilder_setFormat(builder, AAUDIO_FORMAT_PCM_I16);
    AAudioStreamBuilder_setFramesPerDataCallback(builder, frames_per_burst);
    AAudioStreamBuilder_setPerformanceMode(builder, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
    AAudioStreamBuilder_setSharingMode(builder, AAUDIO_SHARING_MODE_SHARED);
    // setInputPreset requires API 28 — omitted to stay compatible with API 26

    res = AAudioStreamBuilder_openStream(builder, &g_stream);
    AAudioStreamBuilder_delete(builder);

    if (res != AAUDIO_OK) {
        LOGE("openStream failed: %s", AAudio_convertResultToText(res));
        g_stream = NULL;
        return -2;
    }

    LOGI("Stream opened: sampleRate=%d channels=%d format=PCM_I16",
         sample_rate, channels);
    return 0;
}

int recorder_start() {
    if (!g_stream) return -1;
    aaudio_result_t res = AAudioStream_requestStart(g_stream);
    if (res != AAUDIO_OK) {
        LOGE("requestStart failed: %s", AAudio_convertResultToText(res));
        return -1;
    }
    LOGI("Stream started.");
    return 0;
}

/**
 * Read up to num_frames int16 samples into buf.
 * Returns number of frames actually read, or negative error code.
 */
int recorder_read(int16_t *buf, int32_t num_frames) {
    if (!g_stream) return -1;
    aaudio_result_t result = AAudioStream_read(g_stream, buf, num_frames, 0 /* timeout_ns */);
    return (int)result;
}

void recorder_stop() {
    if (!g_stream) return;
    AAudioStream_requestStop(g_stream);
    LOGI("Stream stopped.");
}

void recorder_close() {
    if (!g_stream) return;
    AAudioStream_close(g_stream);
    g_stream = NULL;
    LOGI("Stream closed.");
}
