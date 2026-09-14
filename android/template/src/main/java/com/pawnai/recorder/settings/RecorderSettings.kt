package com.pawnai.recorder.settings

data class RecorderSettings(
    // recording
    val rate: Int = 16_000,
    val chunkSizeSec: Int = 120,
    val gain: Float = 1.0f,
    val fileExtension: String = "wav",
    val timestampFormat: String = "{ts}",
    val datetimeFormat: String = "yyMMddHHmmss",
    val conversationId: String = "",
    val sessionLabel: String = "",
    val sessionNameHistory: List<String> = emptyList(),
    // s3
    val s3Bucket: String = "",
    val s3EndpointUrl: String = "",
    val s3AccessKey: String = "",
    val s3SecretKey: String = "",
    val s3Region: String = "us-east-1",
    val s3Prefix: String = "conversations",
    val s3VerifySsl: Boolean = true,
    val s3PathStyle: Boolean = true,
    val uploadEnabled: Boolean = true,
    // queue
    val queueEnabled: Boolean = true,
    val queueTopic: String = "audio-chunks",
    val producerName: String = "pawnai-recorder-android",
    val diarizeMode: String = "end_of_session", // end_of_session | per_chunk
    val diarizeThreshold: Float = 0.2f,
    val diarizeCrossFileThreshold: Float = 0.2f,
    val diarizeDevice: String = "cpu",
    val analyzeEnabled: Boolean = true,
    val analyzeMode: String = "summary",
    val analyzeModel: String = "gpt-4o",
    val syncSiyuanEnabled: Boolean = true,
) {
    fun hasS3Config(): Boolean =
        s3Bucket.isNotBlank() &&
            s3EndpointUrl.isNotBlank() &&
            s3AccessKey.isNotBlank() &&
            s3SecretKey.isNotBlank()

    fun normalizedEndpointUrl(): String {
        val value = s3EndpointUrl.trim()
        if (value.isEmpty()) return value
        return if (value.startsWith("http://", ignoreCase = true) ||
            value.startsWith("https://", ignoreCase = true)
        ) {
            value
        } else {
            "http://$value"
        }
    }

    fun toS3Map(): Map<String, Any?> = mapOf(
        "bucket" to s3Bucket,
        "endpoint_url" to normalizedEndpointUrl(),
        "access_key" to s3AccessKey,
        "secret_key" to s3SecretKey,
        "region" to s3Region,
        "prefix" to s3Prefix,
        "verify_ssl" to s3VerifySsl,
        "path_style" to s3PathStyle,
    )
}
