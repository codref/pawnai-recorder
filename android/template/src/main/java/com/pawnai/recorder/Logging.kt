package com.pawnai.recorder

import android.util.Log
import com.pawnai.recorder.BuildConfig

object Logging {
    fun init() {}
}

inline fun verboseLn(message: () -> String) {
    if (BuildConfig.DEBUG) {
        Log.v("PawnAI", message())
    }
}
