package com.pawnai.recorder.core

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.pawnai.recorder.verboseLn
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

abstract class AbstractViewModel<State : Any, Event : Any, UserAction : Any>(
    startWith: State,
) : ViewModel() {

    private val innerState = MutableStateFlow(startWith)
    val state: StateFlow<State> = innerState.asStateFlow()

    private val internalEvents = Channel<Event>(Channel.BUFFERED)
    val events = internalEvents.receiveAsFlow()

    private val internalUserActions = MutableSharedFlow<UserAction>(extraBufferCapacity = 1)
    private val userActions: Flow<UserAction> = internalUserActions.asSharedFlow()

    init {
        viewModelScope.launch {
            userActions.collect { processUserAction(it) }
        }
    }

    open suspend fun processUserAction(userAction: UserAction) {}

    protected suspend fun emitState(state: State) {
        withContext(Dispatchers.Main.immediate) {
            verboseLn { "${viewModelName()} ⬅️ ${simpleName(state)}" }
            innerState.emit(state)
        }
    }

    protected suspend fun emitEvent(event: Event) {
        withContext(Dispatchers.Main.immediate) {
            verboseLn { "${viewModelName()} ⚡️ ${simpleName(event)}" }
            internalEvents.trySend(event)
        }
    }

    fun pushUserAction(userAction: UserAction) {
        viewModelScope.launch {
            withContext(Dispatchers.Main.immediate) {
                verboseLn { "${viewModelName()} ➡️ ${simpleName(userAction)}" }
                internalUserActions.emit(userAction)
            }
        }
    }

    private fun simpleName(value: Any): String =
        if (value.javaClass.kotlin.objectInstance != null) {
            value::class.simpleName ?: "object"
        } else {
            value.toString()
        }

    private fun viewModelName(): String =
        this@AbstractViewModel::class.simpleName ?: "object"
}
