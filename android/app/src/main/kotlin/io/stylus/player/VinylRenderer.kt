package io.stylus.player

import android.opengl.GLES30 as GL
import android.opengl.GLSurfaceView
import android.opengl.Matrix
import android.util.Log
import java.nio.ByteBuffer
import java.nio.ByteOrder
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10
import kotlin.math.*

/**
 * OpenGL ES 3.0 turntable — interleaved [x,y,r,g,b,a] per vertex.
 * Iso-scaled so circle stays circle regardless of viewport aspect.
 * All geometry via triangles (mobile glLineWidth=1).
 */
class VinylRenderer : GLSurfaceView.Renderer {

    // ── Palette — warm, visible on phone ──
    private val PLINTH = floatArrayOf(0.10f, 0.062f, 0.038f)
    private val VINYL_CORE = floatArrayOf(0.020f, 0.020f, 0.022f)
    private val VINYL_RIM = floatArrayOf(0.075f, 0.072f, 0.068f)
    private val EDGE = floatArrayOf(0.40f, 0.38f, 0.36f)
    private val G_OFF = floatArrayOf(0.11f, 0.115f, 0.125f)
    private val G_ON = floatArrayOf(0.22f, 0.225f, 0.235f)
    private val G_GAP = floatArrayOf(0.72f, 0.70f, 0.68f)
    private val LABEL_BG = floatArrayOf(0.62f, 0.14f, 0.10f)
    private val SPINDLE_C = floatArrayOf(0.24f, 0.24f, 0.25f)
    private val ARM_C = floatArrayOf(0.44f, 0.44f, 0.45f)
    private val ARM_D = floatArrayOf(0.20f, 0.20f, 0.21f)
    private val STYLUS_C = floatArrayOf(0.90f, 0.62f, 0.20f)

    private val R_OUTER = 1.0f; private val R_LEADIN = 0.962f
    private val R_PROG_OUT = 0.945f; private val R_PROG_IN = 0.395f
    private val R_RUNOUT = 0.360f; private val R_LABEL = 0.329f
    private val R_SPINDLE = 0.024f; private val N_RINGS = 96

    private var prog = 0; private var uMvp = -1
    private var bgVbo = 0; private var bgN = 0

    private val mvp = FloatArray(16)
    private val model = FloatArray(16)
    private var isoX = 1f; private var isoY = 1f

    @Volatile var deckRotation = 0f
    @Volatile var armLift = 1f
    @Volatile var playProgress = 0f

    private val SZ = 500000
    private lateinit var sc: FloatArray
    private var si = 0

    private val VS = """
        #version 300 es
        layout(location=0) in vec2 aPos;
        layout(location=1) in vec4 aCol;
        uniform mat4 uMvp;
        out vec4 vCol;
        void main(){ vCol=aCol; gl_Position=uMvp*vec4(aPos,0,1); }
    """.trimIndent()
    private val FS = """
        #version 300 es
        precision mediump float;
        in vec4 vCol; out vec4 frag;
        void main(){ frag=vCol; }
    """.trimIndent()

    override fun onSurfaceCreated(gl10: GL10?, config: EGLConfig?) {
        GL.glClearColor(PLINTH[0], PLINTH[1], PLINTH[2], 1f)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        prog = compile(VS, FS)
        uMvp = GL.glGetUniformLocation(prog, "uMvp")
        sc = FloatArray(SZ)
        bgVbo = uploadBg()
        bgN = 6
    }

    override fun onSurfaceChanged(gl10: GL10?, w: Int, h: Int) {
        GL.glViewport(0, 0, w, h)
        // iso like desktop: min(1, H/W) , min(1, W/H)
        isoX = min(1f, h.toFloat() / w.toFloat())
        isoY = min(1f, w.toFloat() / h.toFloat())
        Log.i("VinylR", "surface ${w}x${h} iso=$isoX,$isoY")
    }

