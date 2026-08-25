package io.stylus.player

import android.opengl.GLES30 as GL
import android.opengl.GLSurfaceView
import android.opengl.Matrix
import android.util.Log
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10
import kotlin.math.*

/**
 * OpenGL ES 3.0 turntable — matches desktop ritual.py proportions.
 *
 * Plinth (warm wood) → disc body (8 annuli, dark gradient) → groove rings
 * (96, loudness-shaded) → edge rings → label → spindle → tonearm.
 * Palette: neutral warm greys, no bloom, no phosphor.
 */
class VinylRenderer : GLSurfaceView.Renderer {

    // ── Palette from desktop vinyl.py ──
    private val BG_PLINTH = floatArrayOf(0.06f, 0.04f, 0.028f)
    private val VINYL_CORE = floatArrayOf(0.013f, 0.013f, 0.014f)
    private val VINYL_RIM = floatArrayOf(0.052f, 0.050f, 0.048f)
    private val EDGE_RING = floatArrayOf(0.28f, 0.27f, 0.26f)
    private val GROOVE_UNPLAYED = floatArrayOf(0.095f, 0.102f, 0.110f)
    private val GROOVE_PLAYED = floatArrayOf(0.190f, 0.198f, 0.208f)
    private val GROOVE_GAP = floatArrayOf(0.76f, 0.75f, 0.735f)
    private val LABEL_RED = floatArrayOf(0.48f, 0.10f, 0.08f)
    private val LABEL_RING = floatArrayOf(0.35f, 0.33f, 0.30f)
    private val SPINDLE = floatArrayOf(0.20f, 0.20f, 0.21f)
    private val ARM_SHAFT = floatArrayOf(0.32f, 0.32f, 0.33f)
    private val ARM_HEAD = floatArrayOf(0.16f, 0.16f, 0.17f)
    private val STYLUS_GLOW = floatArrayOf(0.74f, 0.52f, 0.14f)

    // ── Proportions (same as vinyl.py) ──
    private val R_OUTER = 1.0f
    private val R_LEADIN = 0.962f
    private val R_PROG_OUT = 0.945f
    private val R_PROG_IN = 0.395f
    private val R_RUNOUT = 0.360f
    private val R_LABEL = 0.329f
    private val R_SPINDLE = 0.024f
    private val N_RINGS = 96

    private var progFlat = 0
    private var uMvp = -1
    private var uCol = -1

    // VBOs
    private var bgVbo = 0; private var bgN = 0
    private var discVbo = 0; private var discN = 0
    private var labelVbo = 0; private var labelN = 0
    private var spindleVbo = 0; private var spindleN = 0
    private var edgeVbo = 0; private var edgeN = 0  // per ring
    private var grooveVbo = 0; private var grooveN = 0  // per ring

    private val mvp = FloatArray(16)
    private val proj = FloatArray(16)

    @Volatile var deckRotation = 0f
    @Volatile var armLift = 1f
    @Volatile var playProgress = 0f

    private val VS = """
        #version 300 es
        layout(location=0) in vec2 aPos;
        uniform mat4 uMvp;
        void main(){ gl_Position = uMvp * vec4(aPos, 0.0, 1.0); }
    """.trimIndent()
    private val FS = """
        #version 300 es
        precision mediump float;
        uniform vec4 uCol;
        out vec4 frag;
        void main(){ frag = uCol; }
    """.trimIndent()

    override fun onSurfaceCreated(gl10: GL10?, config: EGLConfig?) {
        GL.glClearColor(BG_PLINTH[0], BG_PLINTH[1], BG_PLINTH[2], 1f)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

        progFlat = compile(VS, FS)
        uMvp = GL.glGetUniformLocation(progFlat, "uMvp")
        uCol = GL.glGetUniformLocation(progFlat, "uCol")

        bgVbo = vbo(quadFill(1.45f)); bgN = 6
        discVbo = vbo(discBody(128)); discN = 128 * 8 + 2  // 8 annuli, 128 segments each + center
        labelVbo = vbo(circleFan(64, R_LABEL)); labelN = 66
        spindleVbo = vbo(circleFan(16, R_SPINDLE)); spindleN = 18
        edgeVbo = vbo(edgeRings(384)); edgeN = 384  // per ring: 4 rings * 384 verts stored sequentially
        grooveVbo = vbo(grooveRingsAll(N_RINGS, 192)); grooveN = 192
    }

