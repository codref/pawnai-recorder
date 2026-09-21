package com.pawnai.recorder.record

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Casino
import androidx.compose.material.icons.rounded.CloudUpload
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pawnai.recorder.audio.ChunkSession
import com.pawnai.recorder.audio.ChunkStatus
import com.pawnai.recorder.audio.SessionNameGenerator
import com.pawnai.recorder.destinations.SettingsScreenDestination
import com.pawnai.recorder.di.recordViewModel
import com.ramcosta.composedestinations.annotation.Destination
import com.ramcosta.composedestinations.annotation.RootNavGraph
import com.ramcosta.composedestinations.navigation.DestinationsNavigator
import kotlin.math.log10
import kotlin.math.round

@OptIn(ExperimentalMaterial3Api::class)
@Destination
@RootNavGraph(start = true)
@Composable
fun RecordScreen(navigator: DestinationsNavigator) {
    val vm: RecordViewModel = viewModel { recordViewModel() }
    val state by vm.state.collectAsState()
    val snap = state.snapshot

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("PawnAI Recorder") },
                actions = {
                    IconButton(onClick = { navigator.navigate(SettingsScreenDestination) }) {
                        Icon(Icons.Rounded.Settings, contentDescription = "Settings")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = if (snap.isRecording) "Recording" else "Ready",
                style = MaterialTheme.typography.titleLarge,
            )
            Spacer(Modifier.height(12.dp))
            SessionNameRow(
                name = state.sessionName,
                history = state.sessionHistory,
                locked = snap.isRecording,
                onNameChange = { vm.pushUserAction(RecordAction.SetSessionName(it)) },
                onRandomize = { vm.pushUserAction(RecordAction.RandomizeSessionName) },
                onPick = { vm.pushUserAction(RecordAction.PickSessionName(it)) },
            )
            if (snap.sessionId.isNotBlank() || snap.conversationId.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    text = listOfNotNull(
                        snap.sessionId.takeIf { it.isNotBlank() }?.let { "run $it" },
                        snap.conversationId.takeIf { it.isNotBlank() },
                    ).joinToString(" · "),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f),
                )
            }
            Spacer(Modifier.height(8.dp))
            Text(
                text = formatElapsed(snap.elapsedSec),
                style = MaterialTheme.typography.headlineLarge,
                fontFamily = FontFamily.Monospace,
            )
            Spacer(Modifier.height(16.dp))
            VuMeter(level = snap.dbLevel, modifier = Modifier.fillMaxWidth().height(28.dp))
            Text(
                text = "%.0f dB".format(snap.dbLevel),
                style = MaterialTheme.typography.labelLarge,
            )
            Spacer(Modifier.height(16.dp))
            GainSlider(
                gain = state.gain,
                onGainChange = { vm.pushUserAction(RecordAction.SetGain(it)) },
            )
            Spacer(Modifier.height(16.dp))

            FilledIconButton(
                onClick = { vm.pushUserAction(RecordAction.ToggleRecord) },
                modifier = Modifier.size(88.dp),
                shape = CircleShape,
            ) {
                Icon(
                    imageVector = if (snap.isRecording) Icons.Rounded.Stop else Icons.Rounded.Mic,
                    contentDescription = if (snap.isRecording) "Stop" else "Record",
                    modifier = Modifier.size(40.dp),
                )
            }

            Spacer(Modifier.height(12.dp))
            OutlinedButton(
                onClick = { vm.pushUserAction(RecordAction.ForceUpload) },
                enabled = snap.isRecording,
            ) {
                Icon(Icons.Rounded.CloudUpload, contentDescription = null)
                Spacer(Modifier.size(8.dp))
                Text("Force upload chunk")
            }

            snap.lastError?.let { err ->
                Spacer(Modifier.height(8.dp))
                Text(err, color = MaterialTheme.colorScheme.error)
            }

            Spacer(Modifier.height(16.dp))
            Text(
                "Chunks",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.align(Alignment.Start),
            )
            Spacer(Modifier.height(8.dp))
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(snap.chunks.reversed(), key = { it.index }) { chunk ->
                    ChunkRow(chunk)
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SessionNameRow(
    name: String,
    history: List<String>,
    locked: Boolean,
    onNameChange: (String) -> Unit,
    onRandomize: () -> Unit,
    onPick: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    var focused by remember { mutableStateOf(false) }
    // Local draft so typing isn't interrupted by normalize/datastore round-trips.
    var draft by remember { mutableStateOf(name) }
    val historyChoices = remember(history, draft) {
        history.filterNot { it.equals(draft, ignoreCase = true) }
    }

    LaunchedEffect(name, locked) {
        when {
            locked || !focused -> draft = name
            // External change (randomize / pick) while focused — not just normalize of draft.
            SessionNameGenerator.normalize(draft) != name && draft != name -> draft = name
        }
    }

    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            "Session",
            style = MaterialTheme.typography.labelLarge,
            modifier = Modifier.align(Alignment.Start),
        )
        Spacer(Modifier.height(4.dp))
        if (locked) {
            Text(
                text = name.ifBlank { "—" },
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.fillMaxWidth(),
            )
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ExposedDropdownMenuBox(
                    expanded = expanded,
                    onExpandedChange = { expanded = it },
                    modifier = Modifier.weight(1f),
                ) {
                    OutlinedTextField(
                        value = draft,
                        onValueChange = {
                            draft = it
                            onNameChange(it)
                        },
                        singleLine = true,
                        modifier = Modifier
                            .menuAnchor(type = MenuAnchorType.PrimaryEditable)
                            .fillMaxWidth()
                            .onFocusChanged { focusState ->
                                val wasFocused = focused
                                focused = focusState.isFocused
                                if (wasFocused && !focusState.isFocused) {
                                    // Commit + show normalized form after editing finishes.
                                    val normalized = SessionNameGenerator.normalize(draft)
                                    draft = normalized
                                    if (normalized != name) onNameChange(normalized)
                                    expanded = false
                                }
                            },
                        placeholder = { Text("super-cat") },
                        trailingIcon = {
                            if (history.isNotEmpty()) {
                                // SecondaryEditable is required so the caret toggles the menu
                                // without fighting text focus (and without a double-toggle IconButton).
                                ExposedDropdownMenuDefaults.TrailingIcon(
                                    expanded = expanded,
                                    modifier = Modifier.menuAnchor(
                                        type = MenuAnchorType.SecondaryEditable,
                                    ),
                                )
                            }
                        },
                    )
                    ExposedDropdownMenu(
                        expanded = expanded && history.isNotEmpty(),
                        onDismissRequest = { expanded = false },
                    ) {
                        if (historyChoices.isEmpty()) {
                            DropdownMenuItem(
                                text = { Text("No other sessions") },
                                onClick = { expanded = false },
                                enabled = false,
                            )
                        } else {
                            historyChoices.forEach { item ->
                                DropdownMenuItem(
                                    text = { Text(item) },
                                    onClick = {
                                        expanded = false
                                        draft = item
                                        onPick(item)
                                    },
                                )
                            }
                        }
                    }
                }
                Spacer(Modifier.width(4.dp))
                IconButton(onClick = {
                    expanded = false
                    onRandomize()
                }) {
                    Icon(Icons.Rounded.Casino, contentDescription = "Randomize session name")
                }
            }
        }
    }
}

