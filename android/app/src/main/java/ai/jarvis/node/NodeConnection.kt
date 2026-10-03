package ai.jarvis.node

import org.json.JSONObject
import java.util.UUID

/** Client-side fabric conversation: hello, pairing, challenge-response
 *  auth, heartbeats, events — and answering host-initiated commands.
 *
 *  Framing/TCP live in SocketPeer; message semantics live here. Every
 *  outbound message is validated before send; every reply is parsed
 *  defensively (missing keys -> null, never guessed). Blocking calls —
 *  run them off the main thread (NodeService owns the executor).
 */
class NodeConnection(
    private val nodeId: String,
    private val secret: () -> String?,
    private val dispatchCommand: (capability: String, args: Map<String, Any?>) -> Map<String, Any?>,
    private val onPeerState: (SocketPeer.ConnState) -> Unit = {},
) {
    private var peer: SocketPeer? = null

    /** Last transport state, for callers that must wait for CONNECTED. */
    @Volatile var connState: SocketPeer.ConnState = SocketPeer.ConnState.DISCONNECTED
        private set

    fun connect(host: String, port: Int) {
        disconnect()
        val p = SocketPeer(
            onRequest = ::onServerFrame,
            onState = { state -> connState = state; onPeerState(state) },
        )
        peer = p
        p.start(host, port, nodeId)
    }

    fun disconnect() {
        peer?.stop()
        peer = null
    }

    fun isConnected(): Boolean = connState == SocketPeer.ConnState.CONNECTED

    // -- bootstrap ------------------------------------------------------

    /** First contact. Returns the reply payload, or null when unreachable. */
    fun hello(deviceId: String, platform: Map<String, Any?> = emptyMap()): JSONObject? {
        val reply = send("hello", deviceId = deviceId, payload = mapOf("platform" to platform))
            ?: return null
        return reply.optJSONObject("payload")
    }

    /** Confirm a pairing code out-of-band. Returns reply payload. */
    fun pairRequest(deviceId: String, code: String): JSONObject? {
        val reply = send(
            "pair_request", deviceId = deviceId,
            payload = mapOf("code" to code, "node_id" to nodeId),
        ) ?: return null
        return reply.optJSONObject("payload")
    }

    /** Poll for human approval. Returns reply payload. */
    fun pairStatus(deviceId: String, pendingToken: String): JSONObject? {
        val reply = send(
            "pair_status", deviceId = deviceId,
            payload = mapOf("pending_token" to pendingToken),
        ) ?: return null
        return reply.optJSONObject("payload")
    }

    // -- authenticated traffic -------------------------------------------

    /** Fetch a fresh single-use challenge, then answer it with the secret. */
    fun authHeaders(deviceId: String): JSONObject? {
        val current = secret() ?: return null
        val challengeReply = send("auth_challenge", deviceId = deviceId) ?: return null
        val challenge = challengeReply.optJSONObject("payload")?.optString("challenge")
            .takeUnless { it.isNullOrBlank() } ?: return null
        return JSONObject()
            .put("challenge", challenge)
            .put("response", NodeCrypto.answerHex(current, challenge))
    }

    fun heartbeat(deviceId: String, telemetry: Map<String, Any?>, auth: JSONObject): JSONObject? {
        val reply = send("heartbeat", deviceId = deviceId, payload = telemetry, auth = auth)
            ?: return null
        val payload = reply.optJSONObject("payload")
        if (payload?.optBoolean("ok") != true) {
            // Only an explicit host auth failure stops reconnecting
            // (wrong secret, revoked trust). Transient refusals keep
            // the socket: the next heartbeat retries normally.
            if (payload?.optBoolean("auth_failed") == true) {
                peer?.notifyAuthFailed()
            }
            return null
        }
        return payload
    }

    fun sendEvent(deviceId: String, event: String, payload: Map<String, Any?>, auth: JSONObject): Boolean {
        val body = HashMap<String, Any?>(payload)
        body["event"] = event
        val reply = send("event", deviceId = deviceId, payload = body, auth = auth)
        return reply?.optJSONObject("payload")?.optBoolean("ok") == true
    }

    // -- host-initiated commands ------------------------------------------

    private fun onServerFrame(json: String): String? {
        val msg = try { JSONObject(json) } catch (_: Exception) { return null }
        if (msg.optString("message_type") != "command_request") return null
        val capability = msg.optString("capability")
        if (capability.isBlank() || !NodeCommand.isAllowlisted(capability)) return null
        val args = msg.optJSONObject("payload")?.optJSONObject("args")?.toStringMap()
            ?: emptyMap()
        val result = try {
            dispatchCommand(capability, args)
        } catch (_: Exception) {
            mapOf("ok" to false, "error" to "handler failed")
        }
        // Mutual auth: echo the host proof requirement is core-side; the
        // reply carries our result only.
        return JSONObject()
            .put("message_id", "msg-" + UUID.randomUUID().toString().replace("-", "").take(16))
            .put("protocol_version", FabricProtocol.PROTOCOL_VERSION)
            .put("sender_node", nodeId)
            .put("recipient_node", msg.optString("sender_node"))
            .put("message_type", "command_result")
            .put("correlation_id", msg.optString("message_id"))
            .put("capability", capability)
            .put("payload", JSONObject(mapOf("ok" to true, "result" to result)))
            .toString()
    }

    // -- plumbing -----------------------------------------------------------

    private fun send(
        type: String,
        deviceId: String,
        payload: Map<String, Any?> = emptyMap(),
        auth: JSONObject = JSONObject(),
    ): JSONObject? {
        val p = peer ?: return null
        val id = "msg-" + UUID.randomUUID().toString().replace("-", "").take(16)
        val msg = JSONObject()
            .put("message_id", id)
            .put("protocol_version", FabricProtocol.PROTOCOL_VERSION)
            .put("sender_node", nodeId)
            .put("message_type", type)
            .put("timestamp", System.currentTimeMillis() / 1000.0)
            .put("capability", "")
            .put("payload", JSONObject(payload + mapOf("device_id" to deviceId)))
            .put("auth", auth)
        val raw = p.send(msg.toString(), id) ?: return null
        return try { JSONObject(raw) } catch (_: Exception) { null }
    }

    private fun JSONObject.toStringMap(): Map<String, Any?> {
        val out = HashMap<String, Any?>()
        val it = keys()
        while (it.hasNext()) {
            val k = it.next()
            out[k] = opt(k)
        }
        return out
    }
}
