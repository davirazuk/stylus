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
 * Premium vinyl — piano-black lacquer with a single moving highlight,
 * hairline grooves you have to look for, walnut plinth you want to touch.
 * The grooves are NOT white lines; they are a subtle change in how the
 * black catches the light. That is why a record looks black until you
 * tilt it.
 */
class VinylRenderer : GLSurfaceView.Renderer {

    // ─── Palette ───────────────────────────────────────────────────────
    private val PLINTH       = floatArrayOf(0.115f, 0.072f, 0.045f)   // walnut
    private val VINYL        = floatArrayOf(0.006f, 0.006f, 0.008f)   // piano black
    private val VINYL_HI     = floatArrayOf(0.55f, 0.57f, 0.62f)      // cool highlight
    private val GROOVE       = floatArrayOf(0.012f, 0.013f, 0.018f)   // unlit groove
    private val GROOVE_LIT   = floatArrayOf(0.035f, 0.038f, 0.050f)   // lit groove
    private val GAP          = floatArrayOf(0.07f, 0.068f, 0.065f)    // lead-out gap (dark)
    private val EDGE         = floatArrayOf(0.44f, 0.42f, 0.38f)      // outer/inner edges
    private val LABEL_BG     = floatArrayOf(0.62f, 0.14f, 0.10f)      // label paper
    private val LABEL_RING   = floatArrayOf(0.52f, 0.44f, 0.38f)      // label edge
    private val SPINDLE_C    = floatArrayOf(0.26f, 0.26f, 0.27f)
    private val ARM_C        = floatArrayOf(0.62f, 0.62f, 0.64f)
    private val ARM_D        = floatArrayOf(0.13f, 0.13f, 0.14f)
    private val ARM_HI       = floatArrayOf(0.88f, 0.88f, 0.90f)
    private val STYLUS_C     = floatArrayOf(0.96f, 0.70f, 0.26f)

    // ─── Geometry ─────────────────────────────────────────────────────
    private val R_OUTER      = 1.0f
    private val R_LEADIN     = 0.962f
    private val R_PROG_OUT   = 0.945f
    private val R_PROG_IN    = 0.395f
    private val R_RUNOUT     = 0.360f
    private val R_LABEL      = 0.329f
    private val R_SPINDLE    = 0.024f
    private val N_RINGS      = 72
    private val LIGHT        = Math.toRadians(-35.0).toFloat()

    // ─── GL state ─────────────────────────────────────────────────────
    private var progBg = 0; private var progVinyl = 0
    private var uMvpBg = -1; private var uMvpVinyl = -1
    private var bgVbo = 0; private var bgN = 0

    private val mvp = FloatArray(16)
    private val model = FloatArray(16)
    private var isoX = 1f; private var isoY = 1f

    @Volatile var deckRotation = 0f
    @Volatile var armLift = 1f
    @Volatile var playProgress = 0f

    private val SZ = 700000
    private lateinit var sc: FloatArray
    private var si = 0

    // ─── Shaders ──────────────────────────────────────────────────────
    private val VS_VINYL = """
        #version 300 es
        layout(location=0) in vec2 aPos;
        layout(location=1) in vec4 aCol;
        uniform mat4 uMvp;
        out vec4 vCol;
        out vec2 vPos;
        void main(){ vCol=aCol; vPos=aPos; gl_Position=uMvp*vec4(aPos,0,1); }
    """.trimIndent()

    private val FS_VINYL = """
        #version 300 es
        precision mediump float;
        in vec4 vCol; in vec2 vPos; out vec4 frag;
        void main(){
            float r = length(vPos);
            float theta = atan(vPos.y, vPos.x);
            // two opposed specular lobes fixed in screen space (180° apart)
            float d = mod(theta - (-0.61) + 3.14159, 3.14159) - 1.5708;
            float sheen = exp(-d*d/0.065) * 0.58 * smoothstep(0.35, 0.55, r) * smoothstep(1.02, 0.98, r);
            // radial brightening toward rim (lacquer thickness)
            float rim = pow(clamp((r-0.25)/0.75, 0.0, 1.0), 0.9) * 0.04;
            vec3 col = vCol.rgb + vec3(rim) + sheen * vec3(0.55, 0.57, 0.62);
            // very soft vignette on the vinyl itself so edge catches light
            float edge = smoothstep(0.85, 1.0, r) * 0.06;
            col += edge;
            frag = vec4(col, 1.0);
        }
    """.trimIndent()

