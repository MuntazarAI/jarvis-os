package ai.jarvis.node

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/** Minimal honest UI: identity, pairing state, connect/disconnect.
 *  No fake controls — every button maps to a real local action. */
class MainActivity : AppCompatActivity() {

    private lateinit var statusView: TextView
    private lateinit var nodeView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val identity = NodeIdentityStore(this).loadOrCreate(android.os.Build.MODEL ?: "android")

        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
        }
        nodeView = TextView(this).apply {
            text = "node ${identity.nodeId}\n${identity.displayName} · android"
        }
        statusView = TextView(this).apply {
            text = "status: idle — not connected\npairing: unpaired"
        }
        val connect = Button(this).apply {
            text = "Connect (local link)"
            setOnClickListener {
                startService(
                    Intent(this@MainActivity, NodeService::class.java).apply {
                        action = NodeService.ACTION_CONNECT
                    },
                )
                statusView.text = "status: connected (local link)\npairing: see core CLI"
            }
        }
        val disconnect = Button(this).apply {
            text = "Disconnect"
            setOnClickListener {
                startService(
                    Intent(this@MainActivity, NodeService::class.java).apply {
                        action = NodeService.ACTION_DISCONNECT
                    },
                )
                statusView.text = "status: idle — not connected\npairing: unpaired"
            }
        }
        layout.addView(nodeView)
        layout.addView(statusView)
        layout.addView(connect)
        layout.addView(disconnect)
        setContentView(layout)
    }
}
