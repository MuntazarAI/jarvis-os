package ai.jarvis.node

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.IBinder

/** Foreground service owning the node lifecycle. Started/stopped ONLY by
 *  explicit user action in MainActivity. No auto-start, no boot receiver:
 *  the node is never "just on" without the user knowing.
 */
class NodeService : Service() {

    private lateinit var identity: NodeIdentityStore.Identity
    private val capabilities = CapabilityRegistry()
    private lateinit var link: InProcessLink
    private lateinit var dispatcher: CommandDispatcher

    override fun onCreate() {
        super.onCreate()
        val store = NodeIdentityStore(this)
        identity = store.loadOrCreate(android.os.Build.MODEL ?: "android")
        dispatcher = CommandDispatcher(this)
        link = InProcessLink(identity.nodeId, dispatcher)
        // Declare read-only, permission-free capabilities by default.
        // Dangerous ones (location/camera/microphone) stay NOT_REQUESTED
        // until the user grants them in MainActivity.
        capabilities.declare(
            CapabilityDeclaration(NodeCapability.INFO, permission = PermissionState.AVAILABLE),
        )
        capabilities.declare(
            CapabilityDeclaration(NodeCapability.STATUS, permission = PermissionState.AVAILABLE),
        )
        capabilities.declare(
            CapabilityDeclaration(NodeCapability.BATTERY, permission = PermissionState.AVAILABLE),
        )
        capabilities.declare(
            CapabilityDeclaration(NodeCapability.SENSORS),
        )
        startForeground(NOTIFICATION_ID, buildNotification("JARVIS Node idle — not connected"))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CONNECT -> updateNotification("JARVIS Node link: local (3.9 milestone)")
            ACTION_DISCONNECT -> updateNotification("JARVIS Node idle — not connected")
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun buildNotification(text: String): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "JARVIS Node", NotificationManager.IMPORTANCE_LOW),
        )
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("JARVIS Node")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .build()
    }

    private fun updateNotification(text: String) {
        getSystemService(NotificationManager::class.java).notify(
            NOTIFICATION_ID, buildNotification(text),
        )
    }

    companion object {
        const val ACTION_CONNECT = "ai.jarvis.node.CONNECT"
        const val ACTION_DISCONNECT = "ai.jarvis.node.DISCONNECT"
        private const val CHANNEL = "jarvis_node"
        private const val NOTIFICATION_ID = 41
    }
}
