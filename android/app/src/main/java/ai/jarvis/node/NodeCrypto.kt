package ai.jarvis.node

import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** HMAC-SHA256 challenge answers. The device secret never leaves the
 *  phone except as a challenge response; challenges are single-use and
 *  server-rotated, so replays fail. Mirrors
 *  DeviceAuthenticator.answer/verify in socket_transport.py. */
object NodeCrypto {
    fun answerHex(secret: String, challenge: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        val out = mac.doFinal(challenge.toByteArray(Charsets.UTF_8))
        return out.joinToString("") { "%02x".format(it) }
    }
}
