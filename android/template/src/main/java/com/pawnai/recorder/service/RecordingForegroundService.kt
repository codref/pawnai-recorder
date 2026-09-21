package com.pawnai.recorder.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.pawnai.recorder.MainActivity
import com.pawnai.recorder.PawnaiRecorderApp
import com.pawnai.recorder.R
import com.pawnai.recorder.audio.ChunkInfo
import com.pawnai.recorder.audio.ChunkSession
import com.pawnai.recorder.audio.RecordingSnapshot
import com.pawnai.recorder.core.AppReference
import com.pawnai.recorder.settings.SettingsRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

class RecordingForegroundService : Service() {
    // Default — not Main: S3/OkHttp teardown touches the network and will crash on Main.
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var session: ChunkSession? = null
    private var observeJob: Job? = null
    private var startJob: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startRecording()
            ACTION_STOP -> stopRecording()
            ACTION_FORCE_FLUSH -> session?.requestForceFlush()
        }
        return START_STICKY
    }

    private fun startRecording() {
        if (session != null || startJob?.isActive == true) return
        // Controller.start() already set optimistic isRecording / startInFlight.

        val notification = buildNotification(0f, 0)
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            notification,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            } else {
                0
            },
        )
        startJob = scope.launch {
            try {
                val repo = SettingsRepository(applicationContext)
                repo.ensureSessionLabel()
                repo.rememberCurrentSessionInHistory()
                val settings = repo.settings.first()
                val priorChunks = Controller.chunksForSession(settings.sessionLabel)
                Controller.publishStarting(settings.sessionLabel, settings.conversationId, priorChunks)
                if (settings.uploadEnabled && !settings.hasS3Config()) {
                    Controller.setWarning("S3 settings incomplete — upload/queue disabled")
                } else if (!settings.queueEnabled) {
                    Controller.setWarning("Queue disabled — audio will upload without jobs")
                }
                val outDir = File(filesDir, "audio")
                val chunkSession = ChunkSession(outDir, settings, scope, priorChunks = priorChunks)
                session = chunkSession
                Controller.attach(chunkSession)
                chunkSession.start()
                observeJob = scope.launch {
                    chunkSession.snapshot.collect { snap ->
                        Controller.publish(snap)
                        updateNotification(snap.dbLevel, snap.elapsedSec)
                    }
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                // Stop requested while starting — let stopRecording finish cleanup.
                throw e
            } catch (e: Exception) {
                Controller.emitError(e.message ?: "Failed to start recording")
                session = null
                observeJob?.cancel()
                observeJob = null
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            } finally {
                startJob = null
            }
        }
    }

    private fun stopRecording() {
        // Never cancel startJob: that used to null `session` before upload/publish ran.
        scope.launch {
            try {
                startJob?.join()
                session?.stop()
            } catch (e: Exception) {
                Controller.emitError(e.message ?: "Failed to stop recording")
            } finally {
                observeJob?.cancel()
                observeJob = null
                session = null
                startJob = null
                Controller.detach()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
    }

    private fun buildNotification(db: Float, elapsed: Long): Notification {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this,
            1,
            Intent(this, RecordingForegroundService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, PawnaiRecorderApp.RECORDING_CHANNEL_ID)
            .setContentTitle(getString(R.string.recording_notification_title))
            .setContentText("${elapsed}s · ${"%.0f".format(db)} dB")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentIntent(open)
            .addAction(0, "Stop", stop)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(db: Float, elapsed: Long) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as android.app.NotificationManager
        nm.notify(NOTIFICATION_ID, buildNotification(db, elapsed))
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    object Controller {
        private val _snapshot = MutableStateFlow(RecordingSnapshot())
        val snapshot: StateFlow<RecordingSnapshot> = _snapshot.asStateFlow()
        @Volatile
        private var activeSession: ChunkSession? = null
        private val startInFlight = AtomicBoolean(false)
        @Volatile
        private var retainedSessionName: String = ""
        @Volatile
        private var retainedChunks: List<ChunkInfo> = emptyList()

        fun chunksForSession(sessionName: String): List<ChunkInfo> {
            val name = sessionName.trim()
            return if (name.isNotBlank() && name == retainedSessionName) retainedChunks else emptyList()
        }

        /** Clear retained chunks when the user switches to a different session name. */
        fun onSessionNameChanged(newName: String) {
            val name = newName.trim()
            if (name == retainedSessionName) return
            retainedSessionName = name
            retainedChunks = emptyList()
            if (!_snapshot.value.isRecording && !startInFlight.get()) {
                _snapshot.value = _snapshot.value.copy(
                    sessionName = name,
                    chunks = emptyList(),
                    sessionId = "",
                    elapsedSec = 0,
                    dbLevel = 0f,
                )
            }
        }

        /** Returns false if a start is already in progress or recording. */
        fun beginStart(): Boolean {
            if (_snapshot.value.isRecording || !startInFlight.compareAndSet(false, true)) {
                return false
            }
            // Keep existing chunks while the service boots.
            _snapshot.updateSafe { it.copy(isRecording = true, lastError = null) }
            return true
        }

        fun publishStarting(
            sessionName: String,
            conversationId: String,
            priorChunks: List<ChunkInfo> = chunksForSession(sessionName),
        ) {
            if (sessionName.isNotBlank()) {
                retainedSessionName = sessionName
            }
            _snapshot.updateSafe {
                it.copy(
                    isRecording = true,
                    sessionName = sessionName,
                    conversationId = conversationId,
                    chunks = priorChunks,
                    lastError = null,
                )
            }
        }

        fun attach(session: ChunkSession) {
            activeSession = session
            val live = session.snapshot.value
            _snapshot.value = if (live.isRecording || live.chunks.isNotEmpty()) live else _snapshot.value
        }

        fun publish(snap: RecordingSnapshot) {
            _snapshot.value = snap
            if (snap.sessionName.isNotBlank()) {
                retainedSessionName = snap.sessionName
                retainedChunks = snap.chunks
            }
        }

        fun detach() {
            activeSession = null
            startInFlight.set(false)
            val current = _snapshot.value
            if (current.sessionName.isNotBlank()) {
                retainedSessionName = current.sessionName
                retainedChunks = current.chunks
            }
            // Keep chunks visible after stop; only clear live recording state.
            _snapshot.value = current.copy(
                isRecording = false,
                elapsedSec = 0,
                dbLevel = 0f,
            )
        }

        fun setGain(gain: Float) {
            activeSession?.setGain(gain)
        }

        fun emitError(message: String) {
            startInFlight.set(false)
            _snapshot.updateSafe { it.copy(lastError = message, isRecording = false) }
        }

        fun setWarning(message: String) {
            _snapshot.updateSafe { it.copy(lastError = message) }
        }

        private fun MutableStateFlow<RecordingSnapshot>.updateSafe(
            transform: (RecordingSnapshot) -> RecordingSnapshot,
        ) {
            value = transform(value)
        }

        fun start(context: android.content.Context = AppReference.requireApplication()) {
            if (!beginStart()) return
            val intent = Intent(context, RecordingForegroundService::class.java)
                .setAction(ACTION_START)
            try {
                context.startForegroundService(intent)
            } catch (e: Exception) {
                emitError(e.message ?: "Could not start recording service")
            }
        }

        fun stop(context: android.content.Context = AppReference.requireApplication()) {
            val intent = Intent(context, RecordingForegroundService::class.java)
                .setAction(ACTION_STOP)
            context.startService(intent)
        }

        fun forceFlush(context: android.content.Context = AppReference.requireApplication()) {
            val intent = Intent(context, RecordingForegroundService::class.java)
                .setAction(ACTION_FORCE_FLUSH)
            context.startService(intent)
        }
    }

    companion object {
        const val ACTION_START = "com.pawnai.recorder.START"
        const val ACTION_STOP = "com.pawnai.recorder.STOP"
        const val ACTION_FORCE_FLUSH = "com.pawnai.recorder.FORCE_FLUSH"
        const val NOTIFICATION_ID = 42
    }
}
