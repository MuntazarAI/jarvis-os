package ai.jarvis.node

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.BatteryManager
import android.os.IBinder
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/** Foreground service owning the fabric connection. Started/stopped ONLY by
 *  explicit user action in MainActivity. No auto-start, no boot receiver.
 *
 *  Owns: NodeConnection (pairing/auth/heartbeat/events/commands) on a
 *  single background executor, plus a 60 s heartbeat schedule. Publishes
 *  state via ACTION_STATE broadcasts; MainActivity renders them.
 */
class NodeService : Service() {

    private lateinit var store: NodeIdentityStore
    private lateinit var dispatcher: CommandDispatcher
    private lateinit var connection: NodeConnection
    private val executor = Executors.newSingleThreadScheduledExecutor()
    /** Pair-status polling runs here so a 200 s poll can never head-of-line
     *  block CONNECT / DISCONNECT / PAIR actions on [executor]. */
    private val pollExecutor = Executors.newSingleThreadExecutor()
    private var heartbeatTask: ScheduledFuture<*>? = null

    @Volatile private var deviceId: String? = null
    @Volatile private var trustState: String = "unregistered"
    @Volatile private var lastHeartbeat: Long = 0L

    override fun onCreate() {
        super.onCreate()
        store = NodeIdentityStore(this)
        val identity = store.loadOrCreate(android.os.Build.MODEL ?: "android")
        dispatcher = CommandDispatcher(this)
        connection = NodeConnection(
            nodeId = identity.nodeId,
            secret = { store.deviceSecret() },
            dispatchCommand = { capability, args ->
                try {
                    dispatcher.dispatch(NodeCommand.fromWire(capability, args))
                } catch (e: IllegalArgumentException) {
                    mapOf("ok" to false, "error" to "unknown command")
                }
            },
            onPeerState = { state ->
                broadcast()
                updateNotification("JARVIS Node: ${state.name.lowercase()}")
            },
        )
        try {
            startForeground(NOTIFICATION_ID, buildNotification("JARVIS Node idle — not connected"))
        } catch (e: Exception) {
            // Android 14+ denies startForeground when the app is backgrounded
            // (e.g. right after install). Do not crash — surface the error and
            // stop; the user retries from the UI with the app in the foreground.
            broadcast(error = "foreground start denied: ${e.javaClass.simpleName} — reopen the app and retry")
            stopSelf()
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CONNECT -> executor.execute {
                val host = intent.getStringExtra(EXTRA_HOST)?.takeIf { it.isNotBlank() }
                    ?: store.host()
                val port = intent.getIntExtra(EXTRA_PORT, store.port())
                if (host.isBlank() || port <= 0) {
                    broadcast(error = "no host configured — enter host/port first")
                    return@execute
                }
                store.saveEndpoint(host, port)
                connection.connect(host, port)
                startHeartbeats()
                broadcast()
            }
            ACTION_DISCONNECT -> executor.execute {
                stopHeartbeats()
                connection.disconnect()
                broadcast()
                updateNotification("JARVIS Node idle — not connected")
            }
            ACTION_PAIR -> executor.execute {
                val devId = intent.getStringExtra(EXTRA_DEVICE_ID) ?: return@execute
                val code = intent.getStringExtra(EXTRA_CODE) ?: return@execute
                // Pairing needs a live socket first — connect, wait, then pair.
                val host = intent.getStringExtra(EXTRA_HOST)?.takeIf { it.isNotBlank() }
                    ?: store.host()
                val port = intent.getIntExtra(EXTRA_PORT, store.port())
                if (host.isBlank() || port <= 0) {
                    broadcast(error = "no host configured — enter host/port first")
                    return@execute
                }
                store.saveEndpoint(host, port)
                PeerLog.debug("NodeService", "PAIR dial $host:$port dev=$devId")
                try {
                    connection.connect(host, port)
                    PeerLog.debug("NodeService", "PAIR connect() returned")
                } catch (t: Throwable) {
                    PeerLog.error("NodeService", "PAIR connect() failed: ${t.message}")
                    broadcast(error = "connect failed: ${t.message}")
                    return@execute
                }
                var waited = 0
                while (connection.connState != SocketPeer.ConnState.CONNECTED && waited < 20) {
                    Thread.sleep(500)
                    waited++
                }
                PeerLog.debug("NodeService", "PAIR waited=$waited state=${connection.connState}")
                if (connection.connState != SocketPeer.ConnState.CONNECTED) {
                    broadcast(error = "cannot reach host $host:$port — check network")
                    return@execute
                }
                val pending = connection.pairRequest(devId, code)
                // Never log the reply body: it carries the single-use
                // pending_token when pairing succeeds.
                PeerLog.debug("NodeService", "pairRequest ok=${pending != null}")
                val token = pending?.optString("pending_token").orEmpty()
                if (token.isEmpty()) {
                    broadcast(error = "pairing rejected — wrong code or expired")
                    return@execute
                }
                deviceId = devId
                trustState = "trust_pending"
                broadcast()
                pollPairStatus(devId, token)
            }
        }
        return START_NOT_STICKY
    }

