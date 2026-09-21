package com.pawnai.recorder.upload

import aws.sdk.kotlin.runtime.auth.credentials.StaticCredentialsProvider
import aws.sdk.kotlin.services.s3.S3Client
import aws.sdk.kotlin.services.s3.model.HeadBucketRequest
import aws.sdk.kotlin.services.s3.model.PutObjectRequest
import aws.smithy.kotlin.runtime.client.config.RequestHttpChecksumConfig
import aws.smithy.kotlin.runtime.client.config.ResponseHttpChecksumConfig
import aws.smithy.kotlin.runtime.content.asByteStream
import aws.smithy.kotlin.runtime.net.url.Url
import com.pawnai.recorder.settings.RecorderSettings
import java.io.File

class S3AudioUploader(private val settings: RecorderSettings) : AutoCloseable {
    private val targetBucket: String = settings.s3Bucket
    private val client: S3Client = S3Client {
        region = settings.s3Region.ifBlank { "us-east-1" }
        endpointUrl = parseEndpoint(settings.normalizedEndpointUrl())
        forcePathStyle = settings.s3PathStyle
        requestChecksumCalculation = RequestHttpChecksumConfig.WHEN_REQUIRED
        responseChecksumValidation = ResponseHttpChecksumConfig.WHEN_REQUIRED
        credentialsProvider = StaticCredentialsProvider {
            accessKeyId = settings.s3AccessKey
            secretAccessKey = settings.s3SecretKey
        }
    }

    val bucket: String get() = targetBucket

    suspend fun uploadFile(
        localPath: String,
        sessionId: String,
        conversationId: String?,
    ): String {
        val objectKey = ObjectKeyBuilder.build(
            filename = localPath,
            sessionId = sessionId,
            conversationId = conversationId?.takeIf { it.isNotBlank() },
            prefix = settings.s3Prefix,
        )
        val file = File(localPath)
        client.putObject(
            PutObjectRequest {
                bucket = targetBucket
                key = objectKey
                body = file.asByteStream()
                contentType = contentTypeFor(file.extension)
            },
        )
        return objectKey
    }

    suspend fun checkBucket(): Result<Unit> = runCatching {
        client.headBucket(HeadBucketRequest { bucket = targetBucket })
    }

    override fun close() {
        try {
            client.close()
        } catch (_: Exception) {
            // AWS OkHttp engine may perform network I/O while shutting down sockets.
        }
    }

    private fun contentTypeFor(ext: String): String = when (ext.lowercase()) {
        "wav" -> "audio/wav"
        "flac" -> "audio/flac"
        "ogg" -> "audio/ogg"
        "mp3" -> "audio/mpeg"
        else -> "application/octet-stream"
    }

    companion object {
        fun parseEndpoint(raw: String): Url {
            val value = raw.trim()
            require(value.isNotEmpty()) { "Endpoint URL is blank" }
            val withScheme = when {
                value.startsWith("http://", ignoreCase = true) ||
                    value.startsWith("https://", ignoreCase = true) -> value
                else -> "http://$value"
            }
            return Url.parse(withScheme)
        }
    }
}
