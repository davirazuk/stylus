package io.stylus.player

/**
 * Seleção do caminho de saída USB p/ o DAC — lógica PURA, sem classes Android,
 * para ser testada no host JVM. O Android (UsbManager.UsbDevice) só fornece os
 * valores; esta função decide. Mesma ideia do UAPP: interface de áudio com
 * endpoint OUT, dando prioridade a isocrono (UAC1/UAC2) e aceitando bulk como
 * fallback honesto (Algumas Fabricas > USBaudio limpas de isocrono).
 */
object UsbDacPath {

    // Direções/endpoints: direção "in" no byte alto do bEndpointAddress.
    const val TYPE_ISOCHRONOUS = 0x01
    const val TYPE_BULK = 0x02
    const val DIR_IN = 0x80

    const val USB_CLASS_AUDIO = 2

    data class Endpoint(val address: Int, val type: Int, val maxPacketSize: Int)
    data class AudioOut(val interfaceIndex: Int, val endpoint: Endpoint)

    // Da lista de interfaces de áudio (já filtradas por classe==AUDIO), escolhe
    // a primeira com endpoint OUT. Retorna null se não houver. Préferencia:
    // isocrono > bulk, e dentro do tipo, o mais largo (mais banda).
    fun find(
        interfaces: List<Pair<Int, List<Endpoint>>>
    ): AudioOut? {
        for ((ifaceIdx, eps) in interfaces) {
            val best = eps.filter { it.address and DIR_IN == 0 }
                .minWithOrNull(compareBy(
                    { if (it.type == TYPE_ISOCHRONOUS) 0 else 1 },
                    { -it.maxPacketSize }
                ))
                ?: continue
            return AudioOut(ifaceIdx, best)
        }
        return null
    }
}