    private fun pollPairStatus(devId: String, token: String) {
        pollExecutor.execute {
            repeat(40) {
                Thread.sleep(5_000)
                // A null reply is transient (socket hiccup) — keep polling.
                val status = connection.pairStatus(devId, token)
                if (status == null) return@repeat
                // Host keys the phase as "pair": pending|approved (never "state").
                when (status.optString("pair")) {
                    "approved" -> {
                        val secret = status.optString("device_secret")
                        if (secret.isNotEmpty()) {
                            store.saveDeviceSecret(secret)
                            deviceId = devId
                            trustState = "trusted"
                            startHeartbeats()
                            broadcast()
                        }
                        return@execute
                    }
                    "pending" -> { /* keep polling */ }
                    else -> {
                        broadcast(error = "pairing failed: ${status.optString("error")}")
                        return@execute
                    }
                }
            }
            broadcast(error = "pairing timed out — approve on the core and retry")
        }
    }

    private fun startHeartbeats() {
        stopHeartbeats()
        heartbeatTask = executor.scheduleAtFixedRate({
            val devId = deviceId ?: return@scheduleAtFixedRate
            val auth = connection.authHeaders(devId) ?: return@scheduleAtFixedRate
            val battery = readBattery()
            val reply = connection.heartbeat(devId, battery, auth) ?: return@scheduleAtFixedRate
            lastHeartbeat = System.currentTimeMillis()
            trustState = "trusted"
            broadcast()
        }, 0, 60, TimeUnit.SECONDS)
    }

    private fun stopHeartbeats() {
        heartbeatTask?.cancel(false)
        heartbeatTask = null
    }

    private fun readBattery(): Map<String, Any?> {
        val manager = getSystemService(BatteryManager::class.java) ?: return emptyMap()
        val pct = manager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val charging = manager.isCharging
        val snap = TelemetrySnapshot(
            batteryPct = if (pct in 0..100) pct.toFloat() else null,
            batteryCharging = charging,
            uptimeSeconds = android.os.SystemClock.elapsedRealtime() / 1000,
        )
        return snap.toPayload()
    }

    private fun broadcast(error: String? = null) {
        val intent = Intent(ACTION_STATE).apply {
            setPackage(packageName)
            putExtra(EXTRA_CONNECTED, connection.isConnected())
            putExtra(EXTRA_TRUST, trustState)
            putExtra(EXTRA_DEVICE_ID, deviceId)
            putExtra(EXTRA_HEARTBEAT, lastHeartbeat)
            if (error != null) putExtra(EXTRA_ERROR, error)
        }
        sendBroadcast(intent)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stopHeartbeats()
        connection.disconnect()
        executor.shutdownNow()
        pollExecutor.shutdownNow()
        super.onDestroy()
    }

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
        const val ACTION_PAIR = "ai.jarvis.node.PAIR"
        const val ACTION_STATE = "ai.jarvis.node.STATE"
        const val EXTRA_HOST = "host"
        const val EXTRA_PORT = "port"
        const val EXTRA_DEVICE_ID = "device_id"
        const val EXTRA_CODE = "code"
        const val EXTRA_CONNECTED = "connected"
        const val EXTRA_TRUST = "trust"
        const val EXTRA_HEARTBEAT = "last_heartbeat"
        const val EXTRA_ERROR = "error"
        private const val CHANNEL = "jarvis_node"
        private const val NOTIFICATION_ID = 41
    }
}