    override fun onSurfaceChanged(gl10: GL10?, w: Int, h: Int) {
        GL.glViewport(0, 0, w, h)
        val aspect = w.toFloat() / h.toFloat()
        val halfH = 1.12f
        Matrix.orthoM(proj, 0, -halfH * aspect, halfH * aspect, -halfH, halfH, -1f, 1f)
    }

    override fun onDrawFrame(gl10: GL10?) {
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glUseProgram(progFlat)

        // 1. Plinth
        drawFan(bgVbo, bgN, BG_PLINTH)

        // 2. Disc body (rotates)
        Matrix.setIdentityM(mvp, 0)
        Matrix.rotateM(mvp, 0, Math.toDegrees(deckRotation.toDouble()).toFloat(), 0f, 0f, -1f)

        // Draw each of the 8 annuli as triangle strips
        drawDiscBody()

        // 3. Groove rings (rotate with disc)
        drawGrooves()

        // 4. Edge rings (outer, lead-in, runout, label — don't need extra rotation, they're circles)
        drawEdgeRings()

        // 5. Label (rotates)
        drawFan(labelVbo, labelN, LABEL_RED)

        // 6. Label ring highlight
        drawRing(R_LABEL * 1.01f, 128, LABEL_RING, 1.2f)

        // 7. Spindle
        drawFan(spindleVbo, spindleN, SPINDLE)

        // 8. Tonearm (fixed position, does not rotate)
        Matrix.setIdentityM(mvp, 0)
        drawTonearm()
    }

    // ── Disc body: 8 annuli with smooth dark gradient ──
    private fun drawDiscBody() {
        // Ring boundaries from vinyl.py: 0.024, 0.20, 0.38, 0.53, 0.66, 0.78, 0.88, 0.96, 1.0
        val rings = floatArrayOf(0.024f, 0.20f, 0.38f, 53f/100f, 0.66f, 0.78f, 0.88f, 0.96f, 1.0f)
        val segs = 128
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glEnableVertexAttribArray(0)
        GL.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)

