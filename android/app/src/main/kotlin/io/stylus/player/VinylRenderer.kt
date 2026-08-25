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
 * OpenGL ES 3.0 turntable — interleaved [x,y,r,g,b,a], 6 floats per vertex.
 * All geometry via triangles (no glLineWidth).
 */
class VinylRenderer : GLSurfaceView.Renderer {

    private val PLINTH = floatArrayOf(0.07f, 0.048f, 0.032f)
    private val VINYL_CORE = floatArrayOf(0.013f, 0.013f, 0.014f)
    private val VINYL_RIM = floatArrayOf(0.052f, 0.050f, 0.048f)
    private val EDGE = floatArrayOf(0.30f, 0.29f, 0.28f)
    private val G_OFF = floatArrayOf(0.045f, 0.050f, 0.058f)
    private val G_ON = floatArrayOf(0.14f, 0.15f, 0.16f)
    private val G_GAP = floatArrayOf(0.55f, 0.54f, 0.52f)
    private val LABEL_BG = floatArrayOf(0.50f, 0.11f, 0.08f)
    private val LABEL_ED = floatArrayOf(0.38f, 0.35f, 0.32f)
    private val SPINDLE_C = floatArrayOf(0.20f, 0.20f, 0.21f)
    private val ARM_C = floatArrayOf(0.30f, 0.30f, 0.31f)
    private val ARM_D = floatArrayOf(0.14f, 0.14f, 0.15f)
    private val STYLUS_C = floatArrayOf(0.74f, 0.52f, 0.14f)

    private val R_OUTER = 1.0f; private val R_LEADIN = 0.962f
    private val R_PROG_OUT = 0.945f; private val R_PROG_IN = 0.395f
    private val R_RUNOUT = 0.360f; private val R_LABEL = 0.329f
    private val R_SPINDLE = 0.024f; private val N_RINGS = 96

    private var prog = 0; private var uMvp = -1
    private var bgVbo = 0; private var bgN = 0
    private var dynVbo = 0

    private val mvp = FloatArray(16)
    private val proj = FloatArray(16)
    @Volatile var deckRotation = 0f
    @Volatile var armLift = 1f
    @Volatile var playProgress = 0f

    // Interleaved scratch: 6 floats per vertex [x,y,r,g,b,a]
    private val SZ = 500000
    private lateinit var sc: FloatArray
    private var si = 0  // write cursor in scratch

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
        dynVbo = genBuf()
        bgVbo = uploadBg()
        bgN = 6
    }

    override fun onSurfaceChanged(gl10: GL10?, w: Int, h: Int) {
        GL.glViewport(0, 0, w, h)
        val a = w.toFloat() / h.toFloat()
        Matrix.orthoM(proj, 0, -1.12f * a, 1.12f * a, -1.12f, 1.12f, -1f, 1f)
    }

    override fun onDrawFrame(gl10: GL10?) {
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glUseProgram(prog)

        // Plinth
        Matrix.setIdentityM(mvp, 0)
        drawBg()

        // Disc frame
        Matrix.setIdentityM(mvp, 0)
        Matrix.rotateM(mvp, 0, Math.toDegrees(deckRotation.toDouble()).toFloat(), 0f, 0f, -1f)

        si = 0; buildDisc(); flush("disc")
        si = 0; buildGrooves(); flush("grooves")
        si = 0; buildEdges(); flush("edges")
        si = 0; buildLabel(); flush("label")
        si = 0; buildRing(R_LABEL * 1.005f, 0.005f, LABEL_ED); flush("label_edge")
        si = 0; buildSpindle(); flush("spindle")

        // Tonearm
        Matrix.setIdentityM(mvp, 0)
        si = 0; buildArm(); flush("arm")
    }

    // ── Builders ──

    private fun buildDisc() {
        val rings = floatArrayOf(R_SPINDLE, 0.20f, 0.38f, 0.53f, 0.66f, 0.78f, 0.88f, 0.96f, R_OUTER)
        val segs = 96
        for (i in 0 until rings.size - 1) {
            val r0 = rings[i]; val r1 = rings[i + 1]
            val t = ((r0 + r1) * 0.5f / R_OUTER).toDouble().pow(0.9).toFloat()
            val c = lerp(VINYL_CORE, VINYL_RIM, t)
            for (j in 0 until segs) {
                val a0 = j.toFloat() / segs * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
                tri(ring(r0, a0), ring(r0, a1), ring(r1, a0), c)
                tri(ring(r0, a1), ring(r1, a1), ring(r1, a0), c)
            }
        }
    }

    private fun buildGrooves() {
        val segs = 96; val hw = 0.005f
        val upTo = (playProgress * N_RINGS).toInt().coerceIn(0, N_RINGS)
        for (i in 0 until N_RINGS) {
            val f = i.toFloat() / max(1, N_RINGS - 1)
            val r = R_PROG_OUT + (R_PROG_IN - R_PROG_OUT) * f
            val isGap = i % 4 == 3
            val c = when { isGap -> G_GAP; i < upTo -> G_ON; else -> G_OFF }
            val w = if (isGap) hw * 0.5f else hw
            for (j in 0 until segs) {
                val a0 = j.toFloat() / segs * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
                tri(ring(r - w, a0), ring(r - w, a1), ring(r + w, a0), c)
                tri(ring(r - w, a1), ring(r + w, a1), ring(r + w, a0), c)
            }
        }
    }

    private fun buildEdges() {
        val data = arrayOf(R_OUTER to 0.007f, R_LEADIN to 0.003f, R_RUNOUT to 0.003f, R_LABEL * 1.005f to 0.004f)
        val segs = 128
        for ((r, hw) in data) {
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
        val segs = 12
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
        val px = 0.76f; val py = 0.70f
        val ex = 0.48f; val ey = 0.48f
        val hx = 0.10f + lift * 0.28f; val hy = 0.04f + lift * 0.22f

        thickLine(px, py, ex, ey, 0.012f, ARM_C)
        thickLine(ex, ey, hx, hy, 0.008f, ARM_C)

        val cw = 0.014f; val ch = 0.035f
        quad(hx - cw, hy, hx + cw, hy, hx + cw, hy - ch, hx - cw, hy - ch, ARM_D)

        tri(floatArrayOf(hx, hy - ch), floatArrayOf(hx - 0.005f, hy - ch - 0.012f), floatArrayOf(hx + 0.005f, hy - ch - 0.012f), STYLUS_C)

        circle(px, py, 0.020f, 16, ARM_D)
        val cwx = px + (px - ex) * 0.14f; val cwy = py + (py - ey) * 0.14f
        circle(cwx, cwy, 0.026f, 16, ARM_D)
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
        GL.glDrawArrays(GL.GL_TRIANGLE_FAN, 0, bgN)
    }

    private fun flush(label: String) {
        val n = si / 6  // number of vertices
        if (n < 3) return
        val buf = ByteBuffer.allocateDirect(si * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()
        buf.put(sc, 0, si).flip()
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 24, buf)
        GL.glEnableVertexAttribArray(1)
        // Color starts at byte offset 8 (after 2 position floats)
        val colBuf = ByteBuffer.allocateDirect(si * 4).order(ByteOrder.nativeOrder())
        colBuf.asFloatBuffer().put(sc, 0, si).flip()
        colBuf.position(8)  // skip x,y
        val colFBuf = colBuf.asFloatBuffer()
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, false, 24, colFBuf)
        GL.glUniformMatrix4fv(uMvp, 1, false, mvp, 0)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, n)
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

    private fun genBuf(): Int {
        val ids = IntArray(1)
        GL.glGenBuffers(1, ids, 0)
        return ids[0]
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
