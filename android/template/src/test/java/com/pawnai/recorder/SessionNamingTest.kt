package com.pawnai.recorder.audio

import org.assertj.core.api.Assertions.assertThat
import org.junit.Test

class SessionNamingTest {
    @Test
    fun embedsDeviceIdPlaceholder() {
        val id = SessionNaming.buildSessionId(
            timestampFormat = "{ts}_dev{device_id}",
            datetimeFormat = "yyMMddHHmmss",
            deviceId = "3",
        )
        assertThat(id).endsWith("_dev3")
        assertThat(id).contains("_dev3")
    }

    @Test
    fun chunkFileNameIsZeroPadded() {
        assertThat(SessionNaming.chunkFileName("sess", 1, "wav"))
            .isEqualTo("sess_01.wav")
        assertThat(SessionNaming.chunkFileName("sess", 12, "wav"))
            .isEqualTo("sess_12.wav")
    }

    @Test
    fun levelMeterSilentIsZero() {
        assertThat(LevelMeter.calculateDbLevel(ShortArray(100))).isEqualTo(0f)
    }
}
