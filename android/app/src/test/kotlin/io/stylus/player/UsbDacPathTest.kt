package io.stylus.player

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class UsbDacPathTest {

    private fun ep(addr: Int, type: Int, pkt: Int) = UsbDacPath.Endpoint(addr, type, pkt)

    @Test
    fun `prefere isocrono sobre bulk`() {
        val path = UsbDacPath.find(listOf(
            0 to listOf(ep(0x01, UsbDacPath.TYPE_ISOCHRONOUS, 192), ep(0x02, UsbDacPath.TYPE_BULK, 512))
        ))
        assertNotNull(path)
        assertEquals(UsbDacPath.TYPE_ISOCHRONOUS, path!!.endpoint.type)
        assertEquals(0x01, path.endpoint.address)
    }

    @Test
    fun `maior pacote isocrono vence`() {
        val path = UsbDacPath.find(listOf(
            0 to listOf(ep(0x01, UsbDacPath.TYPE_ISOCHRONOUS, 96), ep(0x02, UsbDacPath.TYPE_ISOCHRONOUS, 256))
        ))
        assertEquals(256, path!!.endpoint.maxPacketSize)
        assertEquals(0x02, path.endpoint.address)
    }

    @Test
    fun `ignora endpoint IN`() {
        val path = UsbDacPath.find(listOf(
            0 to listOf(ep(0x81, UsbDacPath.TYPE_ISOCHRONOUS, 192))
        ))
        assertNull(path)
    }

    @Test
    fun `vai pra proxima interface se a primeira so tem IN`() {
        val path = UsbDacPath.find(listOf(
            0 to listOf(ep(0x81, UsbDacPath.TYPE_ISOCHRONOUS, 192)),
            1 to listOf(ep(0x01, UsbDacPath.TYPE_ISOCHRONOUS, 192))
        ))
        assertNotNull(path)
        assertEquals(1, path!!.interfaceIndex)
    }

    @Test
    fun `aceita so bulk quando nao tem isocrono`() {
        val path = UsbDacPath.find(listOf(
            0 to listOf(ep(0x02, UsbDacPath.TYPE_BULK, 512))
        ))
        assertNotNull(path)
        assertEquals(UsbDacPath.TYPE_BULK, path!!.endpoint.type)
    }
}