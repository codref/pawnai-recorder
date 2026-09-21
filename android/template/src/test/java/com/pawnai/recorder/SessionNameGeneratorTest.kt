package com.pawnai.recorder.audio

import org.assertj.core.api.Assertions.assertThat
import org.junit.Test
import kotlin.random.Random

class SessionNameGeneratorTest {
    @Test
    fun generate_matchesSafeFormat() {
        repeat(20) {
            val name = SessionNameGenerator.generate(random = Random(it))
            assertThat(SessionNameGenerator.isValidFormat(name))
                .withFailMessage("unexpected name: $name")
                .isTrue()
        }
    }

    @Test
    fun generate_avoidsHistoryWhenPossible() {
        val avoid = setOf("super-cat", "brave-fox")
        val name = SessionNameGenerator.generate(avoid = avoid, random = Random(1))
        assertThat(avoid).doesNotContain(name)
    }

    @Test
    fun history_prependsAndCapsAt20() {
        val history = (1..25).map { "name-$it" }
        val next = SessionNameHistory.prepend(history, "fresh-owl")
        assertThat(next).hasSize(SessionNameHistory.MAX_SIZE)
        assertThat(next.first()).isEqualTo("fresh-owl")
        assertThat(next).doesNotContain("name-25")
    }

    @Test
    fun history_movesExistingToFront() {
        val next = SessionNameHistory.prepend(listOf("a-b", "c-d", "e-f"), "c-d")
        assertThat(next).containsExactly("c-d", "a-b", "e-f")
    }
}
