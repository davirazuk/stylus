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
 * Vinil vivo — luz no escuro, não mobília.
 *
 * §5.5: disco de luz, agulha de luz, sulco conta o disco.
 * Sem madeira, sem parafuso, sem sala.
 */
class VinylRenderer : GLSurfaceView.Renderer {

    // ─── Paleta ──────────────────────────────────────────────────────────
    private val VC  = floatArrayOf(0.010f, 0.010f, 0.013f)
    private val VR  = floatArrayOf(0.045f, 0.048f, 0.056f)
    private val SH  = floatArrayOf(0.120f, 0.122f, 0.115f)
    private val GU  = floatArrayOf(0.048f, 0.051f, 0.062f)
    private val GP  = floatArrayOf(0.145f, 0.130f, 0.115f)
    private val GG  = floatArrayOf(0.740f, 0.720f, 0.680f)
    private val AMB = floatArrayOf(0.960f, 0.560f, 0.130f)
    private val ER  = floatArrayOf(0.135f, 0.138f, 0.148f)
    private val LB  = floatArrayOf(0.56f, 0.12f, 0.08f)
    private val SP  = floatArrayOf(0.22f, 0.22f, 0.23f)
    private val ARM = floatArrayOf(0.36f, 0.38f, 0.44f)
    private val ARM_HI = floatArrayOf(0.66f, 0.68f, 0.76f)
    private val ARM_D = floatArrayOf(0.11f, 0.12f, 0.16f)
    private val DUST_C = floatArrayOf(0.16f, 0.15f, 0.13f)
    private val EDGE_G = floatArrayOf(0.20f, 0.18f, 0.16f)

    // ─── Raios ───────────────────────────────────────────────────────────
    private val RO = 1.0f; private val RL = 0.962f; private val RPO = 0.945f
    private val RPI = 0.395f; private val RLA = 0.329f
    private val RS = 0.024f; private val NRINGS = 96

    // ─── GL ────────────────────────────────────────────────────────────────
    private var prog = 0; private var progP = 0
    private var uMvp = -1; private var uTime = -1; private var uTimeP = -1
    private var uCx = -1; private var uCy = -1
    private val model = FloatArray(16)
    private var pVbo = 0
    private var dScaleX = 1f; private var dScaleY = 1f
    @Volatile var time: Float = 0f

    @Volatile var deckRotation = 0f
    @Volatile var armLift = 1f
    @Volatile var playProgress = 0f
    @Volatile var crackle = 0f
    @Volatile var gapFracs: FloatArray? = null
    @Volatile var discCx = 0f
    @Volatile var discCy = 0f
    @Volatile var viewW = 1080
    @Volatile var viewH = 1920
    @Volatile var wearSeed = 42  // album-specific seed for unique wear marks

    private val PVA = atan2(
        (sin(Math.toRadians(38.0)) * 1.24 + 0.10).toFloat(),
        (cos(Math.toRadians(38.0)) * 1.24 + 0.06).toFloat()
    )

    // Wear marks
    private val WEAR_N = 140
    private val wearR = FloatArray(WEAR_N)
    private val wearA = FloatArray(WEAR_N)
    private val wearB = FloatArray(WEAR_N)
    private var wearInit = false
    private var lastWearSeed = 0

    // Ambient dust
    private val DUST_N = 80
    private val dustX = FloatArray(DUST_N)
    private val dustY = FloatArray(DUST_N)
    private val dustR = FloatArray(DUST_N)
    private val dustS = FloatArray(DUST_N)
    private val dustB = FloatArray(DUST_N)
    private var dustInit = false

    // Vertex buffer: [x,y,r,g,b,a,edge] stride=28
    private val SZ = 4000000
    private lateinit var vb: FloatArray
    private var vi = 0

    // ─── Shaders ─────────────────────────────────────────────────────────
    private val VS = """
        #version 300 es
        layout(location=0) in vec2 aP;
        layout(location=1) in vec4 aC;
        layout(location=2) in float aE;
        uniform mat4 uM;
        out vec2 vPos;
        out vec4 vC;
        out float vE;
        void main(){
            vPos=aP; vC=aC; vE=aE;
            gl_Position=uM*vec4(aP,0,1);
        }
    """.trimIndent()

    private val FS = """
        #version 300 es
        precision mediump float;
        in vec2 vPos; in vec4 vC; in float vE;
        uniform float uT;
        out vec4 f;
        void main(){
            float d=abs(vE);
            float a=1.0-smoothstep(0.40,1.0,d);
            a*=0.92+0.08*exp(-d*d*7.0);
            vec3 col=vC.rgb*a;
            float br=dot(col, vec3(0.299,0.587,0.114));
            // Warm bloom — bright areas glow amber into surroundings
            if(br>0.15){
                float bloom=pow((br-0.15)/0.85, 1.4)*0.42;
                bloom*=1.0-smoothstep(0.0,1.0,d)*0.45;
                col+=vec3(bloom)*vec3(1.0,0.72,0.38);
            }
            // Film grain — adds texture to flat areas
            float n=fract(sin(dot(vPos*2.8+uT*0.012, vec2(12.9898,78.233)))*43758.5);
            col+=(n-0.5)*0.005;
            f=vec4(col,1.0);
        }
    """.trimIndent()

    private val VP = """
        #version 300 es
        layout(location=0) in vec2 aP;
        out vec2 vU;
        void main(){ vU=aP*0.5+0.5; gl_Position=vec4(aP,0,1); }
    """.trimIndent()

