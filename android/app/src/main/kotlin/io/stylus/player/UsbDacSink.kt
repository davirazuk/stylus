package io.stylus.player

import android.content.Context
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.media.AudioManager
import android.util.Log
import androidx.media3.common.AudioAttributes
import androidx.media3.common.AuxEffectInfo
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.PlaybackParameters
import androidx.media3.exoplayer.audio.AudioSink
import java.nio.ByteBuffer
import java.util.concurrent.atomic.AtomicReference

/**
 * AudioSink que escreve o PCM DIRETO no DAC USB — o mesmo caminho do UAPP.
 *
 * Diferença brutal em relação ao AAudio/`NativeAudioSink`: este sink SÓ existe
 * quando um DAC USB está fisicamente plugado E nenhuma chamada está ativa. Sem
 * DAC, nunca chega a ser usado — a factory devolve o AudioTrack padrão. Foi o
 * que faltou na primeira tentativa (AAudio exclusive): ele pegava a saída do
 * telefone inteiro e tocava por cima de uma chamada em curso.
 *
 * Sintoma que este caminho resolve: USB DAC no Android toca 44.1k reamostrado
 * para 48k pelo HAL, ou nem toca se o DAC só fala 44.1/96k. Escrever via
 * bulkTransfer no endpoint isocrono do DAC manda o PCM na taxa/bit que o
 * arquivo tem, sem o mixer no meio.
 */
