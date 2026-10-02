package ai.jarvis.node

/** Wire protocol mirror of jarvis/device/protocol.py (core side).
 *
 * The core is authoritative for validation; the app MUST build only these
 * typed messages and MUST reject anything it cannot parse. There is no
 * remote-execution message: COMMAND_REQUEST names a declared capability and
 * the app runs only its local allowlisted handler.
 */
object FabricProtocol {
    const val PROTOCOL_VERSION = 1
    const val MAX_PAYLOAD_BYTES = 64 * 1024

    /** Closed message set. Unknown types are rejected, never guessed. */
    enum class MessageType(val wire: String) {
        HELLO("hello"),
        REGISTER("register"),
        HEARTBEAT("heartbeat"),
        CAPABILITY_ADVERTISEMENT("capability_advertisement"),
        CAPABILITY_QUERY("capability_query"),
        STATE_UPDATE("state_update"),
        COMMAND_REQUEST("command_request"),
        COMMAND_RESULT("command_result"),
        EVENT("event"),
        ERROR("error"),
        GOODBYE("goodbye");

        companion object {
            fun fromWire(wire: String): MessageType =
                entries.firstOrNull { it.wire == wire }
                    ?: throw ProtocolException("unknown message_type: $wire")
        }
    }

    class ProtocolException(message: String) : IllegalArgumentException(message)

    data class FabricMessage(
        val messageId: String,
        val protocolVersion: Int = PROTOCOL_VERSION,
        val senderNode: String,
        val recipientNode: String = "",
        val messageType: String,
        val timestamp: Double = nowSeconds(),
        val requestId: String = "",
        val correlationId: String = "",
        val capability: String = "",
        val payload: Map<String, Any?> = emptyMap(),
    ) {
        /** Strict validation before send; mirrors protocol.FabricMessage.validate. */
        fun validate(): FabricMessage {
            require(messageId.isNotBlank()) { "message missing message_id" }
            require(protocolVersion >= 1) { "invalid protocol_version" }
            require(protocolVersion <= PROTOCOL_VERSION) {
                "unsupported protocol_version $protocolVersion"
            }
            require(senderNode.isNotBlank()) { "message missing sender_node" }
            val type = MessageType.fromWire(messageType)
            require(payload.toString().length <= MAX_PAYLOAD_BYTES) {
                "message payload exceeds size bound"
            }
            if (type == MessageType.COMMAND_REQUEST) {
                require(capability.isNotBlank()) {
                    "command_request requires a capability"
                }
            }
            return this
        }
    }

    private fun nowSeconds(): Double = System.currentTimeMillis() / 1000.0
}
