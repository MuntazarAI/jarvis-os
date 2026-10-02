package ai.jarvis.node

/** Android permission states. Capability != permission != authorization:
 * a declared capability still needs the OS permission AND a per-command
 * core authorization before anything runs.
 */
enum class PermissionState {
    AVAILABLE,
    DENIED,
    NOT_REQUESTED,
    RESTRICTED,
    UNAVAILABLE,
}

/** The 11 node capabilities (mirrors ANDROID_CAPABILITIES in android.py). */
enum class NodeCapability(
    val wire: String,
    val androidPermission: String?,
    val risk: Double,
) {
    INFO("device.info", null, 0.1),
    STATUS("device.status", null, 0.1),
    NOTIFICATIONS("device.notifications", "android.permission.POST_NOTIFICATIONS", 0.3),
    BATTERY("device.battery", null, 0.1),
    NETWORK("device.network", "android.permission.ACCESS_NETWORK_STATE", 0.2),
    LOCATION("device.location", "android.permission.ACCESS_FINE_LOCATION", 0.6),
    CAMERA("device.camera", "android.permission.CAMERA", 0.7),
    MICROPHONE("device.microphone", "android.permission.RECORD_AUDIO", 0.7),
    SCREEN("device.screen", null, 0.5),
    INPUT("device.input", null, 0.8),
    SENSORS("device.sensors", "android.hardware.sensor.accelerometer", 0.3);

    companion object {
        fun fromWire(wire: String): NodeCapability? =
            entries.firstOrNull { it.wire == wire }
    }
}

data class CapabilityDeclaration(
    val capability: NodeCapability,
    val version: Int = 1,
    val permission: PermissionState = PermissionState.NOT_REQUESTED,
    val enabled: Boolean = true,
) {
    fun advertised(): Boolean = enabled && permission == PermissionState.AVAILABLE
}

/** Local declaration set; only advertised() entries are offered to the core. */
class CapabilityRegistry {
    private val declarations = mutableMapOf<NodeCapability, CapabilityDeclaration>()

    fun declare(declaration: CapabilityDeclaration) {
        declarations[declaration.capability] = declaration
    }

    fun updatePermission(capability: NodeCapability, state: PermissionState) {
        val current = declarations[capability] ?: return
        declarations[capability] = current.copy(permission = state)
    }

    fun setEnabled(capability: NodeCapability, enabled: Boolean) {
        val current = declarations[capability] ?: return
        declarations[capability] = current.copy(enabled = enabled)
    }

    fun advertised(): List<CapabilityDeclaration> =
        declarations.values.filter { it.advertised() }.sortedBy { it.capability.wire }

    fun all(): List<CapabilityDeclaration> =
        declarations.values.sortedBy { it.capability.wire }
}
