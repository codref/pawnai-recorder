package com.pawnai.recorder

import com.pawnai.recorder.upload.S3AudioUploader
import org.assertj.core.api.Assertions.assertThat
import org.assertj.core.api.Assertions.assertThatThrownBy
import org.junit.Test

class S3EndpointParseTest {
    @Test
    fun keepsHttpScheme() {
        val url = S3AudioUploader.parseEndpoint("http://minio.local:9000")
        assertThat(url.scheme.protocolName).isEqualTo("http")
        assertThat(url.toString()).contains("minio.local")
    }

    @Test
    fun keepsHttpsScheme() {
        val url = S3AudioUploader.parseEndpoint("https://s3.example.com")
        assertThat(url.scheme.protocolName).isEqualTo("https")
    }

    @Test
    fun addsHttpWhenSchemeMissing() {
        val url = S3AudioUploader.parseEndpoint("192.168.1.10:9000")
        assertThat(url.scheme.protocolName).isEqualTo("http")
        assertThat(url.toString()).contains("192.168.1.10")
    }

    @Test
    fun rejectsBlank() {
        assertThatThrownBy { S3AudioUploader.parseEndpoint("  ") }
            .isInstanceOf(IllegalArgumentException::class.java)
    }
}