    private val VS_BG = """
        #version 300 es
        layout(location=0) in vec2 aPos;
        layout(location=1) in vec4 aCol;
        uniform mat4 uMvp;
        out vec4 vCol; out vec2 vUv;
        void main(){ vCol=aCol; vUv=aPos*0.5+0.5; gl_Position=uMvp*vec4(aPos,0,1); }
    """.trimIndent()

    private val FS_BG = """
        #version 300 es
        precision mediump float;
        in vec4 vCol; in vec2 vUv; out vec4 frag;
        void main(){
            vec2 p = vUv*2.0-1.0;
            float g1 = sin(p.x*18.0 + p.y*2.2)*0.5+0.5;
            float g2 = sin(p.x*44.0 - p.y*7.0)*0.5+0.5;
            float grain = mix(g1,g2,0.35)*0.020;
            vec3 wood = vec3(0.122,0.074,0.044) + vec3(grain);
            float vig = 1.0 - dot(p,p)*0.19;
            vig = pow(vig, 0.90);
            float hl = max(0.0, dot(normalize(vec2(-0.55,0.45)), p)) * 0.05;
            hl *= (1.0 - length(p)*0.38);
            frag = vec4(wood*vig + vec3(hl*0.9, hl*0.65, hl*0.45), 1.0);
        }
    """.trimIndent()

    override fun onSurfaceCreated(gl10: GL10?, config: EGLConfig?) {
        GL.glClearColor(0.06f, 0.038f, 0.028f, 1f)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

        progBg = compile(VS_BG, FS_BG)
        progVinyl = compile(VS_VINYL, FS_VINYL)
        uMvpBg = GL.glGetUniformLocation(progBg, "uMvp")
        uMvpVinyl = GL.glGetUniformLocation(progVinyl, "uMvp")

        sc = FloatArray(SZ)
        bgVbo = uploadBg()
        bgN = 6
    }

    override fun onSurfaceChanged(gl10: GL10?, w: Int, h: Int) {
        GL.glViewport(0, 0, w, h)
        isoX = min(1f, h.toFloat() / w.toFloat())
        isoY = min(1f, w.toFloat() / h.toFloat())
    }

    override fun onDrawFrame(gl10: GL10?) {
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        // ─── Plinth ───
        GL.glUseProgram(progBg)
        Matrix.setIdentityM(mvp, 0)
        GL.glUniformMatrix4fv(uMvpBg, 1, false, mvp, 0)
        drawBg()

        GL.glUseProgram(progVinyl)

        // Shadow under disc
        Matrix.setIdentityM(model, 0)
        Matrix.scaleM(model, 0, isoX, isoY, 1f)
        Matrix.translateM(model, 0, 0.022f, -0.030f, 0f)
        System.arraycopy(model, 0, mvp, 0, 16)
        GL.glUniformMatrix4fv(uMvpVinyl, 1, false, mvp, 0)
        si = 0; buildShadow(); flushVinyl()

        // Disc (rotates)
        Matrix.setIdentityM(model, 0)
        Matrix.scaleM(model, 0, isoX, isoY, 1f)
        Matrix.rotateM(model, 0, Math.toDegrees(deckRotation.toDouble()).toFloat(), 0f, 0f, -1f)
        System.arraycopy(model, 0, mvp, 0, 16)
        GL.glUniformMatrix4fv(uMvpVinyl, 1, false, mvp, 0)

        si = 0; buildDisc(); flushVinyl()
        si = 0; buildGrooves(); flushVinyl()
        si = 0; buildWear(); flushVinyl()
        si = 0; buildEdges(); flushVinyl()
        // Label area (covered by ImageView, draw dark underlay)
        si = 0; buildLabel(); flushVinyl()
        si = 0; buildRing(R_LABEL * 1.005f, 0.004f, LABEL_RING); flushVinyl()
        si = 0; buildSpindle(); flushVinyl()

        // Tonearm (fixed)
        Matrix.setIdentityM(mvp, 0)
        Matrix.scaleM(mvp, 0, isoX, isoY, 1f)
        GL.glUniformMatrix4fv(uMvpVinyl, 1, false, mvp, 0)
        si = 0; buildArm(); flushVinyl()
    }

    // ─── Geometry builders ──────────────────────────────────────────────

