package com.pawnai.recorder.jobs

import org.assertj.core.api.Assertions.assertThat
import org.junit.Test

class JobPayloadTest {
    @Test
    fun transcribePayloadShape() {
        val payload = mapOf(
            "command" to "transcribe-diarize",
            "audio_paths" to listOf("s3://bucket/conversations/mtg/sess/sess_01.wav"),
            "threshold" to 0.2,
            "cross_file_threshold" to 0.2,
            "session" to "sess",
            "device" to "cpu",
        )
        assertThat(payload["command"]).isEqualTo("transcribe-diarize")
        assertThat(payload["audio_paths"] as List<*>).hasSize(1)
        assertThat(payload).containsKeys("threshold", "cross_file_threshold", "session", "device")
    }
}