    override fun onDrawFrame(gl10: GL10?) {
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glUseProgram(prog)

        // Plinth
        Matrix.setIdentityM(mvp, 0)
        drawBg()

        // Soft shadow under disc (offset, dark, slightly transparent)
        Matrix.setIdentityM(model, 0)
        Matrix.scaleM(model, 0, isoX, isoY, 1f)
        Matrix.translateM(model, 0, 0.03f, -0.04f, 0f)
        System.arraycopy(model, 0, mvp, 0, 16)
        si = 0; buildShadow(); flush()

        // Disc frame — iso + rotation
        Matrix.setIdentityM(model, 0)
        Matrix.scaleM(model, 0, isoX, isoY, 1f)
        Matrix.rotateM(model, 0, Math.toDegrees(deckRotation.toDouble()).toFloat(), 0f, 0f, -1f)
        System.arraycopy(model, 0, mvp, 0, 16)

        si = 0; buildDisc(); flush()
        si = 0; buildGrooves(); flush()
        si = 0; buildEdges(); flush()
        si = 0; buildLabel(); flush()
        si = 0; buildRing(R_LABEL * 1.005f, 0.006f, floatArrayOf(0.42f,0.38f,0.35f)); flush()
        si = 0; buildSpindle(); flush()

        // Tonearm — iso scale, no rotation
        Matrix.setIdentityM(mvp, 0)
        Matrix.scaleM(mvp, 0, isoX, isoY, 1f)
        si = 0; buildArm(); flush()
    }

    // ── Builders ──

    private fun buildDisc() {
        val rings = floatArrayOf(R_SPINDLE, 0.18f, 0.32f, 0.48f, 0.62f, 0.76f, 0.86f, 0.96f, R_OUTER)
        val segs = 96
        for (i in 0 until rings.size - 1) {
            val r0 = rings[i]; val r1 = rings[i + 1]
            val t = ((r0 + r1) * 0.5f / R_OUTER).toDouble().pow(0.9).toFloat().coerceIn(0f,1f)
            val c = lerp(VINYL_CORE, VINYL_RIM, t)
            // slight sheen — outer rings a touch brighter on one side (fake light)
            for (j in 0 until segs) {
                val a0 = j.toFloat() / segs * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
                tri(ring(r0, a0), ring(r0, a1), ring(r1, a0), c)
                tri(ring(r0, a1), ring(r1, a1), ring(r1, a0), c)
            }
        }
    }

    private fun buildShadow() {
        // soft dark ellipse under disc
        val segs = 48
        val col = floatArrayOf(0f, 0f, 0f)
        val r = R_OUTER * 1.02f
        for (j in 0 until segs) {
            val a0 = j.toFloat() / segs * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
            // center + edge with alpha fade via color alpha
            vert(0f, 0f, floatArrayOf(0f,0f,0f)); // center transparent handled via vertex alpha? use dark
            vert(ring(r, a0), floatArrayOf(0.05f,0.03f,0.02f))
            vert(ring(r, a1), floatArrayOf(0.05f,0.03f,0.02f))
        }
    }

    private fun buildGrooves() {
        val segs = 96; val hw = 0.0065f
        val upTo = (playProgress * N_RINGS).toInt().coerceIn(0, N_RINGS)
        for (i in 0 until N_RINGS) {
            val f = i.toFloat() / max(1, N_RINGS - 1)
            val r = R_PROG_OUT + (R_PROG_IN - R_PROG_OUT) * f
            val isGap = i % 4 == 3
            // fake loudness variation — subtle, not uniform
            val loud = (0.45f + 0.35f * sin(i * 0.37f) + 0.2f * sin(i * 1.11f)).coerceIn(0f,1f)
            val base = when { isGap -> G_GAP; i < upTo -> G_ON; else -> G_OFF }
            val shade = if (isGap) 1f else 0.88f + 0.12f * loud
            val c = floatArrayOf(base[0]*shade, base[1]*shade, base[2]*shade)
            val w = if (isGap) hw * 0.45f else hw * (0.85f + 0.15f * loud)
            for (j in 0 until segs) {
                val a0 = j.toFloat() / segs * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
                tri(ring(r - w, a0), ring(r - w, a1), ring(r + w, a0), c)
                tri(ring(r - w, a1), ring(r + w, a1), ring(r + w, a0), c)
            }
        }
    }

