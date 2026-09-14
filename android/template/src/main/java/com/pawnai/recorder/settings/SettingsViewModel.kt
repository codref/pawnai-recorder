package com.pawnai.recorder.settings

import androidx.lifecycle.viewModelScope
import com.pawnai.recorder.core.AbstractViewModel
import com.pawnai.recorder.upload.S3AudioUploader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class SettingsUiState(
    val settings: RecorderSettings = RecorderSettings(),
    val bucketOk: Boolean? = null,
    val message: String? = null,
)

sealed interface SettingsAction {
    data class Update(val transform: (RecorderSettings) -> RecorderSettings) : SettingsAction
    data object TestBucket : SettingsAction
    data object ClearMessage : SettingsAction
}

class SettingsViewModel(
    private val repository: SettingsRepository,
) : AbstractViewModel<SettingsUiState, Nothing, SettingsAction>(
    startWith = SettingsUiState(),
) {
    init {
        viewModelScope.launch {
            repository.settings.collectLatest { s ->
                emitState(state.value.copy(settings = s))
            }
        }
    }

    override suspend fun processUserAction(userAction: SettingsAction) {
        when (userAction) {
            is SettingsAction.Update -> repository.update(userAction.transform)
            SettingsAction.TestBucket -> {
                val s = state.value.settings
                if (!s.hasS3Config()) {
                    emitState(state.value.copy(message = "Fill S3 fields first", bucketOk = false))
                    return
                }
                emitState(state.value.copy(message = "Checking bucket…", bucketOk = null))
                val (ok, message) = withContext(Dispatchers.IO) {
                    try {
                        S3AudioUploader(s).use { uploader ->
                            uploader.checkBucket().fold(
                                onSuccess = { true to "Bucket reachable" },
                                onFailure = { false to (it.message ?: "Bucket check failed") },
                            )
                        }
                    } catch (e: Exception) {
                        false to (e.message?.takeIf { it.isNotBlank() }
                            ?: "Bucket check failed (${e::class.simpleName})")
                    }
                }
                emitState(state.value.copy(bucketOk = ok, message = message))
            }
            SettingsAction.ClearMessage -> emitState(state.value.copy(message = null))
        }
    }
}
