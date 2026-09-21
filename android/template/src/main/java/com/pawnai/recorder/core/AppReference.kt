package com.pawnai.recorder.core

import android.app.Application

object AppReference {
    @Volatile
    private var application: Application? = null

    fun setApplication(app: Application) {
        application = app
    }

    fun requireApplication(): Application =
        application ?: error("Application not initialized")
}
