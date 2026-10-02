package ai.jarvis.node

import android.content.Context
import android.content.SharedPreferences
import java.util.UUID

/** Stable node identity, persisted across restarts (EncryptedSharedPreferences
 *  in a production build; plain prefs here, documented as a limitation).
 *
 * Identification only — never authentication. Trust always comes from the
 * explicit core-side pairing + human approval flow.
 */
class NodeIdentityStore(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    data class Identity(
        val nodeId: String,
        val displayName: String,
        val platform: String = "android",
        val protocolVersion: Int = FabricProtocol.PROTOCOL_VERSION,
    )

    /** Load the stable identity, creating it on first run. */
    fun loadOrCreate(displayName: String): Identity {
        var nodeId = prefs.getString(KEY_NODE_ID, null)
        if (nodeId.isNullOrBlank()) {
            nodeId = "node-" + UUID.randomUUID().toString().replace("-", "").take(16)
            prefs.edit().putString(KEY_NODE_ID, nodeId).apply()
        }
        if (displayName.isNotBlank()) {
            prefs.edit().putString(KEY_NAME, displayName.take(80)).apply()
        }
        return Identity(
            nodeId = nodeId,
            displayName = prefs.getString(KEY_NAME, displayName) ?: displayName,
        )
    }

    fun nodeId(): String? = prefs.getString(KEY_NODE_ID, null)

    companion object {
        private const val PREFS = "jarvis_node_identity"
        private const val KEY_NODE_ID = "node_id"
        private const val KEY_NAME = "display_name"
    }
}