class UsbDacSink(
    private val context: Context,
    private val device: UsbDevice,
    private val connection: UsbDeviceConnection,
    private val audioOut: UsbDacPath.AudioOut
) : AudioSink {

    private var listener: AudioSink.Listener? = null
    private var intf: UsbInterface? = null
    private var endpoint: UsbEndpoint? = null
    private var sampleRate = 48000
    private var channels = 2
    private var streamEnded = false
    private var frameCount = 0L
    private var positionUs = 0L
    private val parameters = AtomicReference(PlaybackParameters.DEFAULT)
    private val attributes = AtomicReference(AudioAttributes.DEFAULT)
    private var audioSessionId = 0

    override fun setListener(listener: AudioSink.Listener) { this.listener = listener }

    override fun supportsFormat(format: Format): Boolean =
        format.sampleRate != Format.NO_VALUE && format.channelCount != Format.NO_VALUE

    override fun getFormatSupport(format: Format) = AudioSink.SINK_FORMAT_SUPPORTED_DIRECTLY

    override fun getCurrentPositionUs(sourceEnded: Boolean) = positionUs

    override fun configure(
        inputFormat: Format,
        specifiedBufferSizeUs: Int,
        outputChannels: IntArray?
    ) {
        sampleRate = inputFormat.sampleRate
        channels = outputChannels?.firstOrNull() ?: 2
        if (channels <= 0) channels = 2
        streamEnded = false
        frameCount = 0L
        positionUs = 0L

        val iface = findAudioInterface(device, audioOut.interfaceIndex)
        if (iface == null) {
            fail("interface de áudio ${audioOut.interfaceIndex} não encontrada no ${device.productName}")
            return
        }
        intf = iface
        endpoint = findEndpoint(iface, audioOut.endpoint.address)
        if (endpoint == null) {
            fail("endpoint OUT ${audioOut.endpoint.address} não encontrado")
            return
        }

        // claimInterface(force=true) coloca o app no controle exclusivo do DAC.
        if (!connection.claimInterface(iface, true)) {
            fail("claimInterface(${iface.id}) recusada — DAC em uso por outro app")
            return
        }
        setSampleRateControl(sampleRate, iface, endpoint!!)
        Log.i("BitPerfect", "usb: ${device.productName} rate=${sampleRate} ch=$channels " +
            "ep=0x${endpoint!!.address.toString(16)} iso=${endpoint!!.type == UsbConstants.USB_ENDPOINT_XFER_ISOC}")
    }

    private fun fail(msg: String) {
        Log.e("BitPerfect", "usb: $msg")
        val fmt = Format.Builder().setSampleRate(sampleRate).setChannelCount(channels).build()
        listener?.onAudioSinkError(
            AudioSink.InitializationException(0, 1, 0, audioSessionId, fmt, false,
                IllegalStateException(msg))
        )
    }

    // Pedaço do firmware de streaming do UAC: antes de tocar o HAL Android
    // configura o DAC com o clock pedido. Sem isso o DAC toca no clock que
    // quiser (quase sempre 48k). Aqui: SET_CUR de sampling freq no controlador
    // da interface — best-effort, na falha o log avisa e segue (alguns DACs
    // só aceitam pelo driver do sistema, que já os abriu).
    private fun setSampleRateControl(rate: Int, iface: UsbInterface, ep: UsbEndpoint) {
        // bmRequestType: host->device (0x20), class (0x00), interface (0x01) => 0x21
        // bRequest SET_CUR = 0x01, wValue = wIndex = sampling freq (0x0100)
        // wValue = (control selector<<8) | endpoint, CS_SAM_FREQ = 1
        val bmRequestType = 0x21
        val bRequest = 0x01 // SET_CUR
        val wValue = (1 shl 8) or (ep.address and 0x0f)
        val wIndex = iface.id
        val freq = byteArrayOf(
            (rate and 0xff).toByte(),
            ((rate shr 8) and 0xff).toByte(),
            ((rate shr 16) and 0xff).toByte(),
            0
        )
        val sent = connection.controlTransfer(bmRequestType, bRequest, wValue, wIndex, freq, freq.size, 1000)
        Log.d("BitPerfect", "usb: SET_CUR freq $rate -> $sent bytes ($bmRequestType/$bRequest/$wValue/$wIndex)")
    }

    override fun handleBuffer(buffer: ByteBuffer, presentationTimeUs: Long, encoding: Int): Boolean {
        val conn = connection ?: return true
        val ep = endpoint ?: return true
        val fileIsFloat = encoding == C.ENCODING_PCM_FLOAT
        val frames = PcmConvert.frameCount(buffer, fileIsFloat, channels)
        if (frames <= 0) { buffer.position(buffer.limit()); return true }

        // O DAC fala i16 na prática (USB audio trafega PCM 16-bit por pacote);
        // float só se o caminho inteiro for float — aqui é sempre i16 no cabo.
        val si = PcmConvert.toShort(buffer, channels, fileIsFloat) ?: return true
        val payload = ByteBuffer.wrap(ByteArray(si.size * 2))
        si.forEach { payload.putShort(it) }
        payload.flip()
        val bytes = payload.array()
        val pkt = ep.maxPacketSize.coerceAtMost(1024)
        val total = bytes.size
        var off = 0
        var framesDone = 0
        while (off < total) {
            val len = minOf(pkt, total - off)
            val n = conn.bulkTransfer(ep, bytes, off, len, 20)
            if (n > 0) {
                off += n
                framesDone = (off / (channels * 2)).coerceAtMost(frames)
            } else {
                break
            }
        }
        frameCount += framesDone
        positionUs = frameCount * 1_000_000L / sampleRate
        return framesDone == frames
    }

    override fun play() {}
    override fun handleDiscontinuity() { frameCount = 0L; positionUs = 0L }
    override fun playToEndOfStream() { streamEnded = true }
    override fun isEnded() = streamEnded
    override fun hasPendingData() = !streamEnded && frameCount > 0
    override fun setPlaybackParameters(p: PlaybackParameters) {
        parameters.set(p)
        if (p.speed != 1f || p.pitch != 1f)
            listener?.onAudioSinkError(IllegalArgumentException("USB bit-perfect: sem speed/pitch"))
    }
    override fun getPlaybackParameters() = parameters.get()
    override fun setSkipSilenceEnabled(enabled: Boolean) {}
    override fun getSkipSilenceEnabled() = false
    override fun setAudioAttributes(a: AudioAttributes) { attributes.set(a) }
    override fun getAudioAttributes() = attributes.get()
    override fun setAudioSessionId(id: Int) { audioSessionId = id }
    override fun setAuxEffectInfo(auxEffectInfo: AuxEffectInfo) {}
    override fun enableTunnelingV21() {}
    override fun disableTunneling() {}
    override fun setVolume(volume: Float) {}

    override fun pause() {}

    override fun flush() {
        frameCount = 0L
        positionUs = 0L
        streamEnded = false
    }

    override fun reset() {
        try { intf?.let { connection?.releaseInterface(it) } } catch (_: Exception) {}
        try { connection?.close() } catch (_: Exception) {}
        intf = null
        endpoint = null
    }

    private fun findAudioInterface(dev: UsbDevice, wantedIndex: Int): UsbInterface? {
        for (i in 0 until dev.interfaceCount) {
            val ifc = dev.getInterface(i)
            if (ifc.id == wantedIndex) return ifc
        }
        return null
    }

    private fun findEndpoint(ifc: UsbInterface, wantedAddress: Int): UsbEndpoint? {
        for (i in 0 until ifc.endpointCount) {
            val ep = ifc.getEndpoint(i)
            if (ep.address == wantedAddress) return ep
        }
        return null
    }

    companion object {
        // Abre o DAC se (a) tem permissão do UsbManager, (b) é interface de
        // áudio com OUT, e (c) não há chamada ativa — nunca toca por cima de
        // uma ligação. Retorna null e loga o motivo quando qualquer check falha.
        fun tryOpen(context: Context): UsbDacSink? {
            val usb = context.getSystemService(Context.USB_SERVICE) as UsbManager

            // Trava de chamada: áudio de chamada nunca é ok para exclusive.
            val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val mode = am.mode
            if (mode == AudioManager.MODE_IN_CALL || mode == AudioManager.MODE_IN_COMMUNICATION) {
                Log.i("BitPerfect", "usb DAC presente mas chamada ativa (mode=$mode) — sem exclusive")
                return null
            }

            val devices = usb.deviceList
            var dac: UsbDevice? = null
            var audioOut: UsbDacPath.AudioOut? = null
            for (dev in devices.values) {
                val audioIfaces = mutableListOf<Pair<Int, List<UsbDacPath.Endpoint>>>()
                for (i in 0 until dev.interfaceCount) {
                    val ifc = dev.getInterface(i)
                    if (ifc.interfaceClass != UsbConstants.USB_CLASS_AUDIO) continue
                    val eps = (0 until ifc.endpointCount).map { j -> ifc.getEndpoint(j) }
                        .map { UsbDacPath.Endpoint(it.address, it.type, it.maxPacketSize) }
                    audioIfaces.add(i to eps)
                }
                val p = UsbDacPath.find(audioIfaces)
                if (p != null) { dac = dev; audioOut = p; break }
            }
            if (dac == null || audioOut == null) return null

            if (!usb.hasPermission(dac)) {
                Log.i("BitPerfect", "usb DAC ${dac.productName} presente sem permissão — USB_DEVICE_ATTACHED precisa do OK do usuário")
                return null
            }
            val conn = usb.openDevice(dac) ?: run {
                Log.e("BitPerfect", "usb: openDevice(${dac.productName}) falhou")
                return null
            }
            return UsbDacSink(context, dac, conn, audioOut!!)
        }
    }
}