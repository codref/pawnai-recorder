package com.pawnai.recorder.upload

import java.io.File

object ObjectKeyBuilder {
    fun build(
        filename: String,
        sessionId: String,
        conversationId: String? = null,
        prefix: String = "",
    ): String {
        val parts = mutableListOf<String>()
        normalizeSegment(prefix)?.let { parts.add(it) }
        if (!conversationId.isNullOrBlank()) {
            normalizeSegment(conversationId)?.let { parts.add(it) }
        }
        parts.add(normalizeSegment(sessionId) ?: sessionId)
        parts.add(File(filename).name)
        return parts.joinToString("/")
    }

    private fun normalizeSegment(value: String): String? {
        val normalized = value.replace('\\', '/')
            .split('/')
            .filter { it.isNotBlank() }
            .joinToString("/")
        return normalized.ifBlank { null }
    }
}
