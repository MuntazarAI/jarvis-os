package ai.jarvis.node

import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread
import kotlin.math.min

/** Logging indirection: android.util.Log on device, but android.jar is a
 *  throwing stub under plain JVM unit tests — so every call is
 *  stub-safe (and the hook is swappable for test observation). */
object PeerLog {
    var debug: (tag: String, msg: String) -> Unit = { tag, msg ->
        try {
            android.util.Log.d(tag, msg)
        } catch (_: Throwable) {
            // JVM unit-test stub: drop, never crash the peer.
        }
    }
    var error: (tag: String, msg: String) -> Unit = { tag, msg ->
        try {
            android.util.Log.e(tag, msg)
        } catch (_: Throwable) {
            // JVM unit-test stub: drop, never crash the peer.
        }
    }
}

/**
 * Blocking TCP client for the JARVIS fabric socket transport.
 *
 * - [send] performs a synchronous request/reply keyed by correlation id.
 * - Unsolicited server frames go to [onRequest] (host-initiated commands).
 * - Reconnect uses bounded exponential backoff (1s -> 60s); after an
 *   authentication failure the peer stops retrying and reports the state.
 *
 * All callbacks fire on internal threads; callers must hop to their own
 * executor (e.g. the NodeService handler) before touching UI or store.
 */
