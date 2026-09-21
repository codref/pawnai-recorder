package com.pawnai.recorder.di

import com.pawnai.recorder.core.AppReference
import com.pawnai.recorder.record.RecordViewModel
import com.pawnai.recorder.settings.SettingsRepository
import com.pawnai.recorder.settings.SettingsViewModel

fun applicationContext() = AppReference.requireApplication()

fun settingsRepository(): SettingsRepository =
    SettingsRepository(applicationContext())

fun recordViewModel(): RecordViewModel =
    RecordViewModel(settingsRepository())

fun settingsViewModel(): SettingsViewModel =
    SettingsViewModel(settingsRepository())