@Composable
private fun ChunkRow(chunk: com.pawnai.recorder.audio.ChunkInfo) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                MaterialTheme.colorScheme.surface,
                MaterialTheme.shapes.medium,
            )
            .padding(12.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text("#${chunk.index}  ${chunk.fileName}", style = MaterialTheme.typography.bodyLarge)
            Text(
                "%.1fs · %s".format(chunk.durationSec, chunk.status.name) +
                    (chunk.s3ObjectKey?.let { " · $it" } ?: ""),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f),
            )
            chunk.error?.let {
                Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            }
        }
        StatusDot(chunk.status)
    }
}

@Composable
private fun StatusDot(status: ChunkStatus) {
    val color = when (status) {
        ChunkStatus.Uploaded, ChunkStatus.Queued -> Color(0xFF2F6F5E)
        ChunkStatus.Failed -> MaterialTheme.colorScheme.error
        ChunkStatus.Uploading, ChunkStatus.Saving -> Color(0xFFC9852A)
        ChunkStatus.Recording -> MaterialTheme.colorScheme.primary
    }
    Box(
        modifier = Modifier
            .size(12.dp)
            .background(color, CircleShape),
    )
}

@Composable
private fun VuMeter(level: Float, modifier: Modifier = Modifier) {
    val fraction = (level / 120f).coerceIn(0f, 1f)
    val barColor = MaterialTheme.colorScheme.primary
    val track = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f)
    Canvas(modifier = modifier) {
        drawRoundRect(track, size = size, cornerRadius = CornerRadius(8f, 8f))
        drawRoundRect(
            barColor,
            size = Size(size.width * fraction, size.height),
            cornerRadius = CornerRadius(8f, 8f),
        )
    }
}

@Composable
fun GainSlider(
    gain: Float,
    onGainChange: (Float) -> Unit,
    modifier: Modifier = Modifier,
) {
    val dbLabel = if (gain > 0f) {
        val db = 20f * log10(gain)
        "%+.1f dB".format(db)
    } else {
        "-∞ dB"
    }
    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Gain", style = MaterialTheme.typography.labelLarge)
            Text(
                "%.1fx · %s".format(gain, dbLabel),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
            )
        }
        Slider(
            value = gain,
            onValueChange = { onGainChange(round(it * 10f) / 10f) },
            valueRange = ChunkSession.GAIN_MIN..ChunkSession.GAIN_MAX,
            steps = ((ChunkSession.GAIN_MAX - ChunkSession.GAIN_MIN) * 10).toInt() - 1,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

private fun formatElapsed(sec: Long): String {
    val m = sec / 60
    val s = sec % 60
    return "%02d:%02d".format(m, s)
}
