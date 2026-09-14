package com.pawnai.recorder

import android.Manifest
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState

@Composable
fun PermissionRequired(onDenyClick: () -> Unit, guardedContent: @Composable () -> Unit) {
    val state = rememberPermissionState(Manifest.permission.RECORD_AUDIO)
    Scaffold { padding ->
        when {
            state.status.isGranted -> guardedContent()
            else -> {
                LaunchedEffect(Unit) { state.launchPermissionRequest() }
                PermissionRequiredScreen(
                    modifier = Modifier.padding(padding),
                    onDenyClick = onDenyClick,
                )
            }
        }
    }
}

@Composable
fun PermissionRequiredScreen(modifier: Modifier, onDenyClick: () -> Unit) {
    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.TopCenter,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp)
                .padding(top = 32.dp, bottom = 12.dp),
            horizontalAlignment = Alignment.Start,
        ) {
            Surface(
                shape = CircleShape,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(80.dp),
            ) {
                Icon(
                    Icons.Rounded.Mic,
                    contentDescription = null,
                    modifier = Modifier.padding(12.dp),
                    tint = MaterialTheme.colorScheme.onPrimary,
                )
            }
            Spacer(Modifier.height(36.dp))
            Text(
                text = "Microphone access is required",
                style = MaterialTheme.typography.headlineMedium,
            )
            Spacer(Modifier.height(16.dp))
            Text(
                text = "PawnAI Recorder needs the microphone to capture room audio and upload chunks for diarization.",
                textAlign = TextAlign.Start,
            )
            Spacer(Modifier.weight(1f))
            TextButton(
                onClick = onDenyClick,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.textButtonColors(
                    contentColor = MaterialTheme.colorScheme.onSurface,
                ),
            ) {
                Text("Deny")
            }
        }
    }
}