    private fun buildEdges() {
        val edges = arrayOf(R_OUTER to 0.008f, R_LEADIN to 0.0035f, R_RUNOUT to 0.0035f)
        val segs = 128
        for ((r, hw) in edges) {
            for (j in 0 until segs) {
                val a0 = j.toFloat() / segs * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
                tri(ring(r - hw, a0), ring(r - hw, a1), ring(r + hw, a0), EDGE)
                tri(ring(r - hw, a1), ring(r + hw, a1), ring(r + hw, a0), EDGE)
            }
        }
    }

    private fun buildLabel() {
        val segs = 48
        for (j in 0 until segs) {
            val a0 = j.toFloat() / segs * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
            vert(0f, 0f, LABEL_BG); vert(ring(R_LABEL, a0), LABEL_BG); vert(ring(R_LABEL, a1), LABEL_BG)
        }
    }

    private fun buildSpindle() {
        val segs = 14
        for (j in 0 until segs) {
            val a0 = j.toFloat() / segs * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
            vert(0f, 0f, SPINDLE_C); vert(ring(R_SPINDLE, a0), SPINDLE_C); vert(ring(R_SPINDLE, a1), SPINDLE_C)
        }
    }

    private fun buildRing(r: Float, hw: Float, col: FloatArray) {
        val segs = 128
        for (j in 0 until segs) {
            val a0 = j.toFloat() / segs * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
            tri(ring(r - hw, a0), ring(r - hw, a1), ring(r + hw, a0), col)
            tri(ring(r - hw, a1), ring(r + hw, a1), ring(r + hw, a0), col)
        }
    }

    private fun buildArm() {
        val lift = armLift
        // pivot near top-right of plinth
        val px = 0.78f; val py = 0.68f
        val ex = 0.45f; val ey = 0.46f
        val hx = 0.14f + lift * 0.26f; val hy = 0.06f + lift * 0.20f

        thickLine(px, py, ex, ey, 0.014f, ARM_C)
        thickLine(ex, ey, hx, hy, 0.010f, ARM_C)

        val cw = 0.016f; val ch = 0.032f
        quad(hx - cw, hy + 0.006f, hx + cw, hy + 0.006f, hx + cw, hy - ch, hx - cw, hy - ch, ARM_D)

        // stylus diamond
        tri(floatArrayOf(hx, hy - ch), floatArrayOf(hx - 0.006f, hy - ch - 0.014f), floatArrayOf(hx + 0.006f, hy - ch - 0.014f), STYLUS_C)

        // pivot hub
        circle(px, py, 0.024f, 18, ARM_D)
        // pivot top (smaller, lighter)
        circle(px, py, 0.012f, 14, ARM_C)

        // counterweight
        val cwx = px + (px - ex) * 0.16f
        val cwy = py + (py - ey) * 0.16f
        circle(cwx, cwy, 0.030f, 18, ARM_D)
        circle(cwx, cwy, 0.018f, 14, ARM_C)

        // arm rest
        val rx = 0.72f; val ry = 0.52f
        thickLine(rx - 0.02f, ry, rx + 0.02f, ry, 0.004f, ARM_D)
        thickLine(rx + 0.02f, ry, rx + 0.02f, ry - 0.05f, 0.004f, ARM_D)
    }

    // ── Primitives ──

    private fun ring(r: Float, a: Float) = floatArrayOf(cos(a) * r, sin(a) * r)