    private val FP = """
        #version 300 es
        precision mediump float;
        in vec2 vU; out vec4 f;
        uniform float uT;
        uniform float uCx;
        uniform float uCy;
        void main(){
            vec2 p=vU*2.0-1.0;
            vec2 dc=vec2(uCx, uCy);
            float dd=length(p-dc);
            // Deep void — dark center, slightly lighter edges
            vec3 col=mix(vec3(0.010,0.011,0.018), vec3(0.004,0.004,0.006),
                         smoothstep(0.0,1.2,dd));
            // Warm halo from the disc
            float breathe=0.85+0.15*sin(uT*0.4);
            col+=vec3(0.30,0.18,0.08)*exp(-dd*dd*3.2)*0.20*breathe;
            col+=vec3(0.15,0.09,0.04)*exp(-dd*dd*1.0)*0.08*breathe;
            // Vignette
            col*=1.0-dot(p,p)*0.32;
            // Film grain
            float n=fract(sin(dot(vU*2.3+uT*0.007, vec2(12.9898,78.233)))*43758.5);
            col+=(n-0.5)*0.004;
            f=vec4(col,1.0);
        }
    """.trimIndent()

    override fun onSurfaceCreated(gl: GL10?, c: EGLConfig?) {
        GL.glClearColor(0.003f, 0.003f, 0.006f, 1f)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        prog = sh(VS, FS); progP = sh(VP, FP)
        uMvp = GL.glGetUniformLocation(prog, "uM")
        uTime = GL.glGetUniformLocation(prog, "uT")
        uTimeP = GL.glGetUniformLocation(progP, "uT")
        uCx = GL.glGetUniformLocation(progP, "uCx")
        uCy = GL.glGetUniformLocation(progP, "uCy")
        vb = FloatArray(SZ)
        pVbo = qbo()
    }

    override fun onSurfaceChanged(gl: GL10?, w: Int, h: Int) {
        GL.glViewport(0, 0, w, h)
        viewW = w; viewH = h
        val wF = w.toFloat(); val hF = h.toFloat()
        val isoX = min(1f, hF / wF); val isoY = min(1f, wF / hF)
        val base = 0.84f
        dScaleX = base * isoX
        dScaleY = base * isoY
    }

    override fun onDrawFrame(gl: GL10?) {
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        time += 0.016f

        // ── Background ──
        GL.glUseProgram(progP)
        if (uTimeP >= 0) GL.glUniform1f(uTimeP, time)
        if (uCx >= 0) GL.glUniform1f(uCx, discCx)
        if (uCy >= 0) GL.glUniform1f(uCy, discCy)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, pVbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 8, 0)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glDisableVertexAttribArray(0)

        // ── Disc (rotates) ──
        GL.glUseProgram(prog)
        if (uTime >= 0) GL.glUniform1f(uTime, time)
        Matrix.setIdentityM(model, 0)
        Matrix.translateM(model, 0, discCx, discCy, 0f)
        Matrix.scaleM(model, 0, dScaleX, dScaleY, 1f)
        Matrix.rotateM(model, 0, Math.toDegrees(deckRotation.toDouble()).toFloat(), 0f, 0f, 1f)
        vi = 0
        discBody()
        grooveRings()
        boundaryRing()
        edgeRings()
        labelCircle()
        labelGlow()
        spindle()
        wearMarks()
        flush(true)

