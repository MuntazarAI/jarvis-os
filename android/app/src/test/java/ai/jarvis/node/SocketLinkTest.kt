package ai.jarvis.node

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class SocketLinkTest {

    @Test
    fun roundtrip() {
        val payload = """{"message_id":"m1","sender_node":"n1","message_type":"heartbeat","payload":{}}"""
        val (frames, next) = SocketLink.decode(SocketLink.encode(payload))
        assertEquals(listOf(payload), frames)
        assertEquals(SocketLink.encode(payload).size, next)
    }

    @Test
    fun roundtripUnicodeAndLarge() {
        val payload = """{"text":"héllo-✓-${"x".repeat(200_000)}"}"""
        val (frames, _) = SocketLink.decode(SocketLink.encode(payload))
        assertEquals(listOf(payload), frames)
    }

    @Test
    fun incrementalDecode() {
        val a = """{"a":1}"""
        val b = """{"b":2}"""
        val wire = SocketLink.encode(a) + SocketLink.encode(b)
        // a single frame is 4 + 7 = 11 bytes; feed only 5 -> nothing complete
        val (first, pos1) = SocketLink.decode(wire.copyOfRange(0, 5))
        assertTrue(first.isEmpty())
        assertEquals(0, pos1)
        val (frames, _) = SocketLink.decode(wire, 0, wire.size)
        assertEquals(listOf(a, b), frames)
    }

    @Test
    fun oversizeRejected() {
        val big = ByteArray(SocketLink.MAX_FRAME_BYTES + 1)
        try {
            SocketLink.encode(String(big, Charsets.ISO_8859_1).let { "{\"d\":\"$it\"}" })
            fail("expected oversize rejection")
        } catch (_: IllegalArgumentException) {
            // expected
        }
        // oversize header on the wire
        val header = byteArrayOf(0x01.toByte(), 0x00.toByte(), 0x10.toByte(), 0x00.toByte()) // 1<<20+4096
        try {
            SocketLink.decode(header + ByteArray(8))
            fail("expected FramingException")
        } catch (_: FramingException) {
            // expected
        }
    }

    @Test
    fun badJsonPassthrough() {
        // framing layer passes bytes through; JSON validation is the protocol layer's job,
        // but truncated frames must not decode
        val payload = """{"partial":true"""
        val wire = SocketLink.encode("""{"partial":true}""")
        val cut = wire.copyOfRange(0, wire.size - 2)
        val (frames, _) = SocketLink.decode(cut)
        assertTrue(frames.isEmpty())
        assertTrue(payload.isNotEmpty())
    }

    @Test
    fun multiFrame() {
        val msgs = (1..5).map { """{"i":$it}""" }
        var wire = ByteArray(0)
        msgs.forEach { wire += SocketLink.encode(it) }
        val (frames, next) = SocketLink.decode(wire)
        assertEquals(msgs, frames)
        assertEquals(wire.size, next)
    }

    @Test
    fun peerExtractField() {
        val peer = SocketPeer(onRequest = { null })
        val json = """{"message_id":"m9","correlation_id":"c-1","payload":{"a":1}}"""
        assertEquals("c-1", peer.extractField(json, "correlation_id"))
        assertEquals("m9", peer.extractField(json, "message_id"))
        assertEquals("", peer.extractField(json, "missing"))
        assertEquals("", peer.extractField("not json", "correlation_id"))
    }
}