class SocketPeer(
    private val onRequest: (json: String) -> String?,
    private val onState: (state: ConnState) -> Unit = {},
) {
    enum class ConnState { CONNECTING, CONNECTED, DISCONNECTED, AUTH_FAILED, STOPPED }

    @Volatile private var socket: Socket? = null
    @Volatile private var nodeId: String = ""
    @Volatile private var host: String = ""
    @Volatile private var port: Int = 0
    private val running = AtomicBoolean(false)
    private val readerDone = AtomicBoolean(true)
    private val pending = LinkedHashMap<String, (String?) -> Unit>()
    private val pendingLock = Object()
    private var backoffMs: Long = 1_000L

    companion object {
        const val CONNECT_TIMEOUT_MS: Int = 10_000
        const val READ_TIMEOUT_MS: Int = 15_000
        const val MAX_BACKOFF_MS: Long = 60_000L
        const val MAX_PENDING: Int = 32
    }

    fun start(host: String, port: Int, nodeId: String) {
        if (!running.compareAndSet(false, true)) return
        this.host = host
        this.port = port
        this.nodeId = nodeId
        backoffMs = 1_000L
        thread(name = "socket-peer-connect", isDaemon = true) { connectLoop() }
    }

    fun stop() {
        running.set(false)
        try { socket?.close() } catch (_: IOException) { }
        socket = null
        onState(ConnState.STOPPED)
    }

    /** Synchronous request/reply. Returns the reply JSON string, or null on timeout/close. */
    fun send(messageJson: String, messageId: String, timeoutMs: Long = READ_TIMEOUT_MS.toLong()): String? {
        val sock = socket ?: return null
        var slot: ((String?) -> Unit)? = null
        val replyBox = arrayOfNulls<String>(1)
        val done = Object()
        synchronized(pendingLock) {
            if (pending.size >= MAX_PENDING) return null
            slot = { reply: String? ->
                synchronized(done) {
                    replyBox[0] = reply
                    done.notifyAll()
                }
            }
            pending[messageId] = slot!!
        }
        try {
            sock.getOutputStream().write(SocketLink.encode(messageJson))
            sock.getOutputStream().flush()
        } catch (_: IOException) {
            synchronized(pendingLock) { pending.remove(messageId) }
            return null
        }
        synchronized(done) {
            val deadline = System.currentTimeMillis() + timeoutMs
            while (replyBox[0] == null) {
                val wait = deadline - System.currentTimeMillis()
                if (wait <= 0) break
                try { (done as Object).wait(wait) } catch (_: InterruptedException) { break }
            }
        }
        synchronized(pendingLock) { pending.remove(messageId) }
        return replyBox[0]
    }

    fun notifyAuthFailed() {
        running.set(false)
        try { socket?.close() } catch (_: IOException) { }
        onState(ConnState.AUTH_FAILED)
    }

    private fun connectLoop() {
        while (running.get()) {
            onState(ConnState.CONNECTING)
            try {
                PeerLog.debug("SocketPeer", "dial $host:$port")
                val sock = Socket()
                sock.tcpNoDelay = true
                sock.soTimeout = READ_TIMEOUT_MS
                sock.connect(InetSocketAddress(host, port), CONNECT_TIMEOUT_MS)
                socket = sock
                backoffMs = 1_000L
                PeerLog.debug("SocketPeer", "connected $host:$port")
                onState(ConnState.CONNECTED)
                readerDone.set(false)
                readLoop(sock)
                readerDone.set(true)
            } catch (e: IOException) {
                PeerLog.debug("SocketPeer", "dial failed: ${e.javaClass.simpleName}: ${e.message}")
                // fall through to backoff
            } catch (e: Exception) {
                // Non-IO failure (e.g. SecurityException): never spin silently.
                PeerLog.error("SocketPeer", "fatal dial error: ${e.javaClass.simpleName}: ${e.message}")
                running.set(false)
                onState(ConnState.DISCONNECTED)
                break
            }
            socket = null
            if (!running.get()) break
            onState(ConnState.DISCONNECTED)
            try { Thread.sleep(backoffMs) } catch (_: InterruptedException) { break }
            backoffMs = min(backoffMs * 2, MAX_BACKOFF_MS)
        }
    }

    private fun readLoop(sock: Socket) {
        val input = try { sock.getInputStream() } catch (_: IOException) { return }
        val acc = mutableListOf<Byte>()
        val chunk = ByteArray(65_536)
        try {
            while (running.get()) {
                val n = try { input.read(chunk) } catch (_: IOException) { break }
                if (n < 0) break
                for (i in 0 until n) acc.add(chunk[i])
                val arr = acc.toByteArray()
                val (frames, nextPos) = try {
                    SocketLink.decode(arr)
                } catch (_: FramingException) {
                    break // fatal: framing violated, drop connection
                }
                if (nextPos > 0) {
                    val remaining = arr.copyOfRange(nextPos, arr.size)
                    acc.clear()
                    remaining.forEach { acc.add(it) }
                }
                for (frame in frames) dispatch(frame)
            }
        } finally {
            failAllPending()
            try { sock.close() } catch (_: IOException) { }
        }
    }

    private fun dispatch(frameJson: String) {
        val corr = extractField(frameJson, "correlation_id")
        val cb: ((String?) -> Unit)? = synchronized(pendingLock) {
            if (corr.isNotEmpty()) pending.remove(corr) else null
        }
        if (cb != null) {
            cb(frameJson)
            return
        }
        val replyJson = try { onRequest(frameJson) } catch (_: Exception) { null }
        if (replyJson != null) {
            try {
                socket?.getOutputStream()?.let {
                    it.write(SocketLink.encode(replyJson))
                    it.flush()
                }
            } catch (_: IOException) { }
        }
    }

    private fun failAllPending() {
        val cbs = synchronized(pendingLock) {
            val all = pending.values.toList()
            pending.clear()
            all
        }
        cbs.forEach { try { it(null) } catch (_: Exception) { } }
    }

    /** Minimal string-field extractor for routing only (full parse is the caller's job). */
    internal fun extractField(json: String, field: String): String {
        val key = "\"$field\""
        val ki = json.indexOf(key)
        if (ki < 0) return ""
        var i = json.indexOf(':', ki + key.length)
        if (i < 0) return ""
        i++
        while (i < json.length && json[i].isWhitespace()) i++
        if (i >= json.length || json[i] != '"') return ""
        i++
        val sb = StringBuilder()
        while (i < json.length) {
            val c = json[i]
            if (c == '\\' && i + 1 < json.length) {
                sb.append(json[i + 1])
                i += 2
                continue
            }
            if (c == '"') break
            sb.append(c)
            i++
        }
        return sb.toString()
    }
}
