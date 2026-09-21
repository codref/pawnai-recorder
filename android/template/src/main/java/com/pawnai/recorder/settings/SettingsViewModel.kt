package com.pawnai.recorder.settings

import androidx.lifecycle.viewModelScope
import com.pawnai.recorder.core.AbstractViewModel
import com.pawnai.recorder.upload.S3AudioUploader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class SettingsUiState(
    val draft: RecorderSettings = RecorderSettings(),
    val saved: RecorderSettings = RecorderSettings(),
    val dirty: Boolean = false,
    val saving: Boolean = false,
    val statusMessage: String? = null,
    val bucketOk: Boolean? = null,
    val bucketMessage: String? = null,
)

sealed interface SettingsAction {
    /** Edit draft only — does not hit DataStore until [Save]. */
    data class Edit(val transform: (RecorderSettings) -> RecorderSettings) : SettingsAction
    data object Save : SettingsAction
    data object Discard : SettingsAction
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
                val current = state.value
                if (current.dirty) {
                    // Keep the user's unsaved edits; only refresh the saved baseline.
                    emitState(current.copy(saved = s))
                } else {
                    emitState(
                        current.copy(
                            draft = s,
                            saved = s,
                            dirty = false,
                        ),
                    )
                }
            }
        }
    }

    override suspend fun processUserAction(userAction: SettingsAction) {
        when (userAction) {
            is SettingsAction.Edit -> {
                val next = userAction.transform(state.value.draft)
                emitState(
                    state.value.copy(
                        draft = next,
                        dirty = next != state.value.saved,
                        statusMessage = null,
                    ),
                )
            }
            SettingsAction.Save -> {
                val draft = state.value.draft
                emitState(state.value.copy(saving = true, statusMessage = null))
                repository.update { draft }
                emitState(
                    state.value.copy(
                        draft = draft,
                        saved = draft,
                        dirty = false,
                        saving = false,
                        statusMessage = "Saved",
                    ),
                )
            }
            SettingsAction.Discard -> {
                emitState(
                    state.value.copy(
                        draft = state.value.saved,
                        dirty = false,
                        statusMessage = "Discarded changes",
                        bucketMessage = null,
                        bucketOk = null,
                    ),
                )
            }
            SettingsAction.TestBucket -> {
                val s = state.value.draft
                if (!s.hasS3Config()) {
                    emitState(
                        state.value.copy(
                            bucketMessage = "Fill S3 fields first",
                            bucketOk = false,
                        ),
                    )
                    return
                }
                emitState(state.value.copy(bucketMessage = "Checking bucket…", bucketOk = null))
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
                emitState(state.value.copy(bucketOk = ok, bucketMessage = message))
            }
            SettingsAction.ClearMessage -> emitState(
                state.value.copy(statusMessage = null, bucketMessage = null),
            )
        }
    }
}
