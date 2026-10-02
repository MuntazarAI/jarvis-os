package ai.jarvis.node

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.BatteryManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

/** Real Node UI: endpoint config, pairing, connect/disconnect, live status
 *  from NodeService ACTION_STATE broadcasts, and per-capability OS
 *  permission states. Every control maps to a real action; states shown
 *  are read from the service or the OS, never invented. */
class MainActivity : AppCompatActivity() {

    private lateinit var store: NodeIdentityStore
    private lateinit var statusView: TextView
    private lateinit var nodeView: TextView
    private lateinit var capsView: TextView
    private lateinit var hostField: EditText
    private lateinit var portField: EditText
    private lateinit var deviceField: EditText
    private lateinit var codeField: EditText

    private var lastHeartbeat: Long = 0L
    private val ticker = Handler(Looper.getMainLooper())
    private val tick = object : Runnable {
        override fun run() {
            renderHeartbeat()
            ticker.postDelayed(this, 5_000)
        }
    }

    private val stateReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val connected = intent.getBooleanExtra(NodeService.EXTRA_CONNECTED, false)
            val trust = intent.getStringExtra(NodeService.EXTRA_TRUST) ?: "unknown"
            val devId = intent.getStringExtra(NodeService.EXTRA_DEVICE_ID)
            lastHeartbeat = intent.getLongExtra(NodeService.EXTRA_HEARTBEAT, 0L)
            val error = intent.getStringExtra(NodeService.EXTRA_ERROR)
            statusView.text = buildString {
                append(if (connected) "[ Connected ]" else "[ Offline ]")
                append("\ntrust: $trust")
                append("\ndevice: ${devId ?: "—"}")
                if (error != null) append("\nerror: $error")
            }
            renderHeartbeat()
            renderCapabilities()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = NodeIdentityStore(this)
        val identity = store.loadOrCreate(android.os.Build.MODEL ?: "android")

        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
        }
        nodeView = TextView(this).apply {
            text = "JARVIS NODE\nnode ${identity.nodeId}\n${identity.displayName} · android"
        }
        statusView = TextView(this).apply { text = "[ Offline ]\ntrust: unregistered" }
        val heartbeatView = TextView(this).apply { text = "last heartbeat: never" }
        heartbeatHolder = heartbeatView

        hostField = EditText(this).apply {
            hint = "JARVIS host (IP / hostname / tailnet)"
            setText(store.host())
        }
        portField = EditText(this).apply {
            hint = "port"
            val p = store.port()
            setText(if (p > 0) p.toString() else "")
        }
        deviceField = EditText(this).apply { hint = "device id (from core register)" }
        codeField = EditText(this).apply { hint = "pairing code" }
        capsView = TextView(this).apply { text = "" }

        val save = Button(this).apply {
            text = "Save endpoint"
            setOnClickListener {
                val port = portField.text.toString().toIntOrNull() ?: 0
                store.saveEndpoint(hostField.text.toString().trim(), port)
            }
        }
        val pair = Button(this).apply {
            text = "Pair device"
            setOnClickListener {
                startNodeService(
                    NodeService.ACTION_PAIR,
                    NodeService.EXTRA_DEVICE_ID to deviceField.text.toString().trim(),
                    NodeService.EXTRA_CODE to codeField.text.toString().trim(),
                    NodeService.EXTRA_HOST to hostField.text.toString().trim(),
                    NodeService.EXTRA_PORT to (portField.text.toString().toIntOrNull() ?: 0),
                )
            }
        }
        val connect = Button(this).apply {
            text = "Connect"
            setOnClickListener {
                startNodeService(
                    NodeService.ACTION_CONNECT,
                    NodeService.EXTRA_HOST to hostField.text.toString().trim(),
                    NodeService.EXTRA_PORT to (portField.text.toString().toIntOrNull() ?: 0),
                )
            }
        }
        val disconnect = Button(this).apply {
            text = "Disconnect"
            setOnClickListener { startNodeService(NodeService.ACTION_DISCONNECT) }
        }
        layout.addView(nodeView)
        layout.addView(statusView)
        layout.addView(heartbeatView)
        layout.addView(hostField)
        layout.addView(portField)
        layout.addView(save)
        layout.addView(deviceField)
        layout.addView(codeField)
        layout.addView(pair)
        layout.addView(connect)
        layout.addView(disconnect)
        layout.addView(capsView)
        setContentView(layout)
    }

    override fun onResume() {
        super.onResume()
        registerReceiver(
            stateReceiver,
            IntentFilter(NodeService.ACTION_STATE),
            RECEIVER_NOT_EXPORTED,
        )
        renderCapabilities()
        ticker.post(tick)
    }

    override fun onPause() {
        super.onPause()
        unregisterReceiver(stateReceiver)
        ticker.removeCallbacks(tick)
    }

    private lateinit var heartbeatHolder: TextView

    private fun renderHeartbeat() {
        val age = if (lastHeartbeat > 0) {
            "${(System.currentTimeMillis() - lastHeartbeat) / 1000}s ago"
        } else {
            "never"
        }
        val manager = getSystemService(BatteryManager::class.java)
        val pct = manager?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        heartbeatHolder.text =
            "last heartbeat: $age\nbattery: ${if (pct != null && pct in 0..100) "$pct%" else "unknown"}"
    }

    private fun renderCapabilities() {
        capsView.text = buildString {
            append("capabilities (on-device permission):\n")
            for (cap in NodeCapability.entries) {
                val perm = cap.androidPermission
                val state = when {
                    perm == null -> "available"
                    perm.startsWith("android.hardware.") -> "hardware feature"
                    ContextCompat.checkSelfPermission(
                        this@MainActivity, perm,
                    ) == PackageManager.PERMISSION_GRANTED -> "granted"
                    else -> "not granted"
                }
                append("· ${cap.wire}: $state\n")
            }
        }
    }

    private fun startNodeService(action: String, vararg extras: Pair<String, Any>) {
        val intent = Intent(this, NodeService::class.java).apply {
            this.action = action
            for ((key, value) in extras) {
                when (value) {
                    is String -> putExtra(key, value)
                    is Int -> putExtra(key, value)
                }
            }
        }
        ContextCompat.startForegroundService(this, intent)
    }
}
