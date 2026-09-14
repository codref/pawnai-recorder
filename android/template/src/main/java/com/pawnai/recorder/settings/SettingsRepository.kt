package com.pawnai.recorder.settings

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.MutablePreferences
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.pawnai.recorder.audio.SessionNameGenerator
import com.pawnai.recorder.audio.SessionNameHistory
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "pawnai_recorder")

class SettingsRepository(private val context: Context) {
    val settings: Flow<RecorderSettings> = context.dataStore.data.map { prefs ->
        prefs.toSettings()
    }

    suspend fun update(transform: (RecorderSettings) -> RecorderSettings) {
        context.dataStore.edit { prefs ->
            val next = transform(prefs.toSettings())
            writeSettings(prefs, next)
        }
    }

    /** Ensure a session label exists; generate + persist if empty. Returns the active label. */
    suspend fun ensureSessionLabel(): String {
        val current = settings.first()
        if (current.sessionLabel.isNotBlank()) return current.sessionLabel
        val generated = SessionNameGenerator.generate(avoid = current.sessionNameHistory.toSet())
        update { s ->
            s.copy(
                sessionLabel = generated,
                sessionNameHistory = SessionNameHistory.prepend(s.sessionNameHistory, generated),
            )
        }
        return generated
    }

    /** Update current label without touching history (idle typing). */
    suspend fun updateSessionLabel(name: String) {
        val normalized = SessionNameGenerator.normalize(name)
        update { s -> s.copy(sessionLabel = normalized) }
    }

    /** Set current session name and bump it to the front of history. */
    suspend fun setSessionName(name: String) {
        val normalized = SessionNameGenerator.normalize(name)
        if (normalized.isBlank()) return
        update { s ->
            s.copy(
                sessionLabel = normalized,
                sessionNameHistory = SessionNameHistory.prepend(s.sessionNameHistory, normalized),
            )
        }
    }

    /** Remember current label in history (e.g. on Start) without changing it. */
    suspend fun rememberCurrentSessionInHistory() {
        update { s ->
            if (s.sessionLabel.isBlank()) s
            else s.copy(
                sessionNameHistory = SessionNameHistory.prepend(s.sessionNameHistory, s.sessionLabel),
            )
        }
    }

    private fun Preferences.toSettings(): RecorderSettings = RecorderSettings(
        rate = this[Keys.RATE] ?: 16_000,
        chunkSizeSec = this[Keys.CHUNK_SIZE] ?: 120,
        gain = this[Keys.GAIN] ?: 1.0f,
        fileExtension = this[Keys.FILE_EXT] ?: "wav",
        timestampFormat = this[Keys.TS_FORMAT] ?: "{ts}",
        datetimeFormat = this[Keys.DT_FORMAT] ?: "yyMMddHHmmss",
        conversationId = this[Keys.CONVERSATION_ID] ?: "",
        sessionLabel = this[Keys.SESSION_LABEL] ?: "",
        sessionNameHistory = decodeHistory(this[Keys.SESSION_HISTORY]),
        s3Bucket = this[Keys.S3_BUCKET] ?: "",
        s3EndpointUrl = this[Keys.S3_ENDPOINT] ?: "",
        s3AccessKey = this[Keys.S3_ACCESS] ?: "",
        s3SecretKey = this[Keys.S3_SECRET] ?: "",
        s3Region = this[Keys.S3_REGION] ?: "us-east-1",
        s3Prefix = this[Keys.S3_PREFIX] ?: "conversations",
        s3VerifySsl = this[Keys.S3_VERIFY_SSL] ?: true,
        s3PathStyle = this[Keys.S3_PATH_STYLE] ?: true,
        uploadEnabled = this[Keys.UPLOAD_ENABLED] ?: true,
        queueEnabled = this[Keys.QUEUE_ENABLED] ?: true,
        queueTopic = this[Keys.QUEUE_TOPIC] ?: "audio-chunks",
        producerName = this[Keys.PRODUCER_NAME] ?: "pawnai-recorder-android",
        diarizeMode = this[Keys.DIARIZE_MODE] ?: "end_of_session",
        diarizeThreshold = this[Keys.DIARIZE_THRESHOLD] ?: 0.2f,
        diarizeCrossFileThreshold = this[Keys.DIARIZE_CROSS] ?: 0.2f,
        diarizeDevice = this[Keys.DIARIZE_DEVICE] ?: "cpu",
        analyzeEnabled = this[Keys.ANALYZE_ENABLED] ?: true,
        analyzeMode = this[Keys.ANALYZE_MODE] ?: "summary",
        analyzeModel = this[Keys.ANALYZE_MODEL] ?: "gpt-4o",
        syncSiyuanEnabled = this[Keys.SYNC_ENABLED] ?: true,
    )

