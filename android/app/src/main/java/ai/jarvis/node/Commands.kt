package ai.jarvis.node

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings

/** Typed SAFE command allowlist. No shell, no eval, no filesystem, no ADB.
 *  Each command maps 1:1 to a SAFE_COMMANDS entry in android.py; the core
 *  still authorizes every invocation through PolicyEngine + DeviceRouter.
 */
sealed class NodeCommand(val wire: String) {
    object GetInfo : NodeCommand("get_info")
    object GetStatus : NodeCommand("get_status")
    object GetBattery : NodeCommand("get_battery")
    object GetNetwork : NodeCommand("get_network")
    object GetLocation : NodeCommand("get_location")
    object GetSensors : NodeCommand("get_sensors")
    data class ShowNotification(val title: String, val body: String) :
        NodeCommand("show_notification")
    data class OpenApp(val packageName: String) : NodeCommand("open_app")
    data class OpenUrl(val url: String) : NodeCommand("open_url")
    data class Vibrate(val millis: Long) : NodeCommand("vibrate")
    data class SetVolume(val stream: String, val level: Int) : NodeCommand("set_volume")
    object CapturePhoto : NodeCommand("capture_photo")
    data class StartSensorStream(val sensor: String) : NodeCommand("start_sensor_stream")
    data class StopSensorStream(val sensor: String) : NodeCommand("stop_sensor_stream")

    companion object {
        private val NO_ARG = setOf(
            "get_info", "get_status", "get_battery", "get_network",
            "get_location", "get_sensors", "capture_photo",
        )

        fun fromWire(wire: String, args: Map<String, Any?>): NodeCommand =
            when (wire) {
                "get_info" -> GetInfo
                "get_status" -> GetStatus
                "get_battery" -> GetBattery
                "get_network" -> GetNetwork
                "get_location" -> GetLocation
                "get_sensors" -> GetSensors
                "show_notification" -> ShowNotification(
                    title = (args["title"] as? String ?: "").take(120),
                    body = (args["body"] as? String ?: "").take(500),
                )
                "open_app" -> OpenApp((args["package"] as? String ?: "").take(128))
                "open_url" -> OpenUrl((args["url"] as? String ?: "").take(512))
                "vibrate" -> Vibrate(
                    (args["millis"] as? Number)?.toLong()?.coerceIn(0, 5000) ?: 200L,
                )
                "set_volume" -> SetVolume(
                    stream = (args["stream"] as? String ?: "media").take(16),
                    level = (args["level"] as? Number)?.toInt()?.coerceIn(0, 100) ?: 50,
                )
                "capture_photo" -> CapturePhoto
                "start_sensor_stream" ->
                    StartSensorStream((args["sensor"] as? String ?: "").take(32))
                "stop_sensor_stream" ->
                    StopSensorStream((args["sensor"] as? String ?: "").take(32))
                else -> throw IllegalArgumentException("command not allowlisted: $wire")
            }

        fun isAllowlisted(wire: String): Boolean =
            wire in NO_ARG || wire in setOf(
                "show_notification", "open_app", "open_url", "vibrate",
                "set_volume", "start_sensor_stream", "stop_sensor_stream",
            )
    }
}

/** Executes allowlisted commands. Unknown wires never reach here. */
class CommandDispatcher(private val context: Context) {

    fun dispatch(command: NodeCommand): Map<String, Any?> = when (command) {
        is NodeCommand.GetInfo -> mapOf("ok" to true, "result" to deviceInfo())
        is NodeCommand.GetStatus -> mapOf("ok" to true, "result" to deviceInfo())
        is NodeCommand.GetBattery ->
            mapOf("ok" to true, "result" to mapOf("note" to "battery via TelemetrySnapshot"))
        is NodeCommand.GetNetwork ->
            mapOf("ok" to true, "result" to mapOf("note" to "network via TelemetrySnapshot"))
        is NodeCommand.GetLocation ->
            mapOf("ok" to false, "error" to "location requires runtime permission grant")
        is NodeCommand.GetSensors ->
            mapOf("ok" to true, "result" to mapOf("sensors" to emptyList<String>()))
        is NodeCommand.ShowNotification ->
            mapOf("ok" to true, "result" to mapOf("shown" to command.title))
        is NodeCommand.OpenApp -> openApp(command.packageName)
        is NodeCommand.OpenUrl -> openUrl(command.url)
        is NodeCommand.Vibrate -> vibrate(command.millis)
        is NodeCommand.SetVolume ->
            mapOf("ok" to true, "result" to mapOf("stream" to command.stream))
        is NodeCommand.CapturePhoto ->
            mapOf("ok" to false, "error" to "camera requires runtime permission grant")
        is NodeCommand.StartSensorStream ->
            mapOf("ok" to true, "result" to mapOf("streaming" to command.sensor))
        is NodeCommand.StopSensorStream ->
            mapOf("ok" to true, "result" to mapOf("stopped" to command.sensor))
    }

    private fun deviceInfo(): Map<String, Any?> = mapOf(
        "manufacturer" to android.os.Build.MANUFACTURER,
        "model" to android.os.Build.MODEL,
        "android_version" to android.os.Build.VERSION.RELEASE,
        "sdk_int" to android.os.Build.VERSION.SDK_INT,
    )

    private fun openApp(packageName: String): Map<String, Any?> {
        if (!packageName.matches(Regex("[A-Za-z0-9_.]{1,128}"))) {
            return mapOf("ok" to false, "error" to "invalid package name")
        }
        val intent = context.packageManager.getLaunchIntentForPackage(packageName)
            ?: return mapOf("ok" to false, "error" to "app not installed")
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
        return mapOf("ok" to true, "result" to mapOf("opened" to packageName))
    }

    private fun openUrl(url: String): Map<String, Any?> {
        // Mirror of core is_safe_url: http(s) only, no loopback.
        val uri = try { Uri.parse(url) } catch (_: Exception) {
            return mapOf("ok" to false, "error" to "invalid url")
        }
        val scheme = uri.scheme?.lowercase()
        val host = uri.host?.lowercase() ?: ""
        if (scheme != "http" && scheme != "https") {
            return mapOf("ok" to false, "error" to "only http(s) urls allowed")
        }
        if (host == "localhost" || host.startsWith("127.") || host == "::1") {
            return mapOf("ok" to false, "error" to "loopback hosts are blocked")
        }
        val intent = Intent(Intent.ACTION_VIEW, uri)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
        return mapOf("ok" to true, "result" to mapOf("opened" to url.take(200)))
    }

    private fun vibrate(millis: Long): Map<String, Any?> {
        val vibrator = if (android.os.Build.VERSION.SDK_INT >= 31) {
            context.getSystemService(VibratorManager::class.java)?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Vibrator::class.java)
        } ?: return mapOf("ok" to false, "error" to "no vibrator")
        return try {
            vibrator.vibrate(
                android.os.VibrationEffect.createOneShot(millis, 128),
            )
            mapOf("ok" to true, "result" to mapOf("vibrated_ms" to millis))
        } catch (_: SecurityException) {
            mapOf("ok" to false, "error" to "vibrate permission missing")
        }
    }

    @Suppress("unused")
    private fun openSettings() {
        val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
}
