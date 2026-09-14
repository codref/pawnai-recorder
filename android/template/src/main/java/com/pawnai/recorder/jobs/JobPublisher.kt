package com.pawnai.recorder.jobs

import android.util.Log
import com.pawnai.recorder.settings.RecorderSettings
import com.pawnai.recorder.upload.S3AudioUploader
import dev.pawnai.queue.PawnQueue
import dev.pawnai.queue.Producer

/**
 * Thin wrapper: builds recorder job payloads and publishes via Kotlin PawnQueue.
 */
class JobPublisher(
    private val settings: RecorderSettings,
    private val bucket: String,
) {
    private var queue: PawnQueue? = null
    private var producer: Producer? = null

    val isStarted: Boolean get() = producer != null

    suspend fun start() {
        if (!settings.queueEnabled || !settings.hasS3Config()) {
            throw IllegalStateException("Queue disabled or S3 config incomplete")
        }
        Log.i(TAG, "Starting queue producer topic=${settings.queueTopic} bucket=$bucket")
        val pq = PawnQueue.fromRecorderS3(settings.toS3Map())
        pq.setup()
        pq.createTopic(settings.queueTopic)
        producer = pq.registerProducer(settings.producerName)
        queue = pq
        Log.i(TAG, "Queue producer ready producer=${settings.producerName}")
    }

    suspend fun publishTranscribeDiarize(
        session: String,
        objectKeys: List<String>,
    ) {
        val p = producer
            ?: throw IllegalStateException("Queue producer not started")
        if (objectKeys.isEmpty()) return
        val paths = objectKeys.map { key ->
            if (key.startsWith("s3://")) key else "s3://$bucket/$key"
        }
        val messageId = p.publish(
            settings.queueTopic,
            mapOf(
                "command" to "transcribe-diarize",
                "audio_paths" to paths,
                "threshold" to settings.diarizeThreshold.toDouble(),
                "cross_file_threshold" to settings.diarizeCrossFileThreshold.toDouble(),
                "session" to session,
                "device" to settings.diarizeDevice,
            ),
        )
        Log.i(TAG, "Published transcribe-diarize id=$messageId session=$session paths=$paths")
        Log.i(TAG, "Pending object key pattern: ${settings.queueTopic}/messages/*-$messageId.json")
    }

    suspend fun publishAnalyze(session: String) {
        if (!settings.analyzeEnabled) return
        val p = producer
            ?: throw IllegalStateException("Queue producer not started")
        val messageId = p.publish(
            settings.queueTopic,
            mapOf(
                "command" to "analyze",
                "session" to session,
                "mode" to settings.analyzeMode,
                "model" to settings.analyzeModel,
            ),
        )
        Log.i(TAG, "Published analyze id=$messageId session=$session")
    }

    suspend fun publishSyncSiyuan(session: String) {
        if (!settings.syncSiyuanEnabled) return
        val p = producer
            ?: throw IllegalStateException("Queue producer not started")
        val messageId = p.publish(
            settings.queueTopic,
            mapOf(
                "command" to "sync-siyuan",
                "session" to session,
            ),
        )
        Log.i(TAG, "Published sync-siyuan id=$messageId session=$session")
    }

    suspend fun close() {
        try {
            queue?.teardown()
        } finally {
            queue = null
            producer = null
        }
    }

    companion object {
        private const val TAG = "PawnAI.Queue"

        fun forUploader(settings: RecorderSettings, uploader: S3AudioUploader?): JobPublisher? {
            if (!settings.queueEnabled || !settings.hasS3Config()) return null
            return JobPublisher(settings, uploader?.bucket ?: settings.s3Bucket)
        }
    }
}