    private fun writeSettings(prefs: MutablePreferences, next: RecorderSettings) {
        prefs[Keys.RATE] = next.rate
        prefs[Keys.CHUNK_SIZE] = next.chunkSizeSec
        prefs[Keys.GAIN] = next.gain
        prefs[Keys.FILE_EXT] = next.fileExtension
        prefs[Keys.TS_FORMAT] = next.timestampFormat
        prefs[Keys.DT_FORMAT] = next.datetimeFormat
        prefs[Keys.CONVERSATION_ID] = next.conversationId
        prefs[Keys.SESSION_LABEL] = next.sessionLabel
        prefs[Keys.SESSION_HISTORY] = encodeHistory(next.sessionNameHistory)
        prefs[Keys.S3_BUCKET] = next.s3Bucket
        prefs[Keys.S3_ENDPOINT] = next.s3EndpointUrl
        prefs[Keys.S3_ACCESS] = next.s3AccessKey
        prefs[Keys.S3_SECRET] = next.s3SecretKey
        prefs[Keys.S3_REGION] = next.s3Region
        prefs[Keys.S3_PREFIX] = next.s3Prefix
        prefs[Keys.S3_VERIFY_SSL] = next.s3VerifySsl
        prefs[Keys.S3_PATH_STYLE] = next.s3PathStyle
        prefs[Keys.UPLOAD_ENABLED] = next.uploadEnabled
        prefs[Keys.QUEUE_ENABLED] = next.queueEnabled
        prefs[Keys.QUEUE_TOPIC] = next.queueTopic
        prefs[Keys.PRODUCER_NAME] = next.producerName
        prefs[Keys.DIARIZE_MODE] = next.diarizeMode
        prefs[Keys.DIARIZE_THRESHOLD] = next.diarizeThreshold
        prefs[Keys.DIARIZE_CROSS] = next.diarizeCrossFileThreshold
        prefs[Keys.DIARIZE_DEVICE] = next.diarizeDevice
        prefs[Keys.ANALYZE_ENABLED] = next.analyzeEnabled
        prefs[Keys.ANALYZE_MODE] = next.analyzeMode
        prefs[Keys.ANALYZE_MODEL] = next.analyzeModel
        prefs[Keys.SYNC_ENABLED] = next.syncSiyuanEnabled
    }

    private object Keys {
        val RATE = intPreferencesKey("rate")
        val CHUNK_SIZE = intPreferencesKey("chunk_size")
        val GAIN = floatPreferencesKey("gain")
        val FILE_EXT = stringPreferencesKey("file_ext")
        val TS_FORMAT = stringPreferencesKey("ts_format")
        val DT_FORMAT = stringPreferencesKey("dt_format")
        val CONVERSATION_ID = stringPreferencesKey("conversation_id")
        val SESSION_LABEL = stringPreferencesKey("session_label")
        val SESSION_HISTORY = stringPreferencesKey("session_history")
        val S3_BUCKET = stringPreferencesKey("s3_bucket")
        val S3_ENDPOINT = stringPreferencesKey("s3_endpoint")
        val S3_ACCESS = stringPreferencesKey("s3_access")
        val S3_SECRET = stringPreferencesKey("s3_secret")
        val S3_REGION = stringPreferencesKey("s3_region")
        val S3_PREFIX = stringPreferencesKey("s3_prefix")
        val S3_VERIFY_SSL = booleanPreferencesKey("s3_verify_ssl")
        val S3_PATH_STYLE = booleanPreferencesKey("s3_path_style")
        val UPLOAD_ENABLED = booleanPreferencesKey("upload_enabled")
        val QUEUE_ENABLED = booleanPreferencesKey("queue_enabled")
        val QUEUE_TOPIC = stringPreferencesKey("queue_topic")
        val PRODUCER_NAME = stringPreferencesKey("producer_name")
        val DIARIZE_MODE = stringPreferencesKey("diarize_mode")
        val DIARIZE_THRESHOLD = floatPreferencesKey("diarize_threshold")
        val DIARIZE_CROSS = floatPreferencesKey("diarize_cross")
        val DIARIZE_DEVICE = stringPreferencesKey("diarize_device")
        val ANALYZE_ENABLED = booleanPreferencesKey("analyze_enabled")
        val ANALYZE_MODE = stringPreferencesKey("analyze_mode")
        val ANALYZE_MODEL = stringPreferencesKey("analyze_model")
        val SYNC_ENABLED = booleanPreferencesKey("sync_enabled")
    }

    companion object {
        fun encodeHistory(list: List<String>): String =
            list.filter { it.isNotBlank() }.joinToString("|")

        fun decodeHistory(raw: String?): List<String> =
            raw?.split('|')?.map { it.trim() }?.filter { it.isNotBlank() }.orEmpty()
    }
}
