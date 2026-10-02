package ai.jarvis.node

/** Bounded telemetry snapshot. Every metric except identity is optional:
 *  unknown stays unknown (null), never fabricated. Mirrors Telemetry.
 */
data class TelemetrySnapshot(
    val batteryPct: Float? = null,
    val batteryCharging: Boolean? = null,
    val networkType: String? = null,
    val networkConnected: Boolean? = null,
    val uptimeSeconds: Long? = null,
    val appVersion: String = "",
) {
    fun toPayload(): Map<String, Any?> {
        val out = mutableMapOf<String, Any?>()
        batteryPct?.let { out["battery_pct"] = it.coerceIn(0f, 100f) }
        batteryCharging?.let { out["battery_charging"] = it }
        networkType?.let { out["network"] = mapOf("type" to it) }
        networkConnected?.let { out["online"] = it }
        uptimeSeconds?.let { if (it >= 0) out["uptime_s"] = it.toDouble() }
        if (appVersion.isNotBlank()) out["node_version"] = appVersion.take(32)
        out["source"] = "android-node"
        return out
    }
}

/** Closed typed event set (mirrors ANDROID_EVENTS in android.py).
 *  Device text (notification bodies, SSIDs) is untrusted data. */
enum class NodeEvent(val wire: String) {
    CONNECTED("connected"),
    DISCONNECTED("disconnected"),
    BATTERY_CHANGED("battery.changed"),
    BATTERY_LOW("battery.low"),
    NETWORK_CHANGED("network.changed"),
    LOCATION_CHANGED("location.changed"),
    APP_OPENED("app.opened"),
    NOTIFICATION_RECEIVED("notification.received"),
    SCREEN_STATE_CHANGED("screen.state_changed"),
    SENSOR_UPDATED("sensor.updated"),
    PERMISSION_CHANGED("permission.changed");

    companion object {
        fun fromWire(wire: String): NodeEvent? =
            entries.firstOrNull { it.wire == wire }
    }
}