    private fun vert(x: Float, y: Float, c: FloatArray) {
        sc[si++] = x; sc[si++] = y; sc[si++] = c[0]; sc[si++] = c[1]; sc[si++] = c[2]; sc[si++] = 1f
    }
    private fun vert(p: FloatArray, c: FloatArray) = vert(p[0], p[1], c)
    private fun tri(a: FloatArray, b: FloatArray, c: FloatArray, col: FloatArray) {
        vert(a, col); vert(b, col); vert(c, col)
    }
    private fun quad(x0: Float, y0: Float, x1: Float, y1: Float, x2: Float, y2: Float, x3: Float, y3: Float, c: FloatArray) {
        vert(x0, y0, c); vert(x1, y1, c); vert(x3, y3, c)
        vert(x1, y1, c); vert(x2, y2, c); vert(x3, y3, c)
    }
    private fun thickLine(x0: Float, y0: Float, x1: Float, y1: Float, hw: Float, c: FloatArray) {
        val dx = x1 - x0; val dy = y1 - y0
        val len = sqrt(dx * dx + dy * dy)
        if (len < 1e-6f) return
        val nx = -dy / len * hw; val ny = dx / len * hw
        quad(x0 + nx, y0 + ny, x0 - nx, y0 - ny, x1 - nx, y1 - ny, x1 + nx, y1 + ny, c)
    }
    private fun circle(cx: Float, cy: Float, r: Float, segs: Int, c: FloatArray) {
        for (j in 0 until segs) {
            val a0 = j.toFloat() / segs * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
            vert(cx, cy, c)
            vert(cx + cos(a0) * r, cy + sin(a0) * r, c)
            vert(cx + cos(a1) * r, cy + sin(a1) * r, c)
        }
    }
    private fun lerp(a: FloatArray, b: FloatArray, t: Float) =
        floatArrayOf(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
    private fun quadFill(h: Float) = floatArrayOf(-h, -h, h, -h, h, h, -h, -h, h, h, -h, h)

    // ── Draw ──

    private fun drawBg() {
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, bgVbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 24, 0)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, false, 24, 8)
        GL.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, bgN)
    }

    private fun flush() {
        val n = si / 6
        if (n < 3) return
        // single interleaved buffer, proper offsets via ByteBuffer slice
        val bb = ByteBuffer.allocateDirect(si * 4).order(ByteOrder.nativeOrder())
        val fb = bb.asFloatBuffer()
        fb.put(sc, 0, si)
        fb.position(0)
        // position attrib: 2 floats at offset 0, stride 6 floats (24 bytes)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        fb.position(0)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 24, fb)
        // color attrib: 4 floats at offset 2, stride 24
        // need a separate FloatBuffer view starting at float 2
        val bb2 = ByteBuffer.allocateDirect(si * 4).order(ByteOrder.nativeOrder())
        val fb2 = bb2.asFloatBuffer()
        fb2.put(sc, 0, si)
        fb2.position(2)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, false, 24, fb2)
        GL.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, n)
        // disable after? leave enabled for next flush
    }

    // ── GL ──

    private fun compile(vs: String, fs: String): Int {
        fun sh(type: Int, src: String): Int {
            val s = GL.glCreateShader(type)
            GL.glShaderSource(s, src)
            GL.glCompileShader(s)
            val ok = IntArray(1)
            GL.glGetShaderiv(s, GL.GL_COMPILE_STATUS, ok, 0)
            if (ok[0] == 0) Log.e("VR", "Shader: ${GL.glGetShaderInfoLog(s)}")
            return s
        }
        val p = GL.glCreateProgram()
        GL.glAttachShader(p, sh(GL.GL_VERTEX_SHADER, vs))
        GL.glAttachShader(p, sh(GL.GL_FRAGMENT_SHADER, fs))
        GL.glLinkProgram(p)
        return p
    }

    private fun uploadBg(): Int {
        val data = floatArrayOf(
            -1.45f, -1.45f, PLINTH[0], PLINTH[1], PLINTH[2], 1f,
             1.45f, -1.45f, PLINTH[0], PLINTH[1], PLINTH[2], 1f,
             1.45f,  1.45f, PLINTH[0], PLINTH[1], PLINTH[2], 1f,
            -1.45f, -1.45f, PLINTH[0], PLINTH[1], PLINTH[2], 1f,
             1.45f,  1.45f, PLINTH[0], PLINTH[1], PLINTH[2], 1f,
            -1.45f,  1.45f, PLINTH[0], PLINTH[1], PLINTH[2], 1f
        )
        val buf = ByteBuffer.allocateDirect(data.size * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()
        buf.put(data).flip()
        val ids = IntArray(1)
        GL.glGenBuffers(1, ids, 0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, ids[0])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, data.size * 4, buf, GL.GL_STATIC_DRAW)
        return ids[0]
    }
}