        // ── Arm + beam + sparks (screen space) ──
        Matrix.setIdentityM(model, 0)
        Matrix.translateM(model, 0, discCx, discCy, 0f)
        Matrix.scaleM(model, 0, dScaleX, dScaleY, 1f)
        vi = 0
        needleBeam()
        sparks()
        armLine()
        flush(true)
    }

    // ═══════════════════════════════════════════════════════════════════════
    // DISCO
    // ═══════════════════════════════════════════════════════════════════════
    private fun discBody() {
        val rot = deckRotation
        // Two light sources: main highlight + secondary fill
        val light1 = -0.66f + 0.02f * sin(time * 0.35f)
        val light2 = light1 + 2.1f  // secondary highlight offset
        val rings = floatArrayOf(0.024f, 0.18f, 0.34f, 0.48f, 0.60f, 0.72f, 0.82f, 0.91f, 0.96f, 1.0f)
        for (k in 0 until rings.size - 1) {
            val r0 = rings[k]; val r1 = rings[k + 1]
            val n = ((r0 + r1) * 0.5f * 560).toInt().coerceIn(64, 300)
            val t0 = r0.toDouble().pow(0.9).toFloat()
            val t1 = r1.toDouble().pow(0.9).toFloat()
            val c0 = lerp(VC, VR, t0); val c1 = lerp(VC, VR, t1)
            val s0 = sc(SH, r0.toDouble().pow(1.7).toFloat())
            val s1 = sc(SH, r1.toDouble().pow(1.7).toFloat())
            for (j in 0 until n) {
                val a = j.toFloat() / n * 2f * PI.toFloat()
                val a2 = (j + 1).toFloat() / n * 2f * PI.toFloat()
                // Primary sheen — tight, bright
                val g0 = sheen(a, light1); val g1 = sheen(a2, light1)
                // Secondary sheen — wider, dimmer
                val g0b = sheen(a, light2) * 0.3f; val g1b = sheen(a2, light2) * 0.3f
                val g0t = (g0 + g0b).coerceIn(0f, 1f)
                val g1t = (g1 + g1b).coerceIn(0f, 1f)
                val co0 = add(c0, sc(s0, g0t - 1f)); val co1 = add(c0, sc(s1, g1t - 1f))
                val ci0 = add(c1, sc(s0, g0t - 1f)); val ci1 = add(c1, sc(s1, g1t - 1f))
                val o0x = cos(a - rot) * r0; val o0y = sin(a - rot) * r0
                val o1x = cos(a2 - rot) * r0; val o1y = sin(a2 - rot) * r0
                val i0x = cos(a - rot) * r1; val i0y = sin(a - rot) * r1
                val i1x = cos(a2 - rot) * r1; val i1y = sin(a2 - rot) * r1
                v(o0x, o0y, co0, 0f); v(o1x, o1y, co1, 0f); v(i0x, i0y, ci0, 0f)
                v(o1x, o1y, co1, 0f); v(i1x, i1y, ci1, 0f); v(i0x, i0y, ci0, 0f)
            }
        }
    }

    private fun grooveRings() {
        val rot = deckRotation
        val upTo = (playProgress * NRINGS).toInt().coerceIn(0, NRINGS)
        val gaps = gapFracs
        val gapSet = if (gaps != null && gaps.isNotEmpty()) {
            gaps.map { (it * NRINGS).toInt().coerceIn(0, NRINGS - 1) }.toSet()
        } else {
            setOf(NRINGS / 4, NRINGS / 2, 3 * NRINGS / 4)
        }
        for (i in 0 until NRINGS) {
            val f = i.toFloat() / max(1, NRINGS - 1)
            val r = RPO + (RPI - RPO) * f
            val isGap = i in gapSet
            val loud = (0.32f + 0.42f * sin(i * 0.41f + 1.2f) + 0.26f * sin(i * 1.07f)).coerceIn(0f, 1f)
            // Groove catches light as disc rotates — depends on both time AND rotation
            val angle = i.toFloat() / NRINGS * 2f * PI.toFloat()
            val lightCatch = max(0f, sin(angle + rot * 3f)) * 0.35f
            val gapPulse = if (isGap) {
                val dist = abs(playProgress * NRINGS - i.toFloat())
                if (dist < 3f) 1f + 0.6f * (1f - dist / 3f) else 1f
            } else 1f
            val shade = (if (isGap) 1f * gapPulse else 0.10f + 0.90f * loud.toDouble().pow(0.62).toFloat()) + lightCatch
            val base = when { isGap -> GG; i < upTo -> GP; else -> GU }
            val hw = if (isGap) 0.18f else 0.85f * (0.88f + 0.14f * min(1f, loud))
            val n = (r * 560).toInt().coerceIn(64, 300)
            val str = if (isGap) 0.8f else 0.22f  // stronger specular
            val lMult = if (isGap) gapPulse else min(1f, loud)
            stripRing(r, n, hw, shade.coerceIn(0f, 1.4f), base, -0.66f, str, lMult, rot)
        }
    }

    private fun stripRing(r: Float, n: Int, hw: Float, shade: Float, base: FloatArray,
                          light: Float, sStr: Float, lMult: Float, rot: Float = 0f) {
        val w = hw * 0.006f
        for (j in 0 until n) {
            val a = j.toFloat() / n * 2f * PI.toFloat()
            val a2 = (j + 1).toFloat() / n * 2f * PI.toFloat()
            val g0 = 1f + sStr * sheen(a, light) * (0.85f + 0.15f * lMult)
            val g1 = 1f + sStr * sheen(a2, light) * (0.85f + 0.15f * lMult)
            val outerShade = shade * 0.92f; val innerShade = shade * 1.08f
            val co0 = sc(base, outerShade * g0); val co1 = sc(base, outerShade * g1)
            val ci0 = sc(base, innerShade * g0); val ci1 = sc(base, innerShade * g1)
            val o0x = cos(a - rot) * (r - w); val o0y = sin(a - rot) * (r - w)
            val o1x = cos(a2 - rot) * (r - w); val o1y = sin(a2 - rot) * (r - w)
            val i0x = cos(a - rot) * (r + w); val i0y = sin(a - rot) * (r + w)
            val i1x = cos(a2 - rot) * (r + w); val i1y = sin(a2 - rot) * (r + w)
            v(o0x, o0y, co0, -1f); v(o1x, o1y, co1, -1f); v(i0x, i0y, ci0, 1f)
            v(o1x, o1y, co1, -1f); v(i1x, i1y, ci1, 1f); v(i0x, i0y, ci0, 1f)
        }
    }

    private fun boundaryRing() {
        if (armLift > 0.5f) return
        val r = RPO + (RPI - RPO) * playProgress
        val rot = deckRotation
        val pulse = 0.80f + 0.20f * sin(time * 1.4f)
        val arcN = 80
        val w = 0.003f
        for (j in 0 until arcN) {
            val a0 = j.toFloat() / arcN * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / arcN * 2f * PI.toFloat()
            val mask0 = max(0f, cos(a0 - rot * 2.1f))
            val mask1 = max(0f, cos(a1 - rot * 2.1f))
            val m0 = mask0.toDouble().pow(2.5).toFloat() * pulse
            val m1 = mask1.toDouble().pow(2.5).toFloat() * pulse
            if (m0 < 0.01f && m1 < 0.01f) continue
            val c0 = sc(AMB, m0 * 0.28f)
            val c1 = sc(AMB, m1 * 0.28f)
            val o0x = cos(a0) * (r + w); val o0y = sin(a0) * (r + w)
            val i0x = cos(a0) * (r - w); val i0y = sin(a0) * (r - w)
            val o1x = cos(a1) * (r + w); val o1y = sin(a1) * (r + w)
            val i1x = cos(a1) * (r - w); val i1y = sin(a1) * (r - w)
            v(i0x, i0y, c0, -1f); v(i1x, i1y, c1, -1f); v(o0x, o0y, c0, 1f)
            v(i1x, i1y, c1, -1f); v(o1x, o1y, c1, 1f); v(o0x, o0y, c0, 1f)
        }
    }

    private fun edgeRings() {
        val rot = deckRotation
        for ((r, hw) in arrayOf(RO to 1.8f, RL to 1.0f, RLA to 1.3f)) {
            stripRing(r, 300, hw, 1f, ER, -0.66f, 0.9f, 1f, rot)
        }
        // Edge glow — warm rim light
        val n = 72
        for (j in 0 until n) {
            val a = j.toFloat() / n * 2f * PI.toFloat()
            val a2 = (j + 1).toFloat() / n * 2f * PI.toFloat()
            val glow = 0.14f + 0.06f * sin(a * 4f + time * 0.2f + rot)
            val eg = sc(EDGE_G, glow)
            val ox = cos(a - rot) * RO; val oy = sin(a - rot) * RO
            val ix = cos(a - rot) * (RO - 0.016f); val iy = sin(a - rot) * (RO - 0.016f)
            val ox2 = cos(a2 - rot) * RO; val oy2 = sin(a2 - rot) * RO
            val ix2 = cos(a2 - rot) * (RO - 0.016f); val iy2 = sin(a2 - rot) * (RO - 0.016f)
            v(ox, oy, eg, 1f); v(ix, iy, eg, -1f); v(ox2, oy2, eg, 1f)
            v(ix, iy, eg, -1f); v(ix2, iy2, eg, -1f); v(ox2, oy2, eg, 1f)
        }
    }

    private fun labelCircle() {
        val rot = deckRotation
        val n = 48
        for (j in 0 until n) {
            val a0 = j.toFloat() / n * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / n * 2f * PI.toFloat()
            v(0f, 0f, LB, 0f)
            v(cos(a0 - rot) * RLA, sin(a0 - rot) * RLA, LB, 1f)
            v(cos(a1 - rot) * RLA, sin(a1 - rot) * RLA, LB, 1f)
        }
    }

    private fun labelGlow() {
        val n = 40
        val pulse = 0.80f + 0.20f * sin(time * 0.7f)
        val gc = sc(LB, 0.18f * pulse)
        for (j in 0 until n) {
            val a0 = j.toFloat() / n * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / n * 2f * PI.toFloat()
            val ri = RLA + 0.003f; val ro = RLA + 0.035f
            v(cos(a0) * ri, sin(a0) * ri, sc(gc, 0.55f), 1f)
            v(cos(a0) * ro, sin(a0) * ro, sc(gc, 0.0f), -1f)
            v(cos(a1) * ri, sin(a1) * ri, sc(gc, 0.55f), 1f)
            v(cos(a1) * ro, sin(a1) * ro, sc(gc, 0.0f), -1f)
            v(cos(a0) * ro, sin(a0) * ro, sc(gc, 0.0f), -1f)
            v(cos(a1) * ri, sin(a1) * ri, sc(gc, 0.55f), 1f)
        }
    }

    private fun spindle() {
        val n = 12
        for (j in 0 until n) {
            val a0 = j.toFloat() / n * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / n * 2f * PI.toFloat()
            v(0f, 0f, SP, 0f)
            v(cos(a0) * RS, sin(a0) * RS, SP, 1f)
            v(cos(a1) * RS, sin(a1) * RS, SP, 1f)
        }
    }

    private fun wearMarks() {
        if (!wearInit || lastWearSeed != wearSeed) {
            lastWearSeed = wearSeed
            val rng = java.util.Random(wearSeed.toLong())
            for (i in 0 until WEAR_N) {
                wearR[i] = RPI + rng.nextFloat() * (RPO - RPI)
                wearA[i] = rng.nextFloat() * 2f * PI.toFloat()
                wearB[i] = 0.12f + rng.nextFloat() * 0.50f
            }
            wearInit = true
        }
        val rot = deckRotation
        for (i in 0 until WEAR_N) {
            val r = wearR[i]
            val a = wearA[i] - rot
            val bright = wearB[i] * (0.6f + 0.4f * sin(time * 0.35f + i.toFloat()))
            val c = sc(DUST_C, bright)
            val px = cos(a) * r; val py = sin(a) * r
            val a2 = a + 0.005f
            val px2 = cos(a2) * r; val py2 = sin(a2) * r
            seg(px, py, px2, py2, c, 0.0009f)
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // VOID — poeira + anéis + rays + nebula
    // ═══════════════════════════════════════════════════════════════════════
    private fun ambientDust() {
        if (!dustInit) {
            val rng = java.util.Random(77)
            for (i in 0 until DUST_N) {
                val angle = rng.nextFloat() * 2f * PI.toFloat()
                val r = 1.08f + rng.nextFloat() * 0.70f
                dustX[i] = cos(angle) * r
                dustY[i] = sin(angle) * r
                dustR[i] = r
                dustS[i] = 0.006f + rng.nextFloat() * 0.020f
                dustB[i] = 0.06f + rng.nextFloat() * 0.16f
            }
            dustInit = true
        }
        val crackleWinds = crackle * 0.15f  // dust moves faster with crackle
        for (i in 0 until DUST_N) {
            val angle = atan2(dustY[i], dustX[i]) + dustS[i] * (0.25f + crackleWinds)
            val r = dustR[i] + sin(time * 0.18f + i.toFloat() * 0.6f) * 0.045f
            val px = cos(angle) * r; val py = sin(angle) * r
            val bright = dustB[i] * (0.4f + 0.6f * sin(time * 0.5f + i.toFloat() * 1.2f))
            val c = sc(DUST_C, bright)
            circleFill(px, py, 0.003f, 5, c)
        }
    }

    private fun voidRings() {
        val ringRadii = floatArrayOf(1.12f, 1.30f, 1.52f)
        val ringAlpha = floatArrayOf(0.035f, 0.022f, 0.012f)
        for (k in ringRadii.indices) {
            val r = ringRadii[k]
            val alpha = ringAlpha[k] * (0.65f + 0.35f * sin(time * 0.25f + k.toFloat() * 1.1f))
            val c = sc(floatArrayOf(0.11f, 0.10f, 0.09f), alpha)
            val n = 90
            for (j in 0 until n) {
                val a0 = j.toFloat() / n * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / n * 2f * PI.toFloat()
                val hw = 0.0007f
                val p00 = floatArrayOf(cos(a0) * (r - hw), sin(a0) * (r - hw))
                val p01 = floatArrayOf(cos(a1) * (r - hw), sin(a1) * (r - hw))
                val p10 = floatArrayOf(cos(a0) * (r + hw), sin(a0) * (r + hw))
                val p11 = floatArrayOf(cos(a1) * (r + hw), sin(a1) * (r + hw))
                v(p00[0], p00[1], c, -1f); v(p01[0], p01[1], c, -1f); v(p10[0], p10[1], c, 1f)
                v(p01[0], p01[1], c, -1f); v(p11[0], p11[1], c, 1f); v(p10[0], p10[1], c, 1f)
            }
        }
    }

    // Radial light rays emanating from disc edge — fills empty void
    private fun voidRays() {
        val nRays = 30
        val rayLen = 0.50f
        val rot = deckRotation
        val cracklePulse = 1f + crackle * 0.4f  // rays flare with crackle
        for (k in 0 until nRays) {
            val baseAngle = k.toFloat() / nRays * 2f * PI.toFloat()
            val pulse = (0.5f + 0.5f * sin(time * 0.4f + k.toFloat() * 1.9f)) * cracklePulse
            val sway = sin(time * 0.2f + k.toFloat() * 1.1f) * 0.12f
            val angle = baseAngle + sway
            val fade = pulse * (0.015f + 0.008f * sin(k.toFloat() * 2.3f + time * 0.3f))
            val c = sc(AMB, fade)
            val ri = RO + 0.02f; val ro = RO + rayLen * (0.8f + 0.2f * pulse)
            val spread = 0.03f
            v(cos(angle) * ri, sin(angle) * ri, sc(c, 0.8f), 1f)
            v(cos(angle - spread) * ro, sin(angle - spread) * ro, sc(c, 0.0f), -1f)
            v(cos(angle + spread) * ro, sin(angle + spread) * ro, sc(c, 0.0f), -1f)
        }
    }

    // Nebula — faint colored patches in the void
    private fun nebulaPatches() {
        if (!dustInit) return
        val patches = arrayOf(
            floatArrayOf(0.12f, 0.06f, 0.18f),
            floatArrayOf(0.06f, 0.09f, 0.16f),
            floatArrayOf(0.10f, 0.08f, 0.04f),
        )
        val positions = arrayOf(
            floatArrayOf(1.25f, 0.4f),
            floatArrayOf(-0.9f, -0.8f),
            floatArrayOf(0.3f, 1.1f),
        )
        for (k in patches.indices) {
            val base = patches[k]
            val px = positions[k][0]; val py = positions[k][1]
            val pulse = 0.6f + 0.4f * sin(time * 0.15f + k.toFloat() * 2.1f)
            val c = sc(base, 0.025f * pulse)
            val n = 28
            val r = 0.18f + 0.04f * sin(time * 0.1f + k.toFloat())
            for (j in 0 until n) {
                val a0 = j.toFloat() / n * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / n * 2f * PI.toFloat()
                val ri = r * 0.3f; val ro = r
                v(cos(a0) * ri + px, sin(a0) * ri + py, sc(c, 0.4f), 1f)
                v(cos(a0) * ro + px, sin(a0) * ro + py, sc(c, 0.0f), -1f)
                v(cos(a1) * ri + px, sin(a1) * ri + py, sc(c, 0.4f), 1f)
                v(cos(a1) * ro + px, sin(a1) * ro + py, sc(c, 0.0f), -1f)
                v(cos(a0) * ro + px, sin(a0) * ro + py, sc(c, 0.0f), -1f)
                v(cos(a1) * ri + px, sin(a1) * ri + py, sc(c, 0.4f), 1f)
            }
        }
    }

    // Edge shimmer — bright pulse along the disc rim synced to crackle
    private fun edgeShimmer() {
        if (crackle < 0.02f) return
        val rot = deckRotation
        val n = 80
        val intensity = crackle * (0.5f + 0.5f * sin(time * 4.0f))  // faster, more alive
        for (j in 0 until n) {
            val a0 = j.toFloat() / n * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / n * 2f * PI.toFloat()
            val shimmer = sin(a0 * 9f + rot * 4f + time * 3.5f) * 0.5f + 0.5f  // higher freq
            val alpha = shimmer * intensity * 0.15f
            val c = sc(AMB, alpha)
            val ri = 0.985f; val ro = 1.015f
            v(cos(a0 - rot) * ri, sin(a0 - rot) * ri, c, 1f)
            v(cos(a0 - rot) * ro, sin(a0 - rot) * ro, c, -1f)
            v(cos(a1 - rot) * ri, sin(a1 - rot) * ri, c, 1f)
            v(cos(a1 - rot) * ro, sin(a1 - rot) * ro, c, -1f)
            v(cos(a0 - rot) * ro, sin(a0 - rot) * ro, c, -1f)
            v(cos(a1 - rot) * ri, sin(a1 - rot) * ri, c, 1f)
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // TRAILING BEAM + PONTO DA AGULHA
    // ═══════════════════════════════════════════════════════════════════════
    private fun needleBeam() {
        if (armLift > 0.5f) return
        val r = RPO + (RPI - RPO) * playProgress
        val pulse = 0.80f + 0.20f * sin(time * 1.6f)

        // ── Groove highlight near needle — the groove being read ──
        val ghN = 24
        val ghArc = 0.6f
        val ghBright = crackle * 0.20f * pulse
        for (j in 0 until ghN) {
            val a0 = PVA - ghArc / 2f + j.toFloat() / ghN * ghArc
            val a1 = PVA - ghArc / 2f + (j + 1).toFloat() / ghN * ghArc
            val fade = 1f - abs(a0 - PVA) / (ghArc / 2f)
            val c = sc(AMB, ghBright * fade * fade)
            val ri = r - 0.012f; val ro = r + 0.012f
            v(cos(a0) * ri, sin(a0) * ri, c, 1f)
            v(cos(a0) * ro, sin(a0) * ro, c, -1f)
            v(cos(a1) * ri, sin(a1) * ri, c, 1f)
            v(cos(a1) * ro, sin(a1) * ro, c, -1f)
            v(cos(a0) * ro, sin(a0) * ro, c, -1f)
            v(cos(a1) * ri, sin(a1) * ri, c, 1f)
        }

        // ── Trailing arc — tight, sharp trail behind the needle ──
        val arcLen = 1.2f
        val arcN = 48
        val rot = deckRotation
        for (j in 0 until arcN) {
            val t0 = j.toFloat() / arcN
            val t1 = (j + 1).toFloat() / arcN
            val a0 = PVA + rot - t0 * arcLen
            val a1 = PVA + rot - t1 * arcLen
            val fade = (1f - t0).toDouble().pow(2.2).toFloat()
            val fade1 = (1f - t1).toDouble().pow(2.2).toFloat()
            val w0 = 0.0020f + 0.005f * fade
            val w1 = 0.0020f + 0.005f * fade1
            val c0 = sc(AMB, fade * pulse * 0.55f)
            val c1 = sc(AMB, fade1 * pulse * 0.55f)
            val o0x = cos(a0) * (r + w0); val o0y = sin(a0) * (r + w0)
            val i0x = cos(a0) * (r - w0); val i0y = sin(a0) * (r - w0)
            val o1x = cos(a1) * (r + w1); val o1y = sin(a1) * (r + w1)
            val i1x = cos(a1) * (r - w1); val i1y = sin(a1) * (r - w1)
            v(i0x, i0y, c0, -1f); v(i1x, i1y, c1, -1f); v(o0x, o0y, c0, 1f)
            v(i1x, i1y, c1, -1f); v(o1x, o1y, c1, 1f); v(o0x, o0y, c0, 1f)
        }

        // ── Hot point — the stylus contact ──
        val ax = cos(PVA) * r; val ay = sin(PVA) * r
        circleFill(ax, ay, 0.030f, 18, sc(AMB, 0.07f * pulse))
        circleFill(ax, ay, 0.018f, 14, sc(AMB, 0.16f * pulse))
        circleRing(ax, ay, 0.013f, 12, sc(AMB, 0.30f * pulse))
        circleFill(ax, ay, 0.008f, 10, sc(AMB, 0.85f * pulse))
        circleFill(ax, ay, 0.003f, 8, floatArrayOf(1.0f, 0.88f, 0.55f))
    }

    // ═══════════════════════════════════════════════════════════════════════
    // FAÍSCAS — 3 camadas
    // ═══════════════════════════════════════════════════════════════════════
    private fun sparks() {
        if (crackle < 0.02f || armLift > 0.5f) return
        val r = RPO + (RPI - RPO) * playProgress
        val ax = cos(PVA) * r; val ay = sin(PVA) * r
        val pulse = 0.75f + 0.25f * sin(time * 3.2f)

        // Soft glow at contact point
        circleFill(ax, ay, 0.045f, 20, sc(AMB, 0.05f * crackle * pulse))

        // Fine sparks — tight, mechanical
        val rng1 = java.util.Random((time * 30).toInt().toLong())
        val cnt1 = (30 * crackle).toInt()
        for (k in 0 until cnt1) {
            val spread = (rng1.nextFloat() - 0.5f) * 0.45f
            val a = PVA + spread
            val dr = (rng1.nextFloat() - 0.3f) * 0.05f
            val rr = r + dr
            val b = (0.25f + rng1.nextFloat() * 0.75f) * crackle
            val c = sc(AMB, b)
            val px = cos(a) * rr; val py = sin(a) * rr
            val spin = deckRotation * 0.08f * rng1.nextFloat()
            val dx = cos(a + spin + PI.toFloat() / 2f) * 0.005f * rng1.nextFloat()
            val dy = sin(a + spin + PI.toFloat() / 2f) * 0.005f * rng1.nextFloat()
            seg(px, py, px + dx, py + dy, c, 0.0010f)
        }

        // Thick sparks — fewer, brighter
        val rng2 = java.util.Random((time * 10).toInt().toLong() + 777)
        val cnt2 = (8 * crackle).toInt()
        for (k in 0 until cnt2) {
            val spread = (rng2.nextFloat() - 0.5f) * 0.25f
            val a = PVA + spread
            val rr = r + (rng2.nextFloat() - 0.2f) * 0.03f
            val b = (0.55f + rng2.nextFloat() * 0.45f) * crackle
            val c = sc(AMB, b)
            val px = cos(a) * rr; val py = sin(a) * rr
            val dx = cos(a + PI.toFloat() / 2f) * 0.007f * rng2.nextFloat()
            val dy = sin(a + PI.toFloat() / 2f) * 0.007f * rng2.nextFloat()
            seg(px, py, px + dx, py + dy, c, 0.0016f)
            circleFill(px + dx / 2, py + dy / 2, 0.0025f, 6, sc(AMB, b * 0.25f))
        }
    }

    // ═══════════════════════════════════════════════════════════════════════
    // BRAÇO — detalhado, com glow e cantilever
    // ═══════════════════════════════════════════════════════════════════════
    private fun armLine() {
        val playR = RPO + (RPI - RPO) * playProgress
        val r = if (armLift > 0.5f) ARR_REST else playR
        val lift = armLift
        val ang = Math.toRadians(38.0).toFloat()
        val pvR = 1.24f
        val px = cos(ang) * pvR + 0.06f
        val py = sin(ang) * pvR + 0.10f
        val ux = -px; val uy = -py
        val ul = sqrt(ux * ux + uy * uy).coerceAtLeast(1e-6f)
        var tx = px + ux / ul * (ul - r)
        var ty = py + uy / ul * (ul - r)
        // Subtle cartridge vibration when playing
        if (lift < 0.5f) {
            val vib = 0.0005f * crackle
            tx += sin(time * 35.0f) * vib
            ty += cos(time * 27.0f) * vib * 0.6f
        }
        val bright = 1f + lift * 0.35f
        val c = sc(ARM, bright)
        val cHi = sc(ARM_HI, bright)

        // Arm glow — warm light from disc reflecting on metal
        if (lift < 0.5f) {
            val glowA = 0.012f * (1f - lift) * (0.7f + 0.3f * crackle)
            val glowC = sc(AMB, glowA)
            seg(px, py, tx, ty, glowC, 0.025f)
        }

        // Counterweight
        val cwX = px + (ux / ul) * 0.070f; val cwY = py + (uy / ul) * 0.070f
        circleRing(cwX, cwY, 0.030f, 18, sc(ARM, 0.45f * bright))
        circleRing(cwX, cwY, 0.022f, 16, sc(ARM_HI, 0.25f * bright))
        circleFill(cwX, cwY, 0.016f, 12, sc(ARM_D, 0.35f * bright))
        circleRing(cwX, cwY, 0.026f, 14, sc(ARM_D, 0.20f * bright))

        // Arm tube — 4 layers for clean depth
        seg(px, py, tx, ty, sc(ARM_D, bright * 0.5f), 0.014f)
        seg(px, py, tx, ty, sc(ARM_D, bright * 0.8f), 0.009f)
        seg(px, py, tx, ty, c, 0.006f)
        seg(px, py, tx, ty, cHi, 0.0022f)

        // Headshell
        val armDx = tx - px; val armDy = ty - py
        val armLen = sqrt(armDx * armDx + armDy * armDy).coerceAtLeast(1e-6f)
        val perpX = -armDy / armLen; val perpY = armDx / armLen
        val cartDirX = armDx / armLen; val cartDirY = armDy / armLen

        val hsLen = 0.012f
        val hsW0 = 0.004f; val hsW1 = 0.008f
        val h0x = tx; val h0y = ty
        val h1x = tx + cartDirX * hsLen; val h1y = ty + cartDirY * hsLen
        v(h0x + perpX * hsW0, h0y + perpY * hsW0, sc(ARM, 0.85f * bright), -1f)
        v(h0x - perpX * hsW0, h0y - perpY * hsW0, sc(ARM, 0.85f * bright), -1f)
        v(h1x + perpX * hsW1, h1y + perpY * hsW1, sc(ARM, 0.90f * bright), 1f)
        v(h0x - perpX * hsW0, h0y - perpY * hsW0, sc(ARM, 0.85f * bright), -1f)
        v(h1x - perpX * hsW1, h1y - perpY * hsW1, sc(ARM, 0.90f * bright), 1f)
        v(h1x + perpX * hsW1, h1y + perpY * hsW1, sc(ARM, 0.90f * bright), 1f)

        // Cartridge body
        val cBaseX = h1x; val cBaseY = h1y
        val cartW = 0.012f; val cartH = 0.022f
        val c0x = cBaseX + perpX * cartW; val c0y = cBaseY + perpY * cartW
        val c1x = cBaseX - perpX * cartW; val c1y = cBaseY - perpY * cartW
        val c2x = c0x + cartDirX * cartH; val c2y = c0y + cartDirY * cartH
        val c3x = c1x + cartDirX * cartH; val c3y = c1y + cartDirY * cartH
        val cartC = sc(ARM, 0.92f * bright)
        val cartHi = sc(ARM_HI, 0.72f * bright)
        val cartSh = sc(ARM_D, 1.1f * bright)
        val so = 0.003f
        v(c0x + so, c0y - so, sc(cartSh, 0.5f), -1f); v(c1x + so, c1y - so, sc(cartSh, 0.5f), -1f)
        v(c2x + so, c2y - so, sc(cartSh, 0.5f), 1f)
        v(c1x + so, c1y - so, sc(cartSh, 0.5f), -1f); v(c3x + so, c3y - so, sc(cartSh, 0.5f), 1f)
        v(c2x + so, c2y - so, sc(cartSh, 0.5f), 1f)
        v(c0x, c0y, cartC, -1f); v(c1x, c1y, cartC, -1f); v(c2x, c2y, cartC, 1f)
        v(c1x, c1y, cartC, -1f); v(c3x, c3y, cartC, 1f); v(c2x, c2y, cartC, 1f)
        v(c0x, c0y, cartHi, -1f); v(c0x, c0y, cartHi, 1f); v(c2x, c2y, cartHi, 1f)
        v(c1x, c1y, sc(cartHi, 0.5f), -1f); v(c3x, c3y, sc(cartHi, 0.5f), 1f); v(c1x, c1y, sc(cartHi, 0.5f), 1f)

        // Cantilever
        val cantLen = 0.018f
        val cantW = 0.0012f
        val cantEndX = cBaseX + cartDirX * (cartH + cantLen)
        val cantEndY = cBaseY + cartDirY * (cartH + cantLen)
        seg(cBaseX + cartDirX * cartH, cBaseY + cartDirY * cartH,
            cantEndX, cantEndY, sc(ARM_HI, 0.90f * bright), cantW)

        // Stylus tip
        val sx = cantEndX; val sy = cantEndY
        if (lift < 0.5f) {
            circleFill(sx, sy, 0.007f, 10, sc(AMB, 0.12f * bright))
        }
        circleFill(sx, sy, 0.004f, 8, sc(AMB, 0.85f * bright))
        circleFill(sx, sy, 0.0025f, 6, floatArrayOf(1.0f, 0.88f, 0.55f))
        circleFill(sx, sy, 0.0012f, 6, floatArrayOf(1.0f, 0.96f, 0.82f))

        // Pivot — triple ring
        circleRing(px, py, 0.032f, 20, sc(ARM_D, 0.35f * bright))
        circleRing(px, py, 0.026f, 16, cHi)
        circleRing(px, py, 0.020f, 14, sc(ARM, 0.55f * bright))
        circleFill(px, py, 0.012f, 10, sc(ARM_D, 0.30f * bright))

        // Arm rest
        if (lift > 0.5f) {
            val rx = 0.86f; val ry = 0.66f
            circleRing(rx, ry, 0.022f, 14, sc(ARM, 0.8f))
            circleRing(rx, ry, 0.016f, 12, sc(ARM_HI, 0.4f))
            circleFill(rx, ry, 0.008f, 8, sc(ARM_D, 0.3f))
        }
    }
    private val ARR_REST = 1.06f

    // ═══════════════════════════════════════════════════════════════════════
    // Primitivas
    // ═══════════════════════════════════════════════════════════════════════
    private fun sheen(theta: Float, light: Float): Float {
        val d2 = ((theta - light + PI.toFloat() / 2f) % PI.toFloat()) - PI.toFloat() / 2f
        return exp(-d2 * d2 / 0.045f)  // tighter, sharper highlight
    }
    private fun lerp(a: FloatArray, b: FloatArray, t: Float) =
        floatArrayOf(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
    private fun sc(a: FloatArray, s: Float) = floatArrayOf(a[0] * s, a[1] * s, a[2] * s)
    private fun add(a: FloatArray, b: FloatArray) = floatArrayOf(a[0] + b[0], a[1] + b[1], a[2] + b[2])
    private fun v(x: Float, y: Float, c: FloatArray, e: Float) {
        if (vi + 7 > SZ) return
        vb[vi++] = x; vb[vi++] = y
        vb[vi++] = c[0]; vb[vi++] = c[1]; vb[vi++] = c[2]; vb[vi++] = 1f
        vb[vi++] = e
    }
    private fun seg(x0: Float, y0: Float, x1: Float, y1: Float, c: FloatArray, hw: Float = 0.0035f) {
        val dx = x1 - x0; val dy = y1 - y0
        val len = sqrt(dx * dx + dy * dy).coerceAtLeast(1e-6f)
        val nx = -dy / len * hw; val ny = dx / len * hw
        v(x0 + nx, y0 + ny, c, -1f); v(x0 - nx, y0 - ny, c, 1f); v(x1 + nx, y1 + ny, c, -1f)
        v(x0 - nx, y0 - ny, c, 1f); v(x1 - nx, y1 - ny, c, 1f); v(x1 + nx, y1 + ny, c, -1f)
    }
    private fun circleFill(cx: Float, cy: Float, r: Float, n: Int, c: FloatArray) {
        for (j in 0 until n) {
            val a0 = j.toFloat() / n * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / n * 2f * PI.toFloat()
            v(cx, cy, c, 0f)
            v(cx + cos(a0) * r, cy + sin(a0) * r, c, 1f)
            v(cx + cos(a1) * r, cy + sin(a1) * r, c, 1f)
        }
    }
    private fun circleRing(cx: Float, cy: Float, r: Float, n: Int, c: FloatArray) {
        val hw = 0.0020f
        for (j in 0 until n) {
            val a0 = j.toFloat() / n * 2f * PI.toFloat()
            val a1 = (j + 1).toFloat() / n * 2f * PI.toFloat()
            val p00 = floatArrayOf(cx + cos(a0) * (r - hw), cy + sin(a0) * (r - hw))
            val p01 = floatArrayOf(cx + cos(a1) * (r - hw), cy + sin(a1) * (r - hw))
            val p10 = floatArrayOf(cx + cos(a0) * (r + hw), cy + sin(a0) * (r + hw))
            val p11 = floatArrayOf(cx + cos(a1) * (r + hw), cy + sin(a1) * (r + hw))
            v(p00[0], p00[1], c, -1f); v(p01[0], p01[1], c, -1f); v(p10[0], p10[1], c, 1f)
            v(p01[0], p01[1], c, -1f); v(p11[0], p11[1], c, 1f); v(p10[0], p10[1], c, 1f)
        }
    }
    private fun flush(useModel: Boolean) {
        val n = vi / 7; if (n < 2) return
        if (useModel) GL.glUniformMatrix4fv(uMvp, 1, false, model, 0)
        val bb = ByteBuffer.allocateDirect(vi * 4).order(ByteOrder.nativeOrder())
        bb.asFloatBuffer().put(vb, 0, vi)
        bb.position(0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, false, 28, bb)
        GL.glEnableVertexAttribArray(1)
        bb.position(8)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, false, 28, bb)
        GL.glEnableVertexAttribArray(2)
        bb.position(24)
        GL.glVertexAttribPointer(2, 1, GL.GL_FLOAT, false, 28, bb)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, n)
    }
    private fun qbo(): Int {
        val d = floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f)
        val b = ByteBuffer.allocateDirect(32).order(ByteOrder.nativeOrder()).asFloatBuffer()
        b.put(d).flip()
        val ids = IntArray(1); GL.glGenBuffers(1, ids, 0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, ids[0])
        GL.glBufferData(GL.GL_ARRAY_BUFFER, 32, b, GL.GL_STATIC_DRAW)
        return ids[0]
    }
    private fun sh(vs: String, fs: String): Int {
        fun s(type: Int, src: String): Int {
            val sh = GL.glCreateShader(type)
            GL.glShaderSource(sh, src); GL.glCompileShader(sh)
            val ok = IntArray(1); GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS, ok, 0)
            if (ok[0] == 0) Log.e("VR", "Shader: ${GL.glGetShaderInfoLog(sh)}")
            return sh
        }
        val p = GL.glCreateProgram()
        GL.glAttachShader(p, s(GL.GL_VERTEX_SHADER, vs))
        GL.glAttachShader(p, s(GL.GL_FRAGMENT_SHADER, fs))
        GL.glLinkProgram(p)
        return p
    }
}
