package ai.jarvis.node

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Length-prefix framing mirroring the Python FrameCodec
 * (jarvis/device/socket_transport.py).
 *
 * Wire layout: u32 big-endian length N, then N bytes of UTF-8 JSON.
 * Frames larger than [MAX_FRAME_BYTES] are rejected before allocation
 * completes. Decoding is incremental: feed bytes, pull complete frames.
 */
object SocketLink {
    const val MAX_FRAME_BYTES: Int = 256 * 1024
    private const val HEADER_SIZE: Int = 4

    fun encode(payloadJson: String): ByteArray {
        val body = payloadJson.toByteArray(Charsets.UTF_8)
        require(body.size <= MAX_FRAME_BYTES) {
            "frame too large: ${body.size} bytes"
        }
        val header = ByteBuffer.allocate(HEADER_SIZE)
            .order(ByteOrder.BIG_ENDIAN)
            .putInt(body.size)
            .array()
        return header + body
    }

    /**
     * Pull complete frames off the front of [buffer], returning the list of
     * decoded JSON strings. Malformed frames throw [FramingException];
     * callers should treat that as a fatal connection error.
     */
    fun decode(buffer: ByteArray, start: Int = 0, end: Int = buffer.size): Pair<List<String>, Int> {
        val out = mutableListOf<String>()
        var pos = start
        while (true) {
            if (end - pos < HEADER_SIZE) return out to pos
            val size = ByteBuffer.wrap(buffer, pos, HEADER_SIZE)
                .order(ByteOrder.BIG_ENDIAN).int
            if (size < 0 || size > MAX_FRAME_BYTES) {
                throw FramingException("frame too large: $size bytes")
            }
            if (end - pos < HEADER_SIZE + size) return out to pos
            val body = buffer.copyOfRange(pos + HEADER_SIZE, pos + HEADER_SIZE + size)
            val text = try {
                body.toString(Charsets.UTF_8)
            } catch (e: Exception) {
                throw FramingException("bad frame encoding: ${e.message}")
            }
            out.add(text)
            pos += HEADER_SIZE + size
        }
    }
}

class FramingException(message: String) : Exception(message)