    private fun buildDisc() {
        val rings = floatArrayOf(R_SPINDLE, 0.15f, 0.28f, 0.42f, 0.57f, 0.72f, 0.86f, 0.95f, R_OUTER)
        val segs = 96
        for (i in 0 until rings.size - 1) {
            val r0 = rings[i]; val r1 = rings[i + 1]
            val t = ((r0 + r1) * 0.5f / R_OUTER).toDouble().pow(0.88).toFloat().coerceIn(0f,1f)
            val base = lerp(floatArrayOf(0.006f,0.006f,0.008f), floatArrayOf(0.045f,0.043f,0.040f), t)
            for (j in 0 until segs) {
                val a0 = j.toFloat() / segs * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
                tri(ring(r0, a0), ring(r0, a1), ring(r1, a0), base)
                tri(ring(r0, a1), ring(r1, a1), ring(r1, a0), base)
            }
        }
    }

    private fun buildShadow() {
        val segs = 48
        val r = R_OUTER * 1.04f
        for (j in 0 until segs) {
            val a0 = j.toFloat() / segs * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
            vert(0f, 0f, floatArrayOf(0f,0f,0f))
            vert(ring(r, a0), floatArrayOf(0.028f,0.016f,0.010f))
            vert(ring(r, a1), floatArrayOf(0.028f,0.016f,0.010f))
        }
    }

    private fun buildGrooves() {
        // hairline — you see them because they catch the highlight, not because they are white
        val segs = 180; val hw = 0.0014f
        val upTo = (playProgress * N_RINGS).toInt().coerceIn(0, N_RINGS)
        for (i in 0 until N_RINGS) {
            val f = i.toFloat() / max(1, N_RINGS - 1)
            val r = R_PROG_OUT + (R_PROG_IN - R_PROG_OUT) * f
            val isGap = i % 4 == 3
            val loud = (0.32f + 0.42f * sin(i*0.41f + 1.2f) + 0.26f * sin(i*1.07f)).coerceIn(0f,1f)
            val shade = if (isGap) 1f else 0.10f + 0.90f * loud.pow(0.58f)
            val base = when { isGap -> GAP; i < upTo -> GROOVE_LIT; else -> GROOVE }
            val colScale = if (isGap) 0.55f else shade
            val w = if (isGap) hw*0.70f else hw*(0.85f + 0.15f*shade)
            val col = floatArrayOf(base[0]*colScale, base[1]*colScale, base[2]*colScale)
            for (j in 0 until segs) {
                val a0 = j.toFloat() / segs * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
                tri(ring(r - w, a0), ring(r - w, a1), ring(r + w, a0), col)
                tri(ring(r - w, a1), ring(r + w, a1), ring(r + w, a0), col)
            }
        }
    }

    private fun buildWear() {
        val rnd = java.util.Random(42)
        for (k in 0 until 7) {
            val r = 0.42f + rnd.nextFloat()*0.50f
            val a = rnd.nextFloat()*2f*PI.toFloat()
            val len = 0.03f + rnd.nextFloat()*0.10f
            val a1 = a + len/r
            val hw = 0.0007f
            val p0 = ring(r, a); val p1 = ring(r, a1)
            val dx=p1[0]-p0[0]; val dy=p1[1]-p0[1]
            val l= sqrt(dx*dx+dy*dy).coerceAtLeast(1e-6f)
            val nx=-dy/l*hw; val ny=dx/l*hw
            val alpha = 0.07f + rnd.nextFloat()*0.10f
            val col = floatArrayOf(0.38f*alpha,0.38f*alpha,0.40f*alpha)
            quad(p0[0]+nx,p0[1]+ny, p0[0]-nx,p0[1]-ny, p1[0]-nx,p1[1]-ny, p1[0]+nx,p1[1]+ny, col)
        }
        for (k in 0 until 22) {
            val r = 0.37f + rnd.nextFloat()*0.56f
            val a = rnd.nextFloat()*2f*PI.toFloat()
            val p = ring(r, a)
            val sz = 0.0011f + rnd.nextFloat()*0.0010f
            val col = floatArrayOf(0.28f,0.28f,0.29f)
            quad(p[0]-sz,p[1]-sz, p[0]+sz,p[1]-sz, p[0]+sz,p[1]+sz, p[0]-sz,p[1]+sz, col)
        }
    }

