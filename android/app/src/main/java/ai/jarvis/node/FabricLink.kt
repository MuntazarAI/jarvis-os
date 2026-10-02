package ai.jarvis.node

import ai.jarvis.node.FabricProtocol.FabricMessage
import ai.jarvis.node.FabricProtocol.MessageType

/** Link abstraction: how frames reach the core. The 3.9 milestone ships NO
 *  remote transport; InProcessLink is the honest local stand-in used by
 *  instrumentation tests. A real LAN/WebSocket transport plugs in here
 *  later WITHOUT changing protocol, capabilities, or command handling.
 */
interface FabricLink {
    fun isConnected(): Boolean
    fun send(message: FabricMessage): FabricMessage?
    fun close()
}

/** Deterministic in-process link: dispatches COMMAND_REQUEST to the local
 *  CommandDispatcher and acknowledges everything else. No sockets. */
class InProcessLink(
    private val localNodeId: String,
    private val dispatcher: CommandDispatcher,
) : FabricLink {
    private var open = true
    val sent = mutableListOf<FabricMessage>()

    override fun isConnected(): Boolean = open

    override fun send(message: FabricMessage): FabricMessage? {
        message.validate()
        sent.add(message)
        if (sent.size > 200) sent.removeAt(0)
        if (message.messageType == MessageType.COMMAND_REQUEST.wire) {
            val command = NodeCommand.fromWire(
                message.capability.ifBlank { message.messageType },
                emptyMap(),
            )
            val result = dispatcher.dispatch(command)
            return FabricMessage(
                messageId = "msg-local",
                senderNode = localNodeId,
                recipientNode = message.senderNode,
                messageType = MessageType.COMMAND_RESULT.wire,
                correlationId = message.messageId,
                payload = result,
            )
        }
        return FabricMessage(
            messageId = "msg-local",
            senderNode = localNodeId,
            recipientNode = message.senderNode,
            messageType = MessageType.EVENT.wire,
            correlationId = message.messageId,
            payload = mapOf("ok" to true, "ack" to message.messageType),
        )
    }

    override fun close() {
        open = false
    }
}
