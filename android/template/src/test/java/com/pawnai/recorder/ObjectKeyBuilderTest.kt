package com.pawnai.recorder.upload

import org.assertj.core.api.Assertions.assertThat
import org.junit.Test

class ObjectKeyBuilderTest {
    @Test
    fun buildsKeyWithoutConversation() {
        val key = ObjectKeyBuilder.build(
            filename = "audio/260223143022_01.wav",
            sessionId = "260223143022",
            conversationId = null,
            prefix = "",
        )
        assertThat(key).isEqualTo("260223143022/260223143022_01.wav")
    }

    @Test
    fun buildsKeyWithPrefixAndConversation() {
        val key = ObjectKeyBuilder.build(
            filename = "260223143022_02.wav",
            sessionId = "260223143022",
            conversationId = "mtg-01",
            prefix = "conversations",
        )
        assertThat(key).isEqualTo("conversations/mtg-01/260223143022/260223143022_02.wav")
    }
}
