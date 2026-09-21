package com.pawnai.recorder.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pawnai.recorder.di.settingsViewModel
import com.pawnai.recorder.record.GainSlider
import com.ramcosta.composedestinations.annotation.Destination
import com.ramcosta.composedestinations.navigation.DestinationsNavigator

private const val DIARIZE_END_OF_SESSION = "end_of_session"
private const val DIARIZE_PER_CHUNK = "per_chunk"

@OptIn(ExperimentalMaterial3Api::class)
@Destination
@Composable
fun SettingsScreen(navigator: DestinationsNavigator) {
    val vm: SettingsViewModel = viewModel { settingsViewModel() }
    val state by vm.state.collectAsState()
    val s = state.draft

    fun edit(transform: (RecorderSettings) -> RecorderSettings) {
        vm.pushUserAction(SettingsAction.Edit(transform))
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(if (state.dirty) "Settings *" else "Settings")
                },
                navigationIcon = {
                    IconButton(onClick = { navigator.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    if (state.dirty) {
                        TextButton(
                            onClick = { vm.pushUserAction(SettingsAction.Discard) },
                            enabled = !state.saving,
                        ) {
                            Text("Discard")
                        }
                        TextButton(
                            onClick = { vm.pushUserAction(SettingsAction.Save) },
                            enabled = !state.saving,
                        ) {
                            Text(if (state.saving) "Saving…" else "Save")
                        }
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            state.statusMessage?.let {
                Text(it, color = MaterialTheme.colorScheme.primary)
            }

            Section("Recording")
            IntField("Sample rate (Hz)", s.rate) {
                edit { cur -> cur.copy(rate = it) }
            }
            IntField("Chunk size (seconds)", s.chunkSizeSec) {
                edit { cur -> cur.copy(chunkSizeSec = it) }
            }
            GainSlider(
                gain = s.gain,
                onGainChange = { edit { cur -> cur.copy(gain = it) } },
            )
            Text("File format")
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                listOf("flac", "wav").forEach { ext ->
                    FilterChip(
                        selected = s.fileExtension.equals(ext, ignoreCase = true),
                        onClick = { edit { cur -> cur.copy(fileExtension = ext) } },
                        label = { Text(ext) },
                    )
                }
            }
            TextField("Timestamp format", s.timestampFormat) {
                edit { cur -> cur.copy(timestampFormat = it) }
            }
            TextField("Datetime format", s.datetimeFormat) {
                edit { cur -> cur.copy(datetimeFormat = it) }
            }
            TextField("Conversation ID", s.conversationId) {
                edit { cur -> cur.copy(conversationId = it) }
            }

            Section("S3")
            TextField("Bucket", s.s3Bucket) {
                edit { cur -> cur.copy(s3Bucket = it) }
            }
            TextField("Endpoint URL", s.s3EndpointUrl) {
                edit { cur -> cur.copy(s3EndpointUrl = it) }
            }
            TextField("Access key", s.s3AccessKey) {
                edit { cur -> cur.copy(s3AccessKey = it) }
            }
            TextField("Secret key", s.s3SecretKey) {
                edit { cur -> cur.copy(s3SecretKey = it) }
            }
            TextField("Region", s.s3Region) {
                edit { cur -> cur.copy(s3Region = it) }
            }
            TextField("Prefix", s.s3Prefix) {
                edit { cur -> cur.copy(s3Prefix = it) }
            }
            SwitchRow("Upload enabled", s.uploadEnabled) {
                edit { cur -> cur.copy(uploadEnabled = it) }
            }
            SwitchRow("Verify SSL", s.s3VerifySsl) {
                edit { cur -> cur.copy(s3VerifySsl = it) }
            }
            SwitchRow("Path style", s.s3PathStyle) {
                edit { cur -> cur.copy(s3PathStyle = it) }
            }
            Button(onClick = { vm.pushUserAction(SettingsAction.TestBucket) }) {
                Text("Test bucket")
            }
            state.bucketMessage?.let {
                Text(
                    it,
                    color = if (state.bucketOk == true) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.error,
                )
            }

            Section("Queue / diarization")
            SwitchRow("Queue enabled", s.queueEnabled) {
                edit { cur -> cur.copy(queueEnabled = it) }
            }
            TextField("Topic", s.queueTopic) {
                edit { cur -> cur.copy(queueTopic = it) }
            }
            TextField("Producer name", s.producerName) {
                edit { cur -> cur.copy(producerName = it) }
            }

            DiarizeModePicker(
                mode = s.diarizeMode,
                onModeChange = { mode -> edit { cur -> cur.copy(diarizeMode = mode) } },
            )

            FloatField("Threshold", s.diarizeThreshold) {
                edit { cur -> cur.copy(diarizeThreshold = it) }
            }
            FloatField("Cross-file threshold", s.diarizeCrossFileThreshold) {
                edit { cur -> cur.copy(diarizeCrossFileThreshold = it) }
            }
            TextField("Device", s.diarizeDevice) {
                edit { cur -> cur.copy(diarizeDevice = it) }
            }
            SwitchRow("Analyze enabled", s.analyzeEnabled) {
                edit { cur -> cur.copy(analyzeEnabled = it) }
            }
            TextField("Analyze mode", s.analyzeMode) {
                edit { cur -> cur.copy(analyzeMode = it) }
            }
            TextField("Analyze model", s.analyzeModel) {
                edit { cur -> cur.copy(analyzeModel = it) }
            }
            SwitchRow("Sync SiYuan enabled", s.syncSiyuanEnabled) {
                edit { cur -> cur.copy(syncSiyuanEnabled = it) }
            }

            if (state.dirty) {
                Spacer(Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    OutlinedButton(
                        onClick = { vm.pushUserAction(SettingsAction.Discard) },
                        enabled = !state.saving,
                        modifier = Modifier.weight(1f),
                    ) {
                        Text("Discard")
                    }
                    Button(
                        onClick = { vm.pushUserAction(SettingsAction.Save) },
                        enabled = !state.saving,
                        modifier = Modifier.weight(1f),
                    ) {
                        Text(if (state.saving) "Saving…" else "Save")
                    }
                }
            }
            Spacer(Modifier.height(32.dp))
        }
    }
}

@Composable
private fun DiarizeModePicker(mode: String, onModeChange: (String) -> Unit) {
    val selected = when (mode) {
        DIARIZE_PER_CHUNK -> DIARIZE_PER_CHUNK
        else -> DIARIZE_END_OF_SESSION
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("Diarize mode", style = MaterialTheme.typography.titleMedium)
        Text(
            "Controls when the recorder publishes the transcribe-diarize queue job " +
                "(not the pawn-queue lease concurrency strategy).",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(
                selected = selected == DIARIZE_END_OF_SESSION,
                onClick = { onModeChange(DIARIZE_END_OF_SESSION) },
                label = { Text("End of session") },
            )
            FilterChip(
                selected = selected == DIARIZE_PER_CHUNK,
                onClick = { onModeChange(DIARIZE_PER_CHUNK) },
                label = { Text("Per chunk") },
            )
        }
        Text(
            when (selected) {
                DIARIZE_PER_CHUNK ->
                    "Publishes one transcribe-diarize message immediately after each chunk upload."
                else ->
                    "Accumulates all chunk paths and publishes one transcribe-diarize message " +
                        "when recording stops (default)."
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun Section(title: String) {
    Spacer(Modifier.height(8.dp))
    Text(title, style = MaterialTheme.typography.titleLarge)
}

@Composable
private fun TextField(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
    )
}

@Composable
private fun IntField(label: String, value: Int, onChange: (Int) -> Unit) {
    var text by remember { mutableStateOf(value.toString()) }
    var focused by remember { mutableStateOf(false) }
    LaunchedEffect(value) {
        if (!focused) text = value.toString()
    }
    OutlinedTextField(
        value = text,
        onValueChange = { new ->
            text = new
            new.toIntOrNull()?.let(onChange)
        },
        label = { Text(label) },
        modifier = Modifier
            .fillMaxWidth()
            .onFocusChanged { focused = it.isFocused },
        singleLine = true,
    )
}

@Composable
private fun FloatField(label: String, value: Float, onChange: (Float) -> Unit) {
    var text by remember { mutableStateOf(value.toString()) }
    var focused by remember { mutableStateOf(false) }
    LaunchedEffect(value) {
        if (!focused) text = value.toString()
    }
    OutlinedTextField(
        value = text,
        onValueChange = { new ->
            text = new
            new.toFloatOrNull()?.let(onChange)
        },
        label = { Text(label) },
        modifier = Modifier
            .fillMaxWidth()
            .onFocusChanged { focused = it.isFocused },
        singleLine = true,
    )
}

@Composable
private fun SwitchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label)
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