    private fun buildEdges() {
        val edges = arrayOf(R_OUTER to 0.005f, R_LEADIN to 0.0022f, R_RUNOUT to 0.0022f)
        val segs = 128
        for ((r,hw) in edges) {
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
        val playR = R_PROG_OUT + (R_PROG_IN - R_PROG_OUT) * playProgress
        val r = if (lift > 0.5f) R_OUTER * 1.06f else playR
        val ang = Math.toRadians(34.0).toFloat()
        val hx = r * cos(ang); val hy = r * sin(ang)
        val liftOff = lift * 0.13f; val hyLift = hy + liftOff
        val px = 0.88f; val py = 0.72f
        val ex = (px + hx) * 0.5f; val ey = (py + hyLift) * 0.5f + 0.04f

        thickLine(px, py, ex, ey, 0.018f, ARM_C)
        thickLine(ex, ey, hx, hyLift, 0.011f, ARM_C)

        val cw = 0.017f; val ch = 0.030f
        quad(hx - cw, hyLift + 0.006f, hx + cw, hyLift + 0.006f, hx + cw, hyLift - ch, hx - cw, hyLift - ch, ARM_D)
        tri(floatArrayOf(hx, hyLift - ch), floatArrayOf(hx - 0.006f, hyLift - ch - 0.014f), floatArrayOf(hx + 0.006f, hyLift - ch - 0.014f), STYLUS_C)

        circle(px, py, 0.026f, 18, ARM_D)
        circle(px, py, 0.013f, 14, ARM_C)

        val cwx = px + (px - ex) * 0.18f; val cwy = py + (py - ey) * 0.18f
        circle(cwx, cwy, 0.030f, 18, ARM_D)
        circle(cwx, cwy, 0.018f, 14, ARM_C)

        val rx = 0.84f; val ry = 0.56f
        thickLine(rx - 0.02f, ry, rx + 0.02f, ry, 0.004f, ARM_D)
        thickLine(rx + 0.02f, ry, rx + 0.02f, ry - 0.05f, 0.004f, ARM_D)
    }

    // ─── Primitives ────────────────────────────────────────────────────

    private fun ring(r: Float, a: Float) = floatArrayOf(cos(a) * r, sin(a) * r)
    private fun vert(x: Float, y: Float, c: FloatArray) { sc[si++] = x; sc[si++] = y; sc[si++] = c[0]; sc[si++] = c[1]; sc[si++] = c[2]; sc[si++] = 1f }
    private fun vert(p: FloatArray, c: FloatArray) = vert(p[0], p[1], c)
    private fun tri(a: FloatArray, b: FloatArray, c: FloatArray, col: FloatArray) { vert(a, col); vert(b, col); vert(c, col) }
    private fun quad(x0: Float, y0: Float, x1: Float, y1: Float, x2: Float, y2: Float, x3: Float, y3: Float, c: FloatArray) {
        vert(x0, y0, c); vert(x1, y1, c); vert(x3, y3, c)
        vert(x1, y1, c); vert(x2, y2, c); vert(x3, y3, c)
    }
    private fun thickLine(x0: Float, y0: Float, x1: Float, y1: Float, hw: Float, c: FloatArray) {
        val dx = x1 - x0; val dy = y1 - y0
        val len = sqrt(dx * dx + dy * dy).coerceAtLeast(1e-6f)
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
    private fun lerp(a: FloatArray, b: FloatArray, t: Float) = floatArrayOf(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
    private fun quadFill(h: Float) = floatArrayOf(-h, -h, h, -h, h, h, -h, -h, h, h, -h, h)

    // ─── Draw helpers ──────────────────────────────────────────────────

    private fun drawBg() {
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, bgVbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 24, 0)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, false, 24, 8)
        GL.glUniformMatrix4fv(uMvpBg, 1, false, mvp, 0)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, bgN)
    }

    private fun flushVinyl() {
        val n = si / 6; if (n < 3) return
        val bb = ByteBuffer.allocateDirect(si * 4).order(ByteOrder.nativeOrder())
        val fb = bb.asFloatBuffer()
        fb.put(sc, 0, si); fb.position(0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 24, fb)
        val bb2 = ByteBuffer.allocateDirect(si * 4).order(ByteOrder.nativeOrder())
        val fb2 = bb2.asFloatBuffer()
        fb2.put(sc, 0, si); fb2.position(2)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, false, 24, fb2)
        GL.glUniformMatrix4fv(uMvpVinyl, 1, false, mvp, 0)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, n)
    }

    private fun compile(vs: String, fs: String): Int {
        fun sh(type: Int, src: String): Int {
            val s = GL.glCreateShader(type)
            GL.glShaderSource(s, src); GL.glCompileShader(s)
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