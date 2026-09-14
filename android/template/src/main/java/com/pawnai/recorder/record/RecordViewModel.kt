package com.pawnai.recorder.record

import androidx.lifecycle.viewModelScope
import com.pawnai.recorder.audio.ChunkSession
import com.pawnai.recorder.audio.RecordingSnapshot
import com.pawnai.recorder.audio.SessionNameGenerator
import com.pawnai.recorder.core.AbstractViewModel
import com.pawnai.recorder.service.RecordingForegroundService
import com.pawnai.recorder.settings.SettingsRepository
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import kotlin.math.round

data class RecordUiState(
    val snapshot: RecordingSnapshot = RecordingSnapshot(),
    val gain: Float = 1.0f,
    val sessionName: String = "",
    val sessionHistory: List<String> = emptyList(),
)

sealed interface RecordAction {
    data object ToggleRecord : RecordAction
    data object ForceUpload : RecordAction
    data object ClearError : RecordAction
    data class SetGain(val gain: Float) : RecordAction
    data class SetSessionName(val name: String) : RecordAction
    data object RandomizeSessionName : RecordAction
    data class PickSessionName(val name: String) : RecordAction
}

class RecordViewModel(
    private val settingsRepository: SettingsRepository,
) : AbstractViewModel<RecordUiState, Nothing, RecordAction>(
    startWith = RecordUiState(),
) {
    init {
        viewModelScope.launch {
            settingsRepository.ensureSessionLabel()
        }
        viewModelScope.launch {
            combine(
                RecordingForegroundService.Controller.snapshot,
                settingsRepository.settings,
            ) { snap, settings ->
                RecordUiState(
                    snapshot = snap,
                    gain = settings.gain,
                    sessionName = if (snap.isRecording && snap.sessionName.isNotBlank()) {
                        snap.sessionName
                    } else {
                        settings.sessionLabel
                    },
                    sessionHistory = settings.sessionNameHistory,
                )
            }.collectLatest { emitState(it) }
        }
    }

    override suspend fun processUserAction(userAction: RecordAction) {
        when (userAction) {
            RecordAction.ToggleRecord -> {
                if (state.value.snapshot.isRecording) {
                    RecordingForegroundService.Controller.stop()
                } else {
                    // Start the service immediately; session label is ensured inside the service.
                    RecordingForegroundService.Controller.start()
                }
            }
            RecordAction.ForceUpload -> RecordingForegroundService.Controller.forceFlush()
            RecordAction.ClearError -> Unit
            is RecordAction.SetGain -> {
                val gain = (round(userAction.gain * 10f) / 10f)
                    .coerceIn(ChunkSession.GAIN_MIN, ChunkSession.GAIN_MAX)
                RecordingForegroundService.Controller.setGain(gain)
                settingsRepository.update { it.copy(gain = gain) }
            }
            is RecordAction.SetSessionName -> {
                if (state.value.snapshot.isRecording) return
                settingsRepository.updateSessionLabel(userAction.name)
                RecordingForegroundService.Controller.onSessionNameChanged(userAction.name)
            }
            RecordAction.RandomizeSessionName -> {
                if (state.value.snapshot.isRecording) return
                val avoid = state.value.sessionHistory.toSet() + state.value.sessionName
                val generated = SessionNameGenerator.generate(avoid = avoid)
                settingsRepository.setSessionName(generated)
                RecordingForegroundService.Controller.onSessionNameChanged(generated)
            }
            is RecordAction.PickSessionName -> {
                if (state.value.snapshot.isRecording) return
                settingsRepository.setSessionName(userAction.name)
                RecordingForegroundService.Controller.onSessionNameChanged(userAction.name)
            }
        }
    }
}
