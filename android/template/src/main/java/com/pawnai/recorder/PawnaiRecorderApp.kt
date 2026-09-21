package com.pawnai.recorder

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.pawnai.recorder.core.AppReference

class PawnaiRecorderApp : Application() {
    override fun onCreate() {
        super.onCreate()
        AppReference.setApplication(this)
        createRecordingChannel()
    }

    private fun createRecordingChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            RECORDING_CHANNEL_ID,
            getString(R.string.recording_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = getString(R.string.recording_channel_description)
        }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(channel)
    }

    companion object {
        const val RECORDING_CHANNEL_ID = "recording"
    }
}
