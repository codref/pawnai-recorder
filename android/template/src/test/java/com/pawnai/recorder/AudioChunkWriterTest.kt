package com.pawnai.recorder.audio

import org.assertj.core.api.Assertions.assertThat
import org.assertj.core.api.Assertions.assertThatThrownBy
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.Rule
import java.io.File

class AudioChunkWriterTest {
    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun normalizeExtension_stripsDotAndCase() {
        assertThat(AudioChunkWriter.normalizeExtension("FLAC")).isEqualTo("flac")
        assertThat(AudioChunkWriter.normalizeExtension(".wav")).isEqualTo("wav")
    }

    @Test
    fun writeMonoPcm16_wav_writesRiffHeader() {
        val file = tmp.newFile("chunk.wav")
        val pcm = ByteArray(4) { it.toByte() }
        AudioChunkWriter.writeMonoPcm16(file, 16_000, pcm, "wav")
        val bytes = file.readBytes()
        assertThat(bytes.copyOfRange(0, 4).toString(Charsets.US_ASCII)).isEqualTo("RIFF")
        assertThat(bytes.copyOfRange(8, 12).toString(Charsets.US_ASCII)).isEqualTo("WAVE")
        assertThat(file.length()).isEqualTo(44L + pcm.size)
    }

    @Test
    fun writeMonoPcm16_rejectsUnknownFormat() {
        val file = File(tmp.root, "chunk.mp3")
        assertThatThrownBy {
            AudioChunkWriter.writeMonoPcm16(file, 16_000, ByteArray(2), "mp3")
        }.isInstanceOf(IllegalArgumentException::class.java)
            .hasMessageContaining("Unsupported audio format")
    }
}
