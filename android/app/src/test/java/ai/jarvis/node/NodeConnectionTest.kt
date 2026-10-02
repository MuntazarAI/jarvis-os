package ai.jarvis.node

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.ServerSocket
import java.net.Socket
import java.nio.ByteBuffer
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit

/** NodeConnection behaviour: pure unit tests plus a live loopback
 *  conversation against a fake host on 127.0.0.1 (no phone needed). */
class NodeConnectionTest {

    // -- pure unit tests --------------------------------------------------

    @Test
    fun allowlistAcceptsBareWiresAndRejectsShell() {
        assertTrue(NodeCommand.isAllowlisted("get_battery"))
        assertTrue(NodeCommand.isAllowlisted("get_info"))
        assertFalse(NodeCommand.isAllowlisted("shell"))
        assertFalse(NodeCommand.isAllowlisted("exec"))
        assertFalse(NodeCommand.isAllowlisted("device.shell"))
        assertFalse(NodeCommand.isAllowlisted(""))
    }

    @Test
    fun cryptoHmacIsDeterministicAndKeyed() {
        val a = NodeCrypto.answerHex("secret", "challenge")
        assertEquals(a, NodeCrypto.answerHex("secret", "challenge"))
        assertNotEquals(a, NodeCrypto.answerHex("other", "challenge"))
        assertNotEquals(a, NodeCrypto.answerHex("secret", "other"))
        assertEquals(64, a.length)
    }

    @Test
    fun protocolVersionIsPositive() {
        assertTrue(FabricProtocol.PROTOCOL_VERSION >= 1)
    }

    // -- loopback conversation --------------------------------------------

    private class FakeHost(val sock: Socket) {
        private val inp = DataInputStream(sock.getInputStream())
        private val out = DataOutputStream(sock.getOutputStream())

        fun readFrame(timeoutMs: Long = 5000): JSONObject {
            sock.soTimeout = timeoutMs.toInt()
            val len = inp.readInt()
            assertTrue("frame too large: $len", len in 1..(256 * 1024))
            val raw = ByteArray(len)
            inp.readFully(raw)
            return JSONObject(String(raw, Charsets.UTF_8))
        }

        fun writeFrame(obj: JSONObject) {
            val raw = obj.toString().toByteArray(Charsets.UTF_8)
            out.write(ByteBuffer.allocate(4).putInt(raw.size).array())
            out.write(raw)
            out.flush()
        }

        fun replyEnvelope(req: JSONObject, payload: Map<String, Any?>): JSONObject {
            return JSONObject()
                .put("message_id", "msg-host-" + UUID.randomUUID().toString().take(8))
                .put("protocol_version", FabricProtocol.PROTOCOL_VERSION)
                .put("sender_node", "host")
                .put("recipient_node", req.optString("sender_node"))
                .put("message_type", req.optString("message_type"))
                .put("correlation_id", req.optString("message_id"))
                .put("capability", "")
                .put("payload", JSONObject(payload))
                .put("auth", JSONObject())
        }
    }

    @Test
    fun loopbackHelloAndHostCommandAreAnswered() {
        val listener = ServerSocket(0, 1)
        val accepted = ArrayBlockingQueue<Socket>(1)
        val acceptThread = Thread {
            try { accepted.offer(listener.accept(), 5, TimeUnit.SECONDS) } catch (_: Exception) {}
        }.also { it.isDaemon = true; it.start() }

        val states = ArrayBlockingQueue<SocketPeer.ConnState>(4)
        val conn = NodeConnection(
            nodeId = "node-test-1",
            secret = { null },
            dispatchCommand = { capability, _ ->
                assertEquals("get_battery", capability)
                mapOf("battery" to 77)
            },
            onPeerState = { states.offer(it) },
        )
        try {
            conn.connect("127.0.0.1", listener.localPort)
            val connected = generateSequence { states.poll(5, TimeUnit.SECONDS) }
                .take(4).any { it == SocketPeer.ConnState.CONNECTED }
            assertTrue("peer never connected", connected)
            val hostSock = accepted.poll(5, TimeUnit.SECONDS)
                ?: throw AssertionError("fake host never accepted")
            val host = FakeHost(hostSock)

            // Drive hello from a worker thread (send blocks for the reply).
            val helloPayload = ArrayBlockingQueue<JSONObject>(1)
            val helloThread = Thread {
                helloPayload.offer(
                    conn.hello("dev-test-1") ?: JSONObject(),
                    5, TimeUnit.SECONDS,
                )
            }.also { it.isDaemon = true; it.start() }

            val helloReq = host.readFrame()
            assertEquals("hello", helloReq.optString("message_type"))
            assertEquals("dev-test-1", helloReq.optJSONObject("payload")?.optString("device_id"))
            host.writeFrame(host.replyEnvelope(helloReq, mapOf("ok" to true, "lifecycle" to "trusted")))
            helloThread.join(5000)
            val payload = helloPayload.poll() ?: throw AssertionError("no hello reply")
            assertEquals("trusted", payload.optString("lifecycle"))

            // Host-initiated command: fake host sends command_request
            // directly on the wire; NodeConnection must answer command_result.
            val cmdId = "msg-cmd-1"
            host.writeFrame(
                JSONObject()
                    .put("message_id", cmdId)
                    .put("protocol_version", FabricProtocol.PROTOCOL_VERSION)
                    .put("sender_node", "host")
                    .put("recipient_node", "node-test-1")
                    .put("message_type", "command_request")
                    .put("correlation_id", "")
                    .put("capability", "get_battery")
                    .put("payload", JSONObject(mapOf("args" to JSONObject())))
                    .put("auth", JSONObject()),
            )
            val answer = host.readFrame()
            assertEquals("command_result", answer.optString("message_type"))
            assertEquals(cmdId, answer.optString("correlation_id"))
            assertTrue(answer.optJSONObject("payload")?.optBoolean("ok") == true)
            assertEquals(
                77,
                answer.optJSONObject("payload")?.optJSONObject("result")?.optInt("battery"),
            )
            hostSock.close()
        } finally {
            conn.disconnect()
            listener.close()
            acceptThread.join(2000)
        }
    }
}
