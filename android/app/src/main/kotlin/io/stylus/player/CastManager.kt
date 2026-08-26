package io.stylus.player

import android.content.Context
import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URL
import java.net.URLDecoder
import javax.xml.parsers.DocumentBuilderFactory
import org.w3c.dom.Document

/**
 * Cast to DLNA renderers (Smart TVs, Firestick, etc).
 *
 * SSDP discovery + AVTransport SOAP to push a local HTTP stream.
 */
object CastManager {

    data class DlnaDevice(
        val name: String,
        val location: String,  // description URL
        val controlURL: String,
        val uuid: String
    )

    private const val TAG = "CastManager"
    private const val SSDP_ADDR = "239.255.255.250"
    private const val SSDP_PORT = 1900
    private const val SERVER_PORT = 8192  // local HTTP server for streaming

    private var serverSocket: ServerSocket? = null
    private var serverThread: Thread? = null
    @Volatile var isStreaming = false
        private set
    private var currentContentUri: android.net.Uri? = null
    private var currentResolver: android.content.ContentResolver? = null

    /** Discover DLNA renderers on the local network */
    fun discover(timeoutMs: Long = 3000, onResult: (List<DlnaDevice>) -> Unit) {
        Thread {
            val devices = mutableListOf<DlnaDevice>()
            try {
                val ssdpMsg = "M-SEARCH * HTTP/1.1\r\n" +
                    "HOST: $SSDP_ADDR:$SSDP_PORT\r\n" +
                    "MAN: \"ssdp:discover\"\r\n" +
                    "MX: 3\r\n" +
                    "ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n" +
                    "\r\n"

                val socket = DatagramSocket()
                socket.soTimeout = timeoutMs.toInt()
                val group = InetAddress.getByName(SSDP_ADDR)
                val data = ssdpMsg.toByteArray()
                val packet = DatagramPacket(data, data.size, group, SSDP_PORT)
                socket.send(packet)

                val buf = ByteArray(4096)
                val seen = mutableSetOf<String>()
                val end = System.currentTimeMillis() + timeoutMs

                while (System.currentTimeMillis() < end) {
                    try {
                        val recv = DatagramPacket(buf, buf.size)
                        socket.receive(recv)
                        val resp = String(recv.data, 0, recv.length)
                        val loc = extractHeader(resp, "LOCATION")
                        if (loc != null && loc !in seen) {
                            seen.add(loc)
                            val device = parseDeviceDescription(loc)
                            if (device != null) devices.add(device)
                        }
                    } catch (_: java.net.SocketTimeoutException) { break }
                }
                socket.close()
            } catch (e: Exception) {
                Log.w(TAG, "Discovery error: $e")
            }
            onResult(devices)
        }.start()
    }

    /** Start local HTTP server and push playback to a DLNA device */
    fun castFile(context: Context, contentUri: android.net.Uri, device: DlnaDevice, onResult: (Boolean) -> Unit) {
        Thread {
            try {
                // Start local server
                stopServer()
                // Store the content URI and resolver for the HTTP handler
                currentContentUri = contentUri
                currentResolver = context.contentResolver
                serverSocket = ServerSocket(SERVER_PORT)
                isStreaming = true

                serverThread = Thread {
                    while (isStreaming) {
                        try {
                            val client = serverSocket?.accept() ?: break
                            handleHttpClient(client)
                        } catch (_: Exception) { break }
                    }
                }.also { it.isDaemon = true; it.start() }

                val localIp = getLocalIp() ?: "127.0.0.1"
                val mediaUrl = "http://$localIp:$SERVER_PORT/stream"

                // Push to device via AVTransport
                val success = avTransportSetUri(device, mediaUrl)
                if (success) avTransportPlay(device)
                onResult(success)
            } catch (e: Exception) {
                Log.w(TAG, "Cast error: $e")
                onResult(false)
            }
        }.start()
    }

    fun stopCast() {
        isStreaming = false
        stopServer()
    }

    private fun stopServer() {
        try { serverSocket?.close() } catch (_: Exception) {}
        serverSocket = null
        try { serverThread?.join(500) } catch (_: Exception) {}
        serverThread = null
        isStreaming = false
    }