        for (i in 0 until rings.size - 1) {
            val r0 = rings[i]; val r1 = rings[i + 1]
            val t0 = r0.toDouble().pow(0.9).toFloat()
            val t1 = r1.toDouble().pow(0.9).toFloat()
            val c0 = lerp(VINYL_CORE, VINYL_RIM, t0)
            val c1 = lerp(VINYL_CORE, VINYL_RIM, t1)
            // Average color for this annulus
            val avgCol = floatArrayOf((c0[0] + c1[0]) / 2, (c0[1] + c1[1]) / 2, (c0[2] + c1[2]) / 2, 1f)
            // Build triangle strip: inner ring + outer ring
            val verts = FloatArray(segs * 4)  // 2 verts per segment * 2 coords
            for (j in 0 until segs) {
                val a = (j.toFloat() / segs) * 2f * PI.toFloat()
                val ca = cos(a); val sa = sin(a)
                verts[j * 4] = ca * r0; verts[j * 4 + 1] = sa * r0
                verts[j * 4 + 2] = ca * r1; verts[j * 4 + 3] = sa * r1
            }
            val buf = directBuf(verts)
            GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, buf)
            GL.glUniform4f(uCol, avgCol[0], avgCol[1], avgCol[2], 1f)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, segs * 2)
        }
    }

    // ── Groove rings ──
    private fun drawGrooves() {
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, grooveVbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, 0)
        GL.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
        val playedUpTo = (playProgress * N_RINGS).toInt().coerceIn(0, N_RINGS)
        for (i in 0 until N_RINGS) {
            val isGap = (i % 4 == 3)
            val col = when {
                isGap -> GROOVE_GAP
                i < playedUpTo -> GROOVE_PLAYED
                else -> GROOVE_UNPLAYED
            }
            GL.glUniform4f(uCol, col[0], col[1], col[2], 1f)
            GL.glDrawArrays(GL.GL_LINE_LOOP, i * grooveN, grooveN)
        }
    }

    // ── Edge rings (outer edge, lead-in, runout, label edge) ──
    private val edgeRadii = floatArrayOf(R_OUTER, R_LEADIN, R_RUNOUT, R_LABEL)
    private val edgeWidths = floatArrayOf(1.5f, 0.7f, 0.7f, 1.0f)

    private fun drawEdgeRings() {
        for (i in edgeRadii.indices) {
            drawRing(edgeRadii[i], 384, EDGE_RING, edgeWidths[i])
        }
    }

    private fun drawRing(radius: Float, segs: Int, color: FloatArray, width: Float) {
        GL.glLineWidth(width)
        val verts = FloatArray(segs * 2)
        for (j in 0 until segs) {
            val a = (j.toFloat() / segs) * 2f * PI.toFloat()
            verts[j * 2] = cos(a) * radius
            verts[j * 2 + 1] = sin(a) * radius
        }
        val buf = directBuf(verts)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, buf)
        GL.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
        GL.glUniform4f(uCol, color[0], color[1], color[2], 1f)
        GL.glDrawArrays(GL.GL_LINE_LOOP, 0, segs)
        GL.glLineWidth(1f)
    }

    // ── Tonearm ──
    private fun drawTonearm() {
        val lift = armLift
        // Pivot (top-right), elbow, headshell — same proportions as desktop
        val px = 0.76f; val py = 0.70f
        val ex = 0.48f; val ey = 0.48f
        // Head moves up with lift
        val hx = 0.10f + lift * 0.28f
        val hy = 0.04f + lift * 0.22f

        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glEnableVertexAttribArray(0)
        GL.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)

        // Shaft: pivot → elbow → headshell
        val shaft = floatArrayOf(px, py, ex, ey, hx, hy)
        val buf = directBuf(shaft)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, buf)
        GL.glLineWidth(5f)
        GL.glUniform4f(uCol, ARM_SHAFT[0], ARM_SHAFT[1], ARM_SHAFT[2], 1f)
        GL.glDrawArrays(GL.GL_LINE_STRIP, 0, 3)

        // Counterweight (small circle behind pivot)
        val cwX = px + (px - ex) * 0.12f
        val cwY = py + (py - ey) * 0.12f
        val cwVerts = circleFanDirect(12, 0.028f, cwX, cwY)
        val cwBuf = directBuf(cwVerts)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, cwBuf)
        GL.glUniform4f(uCol, ARM_HEAD[0], ARM_HEAD[1], ARM_HEAD[2], 1f)
        GL.glDrawArrays(GL.GL_TRIANGLE_FAN, 0, cwVerts.size / 2)

        // Headshell / cartridge: rectangle at the end
        val cw = 0.016f; val ch = 0.038f
        val cart = floatArrayOf(
            hx - cw, hy, hx + cw, hy, hx + cw, hy - ch,
            hx - cw, hy, hx + cw, hy - ch, hx - cw, hy - ch
        )
        val cartBuf = directBuf(cart)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, cartBuf)
        GL.glUniform4f(uCol, ARM_HEAD[0], ARM_HEAD[1], ARM_HEAD[2], 1f)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)

        // Stylus tip — small triangle
        val tip = floatArrayOf(
            hx, hy - ch,
            hx - 0.005f, hy - ch - 0.012f,
            hx + 0.005f, hy - ch - 0.012f
        )
        val tipBuf = directBuf(tip)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, tipBuf)
        GL.glUniform4f(uCol, STYLUS_GLOW[0], STYLUS_GLOW[1], STYLUS_GLOW[2], 1f)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)

        // Pivot circle
        val pivFan = circleFanDirect(16, 0.022f, px, py)
        val pivBuf = directBuf(pivFan)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, pivBuf)
        GL.glUniform4f(uCol, ARM_HEAD[0], ARM_HEAD[1], ARM_HEAD[2], 1f)
        GL.glDrawArrays(GL.GL_TRIANGLE_FAN, 0, pivFan.size / 2)

        // Tonearm rest (small L-shaped bracket at rest position)
        val restX = 0.72f; val restY = 0.58f
        val rest = floatArrayOf(restX - 0.01f, restY, restX + 0.01f, restY, restX + 0.01f, restY - 0.04f)
        val restBuf = directBuf(rest)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, restBuf)
        GL.glLineWidth(3f)
        GL.glUniform4f(uCol, ARM_HEAD[0], ARM_HEAD[1], ARM_HEAD[2], 0.5f)
        GL.glDrawArrays(GL.GL_LINE_STRIP, 0, 3)
        GL.glLineWidth(1f)
    }

    // ── Geometry generators ──

    private fun discBody(segs: Int): FloatArray {
        // 8 annuli triangle strips + center point
        // Actually, simpler: one big triangle fan from center to outer edge
        // with 8 "bands" of color. We draw as triangle strips.
        // For simplicity: single triangle fan from center = 0 to R_OUTER
        val v = FloatArray((segs + 2) * 2)
        v[0] = 0f; v[1] = 0f
        for (i in 0..segs) {
            val a = (i.toFloat() / segs) * 2f * PI.toFloat()
            v[(i + 1) * 2] = cos(a) * R_OUTER
            v[(i + 1) * 2 + 1] = sin(a) * R_OUTER
        }
        return v
    }

    private fun circleFan(segs: Int, radius: Float): FloatArray {
        val v = FloatArray((segs + 2) * 2)
        v[0] = 0f; v[1] = 0f
        for (i in 0..segs) {
            val a = (i.toFloat() / segs) * 2f * PI.toFloat()
            v[(i + 1) * 2] = cos(a) * radius
            v[(i + 1) * 2 + 1] = sin(a) * radius
        }
        return v
    }

    private fun circleFanDirect(segs: Int, radius: Float, cx: Float, cy: Float): FloatArray {
        val v = FloatArray((segs + 2) * 2)
        v[0] = cx; v[1] = cy
        for (i in 0..segs) {
            val a = (i.toFloat() / segs) * 2f * PI.toFloat()
            v[(i + 1) * 2] = cx + cos(a) * radius
            v[(i + 1) * 2 + 1] = cy + sin(a) * radius
        }
        return v
    }

    private fun quadFill(half: Float): FloatArray = floatArrayOf(
        -half, -half, half, -half, half, half,
        -half, -half, half, half, -half, half
    )

    private fun edgeRings(segs: Int): FloatArray {
        // 4 rings, each `segs` vertices. Stored sequentially for LINE_LOOP draws.
        val v = FloatArray(4 * segs * 2)
        val radii = floatArrayOf(R_OUTER, R_LEADIN, R_RUNOUT, R_LABEL)
        for (ring in 0..3) {
            for (j in 0 until segs) {
                val a = (j.toFloat() / segs) * 2f * PI.toFloat()
                v[(ring * segs + j) * 2] = cos(a) * radii[ring]
                v[(ring * segs + j) * 2 + 1] = sin(a) * radii[ring]
            }
        }
        return v
    }

    private fun grooveRingsAll(rings: Int, segs: Int): FloatArray {
        val v = FloatArray(rings * segs * 2)
        for (i in 0 until rings) {
            val f = i.toFloat() / max(1, rings - 1)
            val r = R_PROG_OUT + (R_PROG_IN - R_PROG_OUT) * f
            for (j in 0 until segs) {
                val a = (j.toFloat() / segs) * 2f * PI.toFloat()
                v[(i * segs + j) * 2] = cos(a) * r
                v[(i * segs + j) * 2 + 1] = sin(a) * r
            }
        }
        return v
    }

    // ── Helpers ──

    private fun lerp(a: FloatArray, b: FloatArray, t: Float): FloatArray =
        floatArrayOf(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)

    private fun drawFan(vbo: Int, count: Int, color: FloatArray) {
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, 0)
        GL.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
        GL.glUniform4f(uCol, color[0], color[1], color[2], 1f)
        GL.glDrawArrays(GL.GL_TRIANGLE_FAN, 0, count)
    }

    private fun compile(vs: String, fs: String): Int {
        fun sh(type: Int, src: String): Int {
            val s = GL.glCreateShader(type)
            GL.glShaderSource(s, src)
            GL.glCompileShader(s)
            val ok = IntArray(1)
            GL.glGetShaderiv(s, GL.GL_COMPILE_STATUS, ok, 0)
            if (ok[0] == 0) Log.e("VinylR", "Shader: ${GL.glGetShaderInfoLog(s)}")
            return s
        }
        val p = GL.glCreateProgram()
        GL.glAttachShader(p, sh(GL.GL_VERTEX_SHADER, vs))
        GL.glAttachShader(p, sh(GL.GL_FRAGMENT_SHADER, fs))
        GL.glLinkProgram(p)
        return p
    }

    private fun vbo(data: FloatArray): Int {
        val buf = directBuf(data)
        val ids = IntArray(1)
        GL.glGenBuffers(1, ids, 0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, ids[0])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.size * 4, buf, GL.GL_STATIC_DRAW)
        return ids[0]
    }

    private fun directBuf(data: FloatArray): FloatBuffer {
        val buf = ByteBuffer.allocateDirect(data.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()
        buf.put(data).flip()
        return buf
    }
}
