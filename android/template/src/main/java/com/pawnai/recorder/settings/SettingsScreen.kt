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
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pawnai.recorder.di.settingsViewModel
import com.pawnai.recorder.record.GainSlider
import com.ramcosta.composedestinations.annotation.Destination
import com.ramcosta.composedestinations.navigation.DestinationsNavigator

@OptIn(ExperimentalMaterial3Api::class)
@Destination
@Composable
fun SettingsScreen(navigator: DestinationsNavigator) {
    val vm: SettingsViewModel = viewModel { settingsViewModel() }
    val state by vm.state.collectAsState()
    val s = state.settings

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings") },
                navigationIcon = {
                    IconButton(onClick = { navigator.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "Back")
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
            Section("Recording")
            IntField("Sample rate (Hz)", s.rate) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(rate = it) })
            }
            IntField("Chunk size (seconds)", s.chunkSizeSec) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(chunkSizeSec = it) })
            }
            GainSlider(
                gain = s.gain,
                onGainChange = {
                    vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(gain = it) })
                },
            )
            TextField("File extension", s.fileExtension) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(fileExtension = it) })
            }
            TextField("Timestamp format", s.timestampFormat) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(timestampFormat = it) })
            }
            TextField("Datetime format", s.datetimeFormat) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(datetimeFormat = it) })
            }
            TextField("Conversation ID", s.conversationId) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(conversationId = it) })
            }

            Section("S3")
            TextField("Bucket", s.s3Bucket) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(s3Bucket = it) })
            }
            TextField("Endpoint URL", s.s3EndpointUrl) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(s3EndpointUrl = it) })
            }
            TextField("Access key", s.s3AccessKey) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(s3AccessKey = it) })
            }
            TextField("Secret key", s.s3SecretKey) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(s3SecretKey = it) })
            }
            TextField("Region", s.s3Region) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(s3Region = it) })
            }
            TextField("Prefix", s.s3Prefix) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(s3Prefix = it) })
            }
            SwitchRow("Upload enabled", s.uploadEnabled) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(uploadEnabled = it) })
            }
            SwitchRow("Verify SSL", s.s3VerifySsl) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(s3VerifySsl = it) })
            }
            SwitchRow("Path style", s.s3PathStyle) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(s3PathStyle = it) })
            }
            Button(onClick = { vm.pushUserAction(SettingsAction.TestBucket) }) {
                Text("Test bucket")
            }
            state.message?.let {
                Text(
                    it,
                    color = if (state.bucketOk == true) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.error,
                )
            }

            Section("Queue / diarization")
            SwitchRow("Queue enabled", s.queueEnabled) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(queueEnabled = it) })
            }
            TextField("Topic", s.queueTopic) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(queueTopic = it) })
            }
            TextField("Producer name", s.producerName) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(producerName = it) })
            }
            TextField("Diarize mode (end_of_session|per_chunk)", s.diarizeMode) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(diarizeMode = it) })
            }
            FloatField("Threshold", s.diarizeThreshold) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(diarizeThreshold = it) })
            }
            FloatField("Cross-file threshold", s.diarizeCrossFileThreshold) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(diarizeCrossFileThreshold = it) })
            }
            TextField("Device", s.diarizeDevice) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(diarizeDevice = it) })
            }
            SwitchRow("Analyze enabled", s.analyzeEnabled) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(analyzeEnabled = it) })
            }
            TextField("Analyze mode", s.analyzeMode) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(analyzeMode = it) })
            }
            TextField("Analyze model", s.analyzeModel) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(analyzeModel = it) })
            }
            SwitchRow("Sync SiYuan enabled", s.syncSiyuanEnabled) {
                vm.pushUserAction(SettingsAction.Update { cur -> cur.copy(syncSiyuanEnabled = it) })
            }
            Spacer(Modifier.height(32.dp))
        }
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
    OutlinedTextField(
        value = value.toString(),
        onValueChange = { it.toIntOrNull()?.let(onChange) },
        label = { Text(label) },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
    )
}

@Composable
private fun FloatField(label: String, value: Float, onChange: (Float) -> Unit) {
    OutlinedTextField(
        value = value.toString(),
        onValueChange = { it.toFloatOrNull()?.let(onChange) },
        label = { Text(label) },
        modifier = Modifier.fillMaxWidth(),
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