    private fun handleHttpClient(client: Socket) {
        try {
            val reader = BufferedReader(InputStreamReader(client.getInputStream()))
            val requestLine = reader.readLine() ?: return
            val method = requestLine.split(" ").firstOrNull() ?: ""
            var rangeHeader: String? = null
            while (true) {
                val line = reader.readLine() ?: break
                if (line.isEmpty()) break
                if (line.lowercase().startsWith("range:")) rangeHeader = line.substringAfter(":").trim()
            }

            val uri = currentContentUri
            val resolver = currentResolver
            if (uri == null || resolver == null) { sendHttp404(client); return }

            // Determine mime type and file size
            val mime = resolver.getType(uri) ?: "audio/flac"
            val fileSize = try {
                val pfd = resolver.openFileDescriptor(uri, "r")
                val size = pfd?.statSize ?: -1L
                pfd?.close()
                size
            } catch (_: Exception) { -1L }

            // Parse Range header (e.g. "bytes=0-" or "bytes=12345-")
            var start = 0L
            var end = if (fileSize > 0) fileSize - 1 else -1L
            if (rangeHeader != null && fileSize > 0) {
                val rangeMatch = Regex("bytes=(\\d*)-(\\d*)").find(rangeHeader)
                if (rangeMatch != null) {
                    val s = rangeMatch.groupValues[1].toLongOrNull()
                    val e = rangeMatch.groupValues[2].toLongOrNull()
                    start = s ?: 0L
                    end = e ?: (fileSize - 1)
                    if (start > end || start >= fileSize) {
                        sendHttp416(client, fileSize)
                        return
                    }
                }
            }

            val contentLen = end - start + 1
            val os = client.getOutputStream()

            if (rangeHeader != null && fileSize > 0) {
                // Partial content response
                val header = "HTTP/1.1 206 Partial Content\r\n" +
                    "Content-Type: $mime\r\n" +
                    "Content-Length: $contentLen\r\n" +
                    "Content-Range: bytes $start-$end/$fileSize\r\n" +
                    "Accept-Ranges: bytes\r\n" +
                    "Connection: close\r\n" +
                    "\r\n"
                os.write(header.toByteArray())
            } else {
                val lenHeader = if (fileSize > 0) "Content-Length: $fileSize\r\n" else ""
                val header = "HTTP/1.1 200 OK\r\n" +
                    "Content-Type: $mime\r\n" +
                    lenHeader +
                    "Accept-Ranges: bytes\r\n" +
                    "Connection: close\r\n" +
                    "\r\n"
                os.write(header.toByteArray())
            }
            os.flush()

            // Stream the content
            val input = resolver.openInputStream(uri)
            if (input == null) { sendHttp404(client); return }

            // Skip to start position for range requests
            if (start > 0) {
                var skipped = 0L
                while (skipped < start) {
                    val toSkip = (start - skipped).coerceAtMost(8192L)
                    val s = input.skip(toSkip)
                    if (s <= 0) break
                    skipped += s
                }
            }

            val buf = ByteArray(8192)
            var remaining = contentLen
            var read = 0
            while (remaining > 0 && input.read(buf, 0, (if (remaining < buf.size) remaining else buf.size.toLong()).toInt()).also { read = it } != -1) {
                os.write(buf, 0, read)
                remaining -= read
            }
            os.flush()
            input.close()
            client.close()
        } catch (e: Exception) {
            Log.w(TAG, "HTTP handler: $e")
            try { client.close() } catch (_: Exception) {}
        }
    }

    private fun sendHttp404(client: Socket) {
        try {
            val resp = "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
            client.getOutputStream().write(resp.toByteArray())
            client.close()
        } catch (_: Exception) {}
    }

    private fun sendHttp416(client: Socket, totalSize: Long) {
        try {
            val resp = "HTTP/1.1 416 Range Not Satisfiable\r\nContent-Range: bytes */$totalSize\r\nContent-Length: 0\r\n\r\n"
            client.getOutputStream().write(resp.toByteArray())
            client.close()
        } catch (_: Exception) {}
    }

    private fun avTransportSetUri(device: DlnaDevice, uri: String): Boolean {
        val body = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <CurrentURI>$uri</CurrentURI>
      <CurrentURIMetaData></CurrentURIMetaData>
    </u:SetAVTransportURI>
  </s:Body>
</s:Envelope>"""
        return sendSoap(device.controlURL, "SetAVTransportURI", body)
    }

    private fun avTransportPlay(device: DlnaDevice): Boolean {
        val body = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <Speed>1</Speed>
    </u:Play>
  </s:Body>
</s:Envelope>"""
        return sendSoap(device.controlURL, "Play", body)
    }

    private fun sendSoap(url: String, action: String, body: String): Boolean {
        try {
            val u = URL(url)
            val conn = u.openConnection() as java.net.HttpURLConnection
            conn.requestMethod = "POST"
            conn.setRequestProperty("Content-Type", "text/xml; charset=\"utf-8\"")
            conn.setRequestProperty("SOAPACTION", "\"urn:schemas-upnp-org:service:AVTransport:1#$action\"")
            conn.doOutput = true
            conn.connectTimeout = 5000
            conn.readTimeout = 5000
            val os: OutputStream = conn.outputStream
            os.write(body.toByteArray(Charsets.UTF_8))
            os.flush()
            val code = conn.responseCode
            conn.disconnect()
            return code == 200
        } catch (e: Exception) {
            Log.w(TAG, "SOAP $action failed: $e")
            return false
        }
    }

    private fun parseDeviceDescription(location: String): DlnaDevice? {
        try {
            val url = URL(location)
            val conn = url.openConnection()
            conn.connectTimeout = 3000
            conn.readTimeout = 3000
            val doc = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(conn.getInputStream())
            val deviceNodes = doc.getElementsByTagName("device")
            if (deviceNodes.length == 0) return null
            val deviceNode = deviceNodes.item(0)

            val friendlyName = getTagText(deviceNode, "friendlyName") ?: "Unknown"
            val uuid = getTagText(deviceNode, "UDN") ?: ""

            // Check if it's a MediaRenderer
            val deviceType = getTagText(deviceNode, "deviceType") ?: ""
            if (!deviceType.contains("MediaRenderer")) return null

            // Find AVTransport control URL
            val serviceNodes = doc.getElementsByTagName("service")
            var controlURL: String? = null
            for (i in 0 until serviceNodes.length) {
                val svc = serviceNodes.item(i)
                val svcType = getTagText(svc, "serviceType") ?: ""
                if (svcType.contains("AVTransport")) {
                    val ctrlPath = getTagText(svc, "controlURL") ?: continue
                    // Build absolute URL relative to description location
                    controlURL = if (ctrlPath.startsWith("http")) ctrlPath
                    else "${url.protocol}://${url.host}:${url.port}$ctrlPath"
                    break
                }
            }
            if (controlURL == null) return null
            return DlnaDevice(friendlyName, location, controlURL, uuid)
        } catch (e: Exception) {
            Log.w(TAG, "Parse error: $e")
            return null
        }
    }

    private fun getTagText(parent: org.w3c.dom.Node, tag: String): String? {
        val nodes = (parent as org.w3c.dom.Element).getElementsByTagName(tag)
        return if (nodes.length > 0) nodes.item(0).textContent?.trim() else null
    }

    private fun extractHeader(response: String, header: String): String? {
        for (line in response.lines()) {
            if (line.lowercase().startsWith("$header:".lowercase())) {
                return line.substringAfter(":").trim()
            }
        }
        return null
    }

    private fun getLocalIp(): String? {
        try {
            val interfaces = java.net.NetworkInterface.getNetworkInterfaces()
            while (interfaces.hasMoreElements()) {
                val intf = interfaces.nextElement()
                if (intf.isLoopback || !intf.isUp) continue
                val addrs = intf.inetAddresses
                while (addrs.hasMoreElements()) {
                    val addr = addrs.nextElement()
                    if (!addr.isLoopbackAddress && addr is java.net.Inet4Address) {
                        return addr.hostAddress
                    }
                }
            }
        } catch (_: Exception) {}
        return null
    }
}
