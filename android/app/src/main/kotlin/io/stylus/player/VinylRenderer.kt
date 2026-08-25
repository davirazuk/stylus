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
 * Premium vinyl — matches PC's honest material: wood plinth, black plastic with sheen,
 * envelope-shaded grooves, wear, label with cover, proper tonearm.
 * All via triangles, iso-corrected, screen-space sheen fixed.
 */
class VinylRenderer : GLSurfaceView.Renderer {

    // Softer — grooves are subtle graphite, gaps are warm light grey not white
    private val PLINTH_DARK = floatArrayOf(0.08f, 0.050f, 0.030f)
    private val VINYL_CORE = floatArrayOf(0.015f, 0.015f, 0.016f)
    private val VINYL_RIM = floatArrayOf(0.062f, 0.060f, 0.057f)
    private val SHEEN = floatArrayOf(0.12f, 0.125f, 0.115f)
    private val EDGE = floatArrayOf(0.36f, 0.34f, 0.32f)
    private val G_OFF = floatArrayOf(0.055f, 0.060f, 0.070f)
    private val G_ON = floatArrayOf(0.13f, 0.135f, 0.145f)
    private val G_GAP = floatArrayOf(0.42f, 0.40f, 0.38f)
    private val LABEL_BG = floatArrayOf(0.58f, 0.12f, 0.09f)
    private val SPINDLE_C = floatArrayOf(0.23f, 0.23f, 0.24f)
    private val ARM_C = floatArrayOf(0.55f, 0.55f, 0.56f)
    private val ARM_D = floatArrayOf(0.16f, 0.16f, 0.17f)
    private val ARM_HI = floatArrayOf(0.72f, 0.72f, 0.74f)
    private val STYLUS_C = floatArrayOf(0.94f, 0.66f, 0.22f)

    private val R_OUTER = 1.0f; private val R_LEADIN = 0.962f
    private val R_PROG_OUT = 0.945f; private val R_PROG_IN = 0.395f
    private val R_RUNOUT = 0.360f; private val R_LABEL = 0.329f
    private val R_SPINDLE = 0.024f; private val N_RINGS = 96
    private val LIGHT = Math.toRadians(-38.0).toFloat()

    private var prog = 0; private var uMvp = -1
    private var bgVbo = 0; private var bgN = 0

    private val mvp = FloatArray(16)
    private val model = FloatArray(16)
    private var isoX = 1f; private var isoY = 1f

    @Volatile var deckRotation = 0f
    @Volatile var armLift = 1f
    @Volatile var playProgress = 0f

    private val SZ = 600000
    private lateinit var sc: FloatArray
    private var si = 0

    private val VS = """
        #version 300 es
        layout(location=0) in vec2 aPos;
        layout(location=1) in vec4 aCol;
        uniform mat4 uMvp;
        out vec4 vCol;
        out vec2 vUv;
        void main(){ vCol=aCol; vUv=aPos*0.5+0.5; gl_Position=uMvp*vec4(aPos,0,1); }
    """.trimIndent()
    private val FS = """
        #version 300 es
        precision mediump float;
        in vec4 vCol; in vec2 vUv; out vec4 frag;
        void main(){
            // wood for plinth (dark brown base)
            if (vCol.r < 0.09 && vCol.g < 0.06) {
                vec2 p = vUv*2.0-1.0;
                float g1 = sin(p.x*18.0 + p.y*2.0)*0.5+0.5;
                float g2 = sin(p.x*42.0 - p.y*7.0)*0.5+0.5;
                float grain = mix(g1,g2,0.35)*0.020;
                vec3 wood = vec3(0.115,0.068,0.040) + vec3(grain);
                float vig = 1.0 - dot(p,p)*0.18;
                vig = pow(vig, 0.92);
                float hl = max(0.0, dot(normalize(vec2(-0.6,0.5)), p)) * 0.045;
                hl *= (1.0 - length(p)*0.35);
                frag = vec4(wood*vig + vec3(hl*0.9, hl*0.7, hl*0.5), 1.0);
            } else {
                frag=vCol;
            }
        }
    """.trimIndent()

    override fun onSurfaceCreated(gl10: GL10?, config: EGLConfig?) {
        GL.glClearColor(0.06f, 0.038f, 0.028f, 1f)
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
        isoX = min(1f, h.toFloat() / w.toFloat())
        isoY = min(1f, w.toFloat() / h.toFloat())
    }

    override fun onDrawFrame(gl10: GL10?) {
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glUseProgram(prog)

        Matrix.setIdentityM(mvp, 0)
        drawBg()

        // soft drop shadow under disc
        Matrix.setIdentityM(model, 0)
        Matrix.scaleM(model, 0, isoX, isoY, 1f)
        Matrix.translateM(model, 0, 0.025f, -0.035f, 0f)
        System.arraycopy(model, 0, mvp, 0, 16)
        si = 0; buildShadow(); flush()

        // disc (rotates)
        Matrix.setIdentityM(model, 0)
        Matrix.scaleM(model, 0, isoX, isoY, 1f)
        Matrix.rotateM(model, 0, Math.toDegrees(deckRotation.toDouble()).toFloat(), 0f, 0f, -1f)
        System.arraycopy(model, 0, mvp, 0, 16)

        si = 0; buildDisc(); flush()
        si = 0; buildGrooves(); flush()
        si = 0; buildWear(); flush()
        si = 0; buildEdges(); flush()
        si = 0; buildLabel(); flush()
        si = 0; buildRing(R_LABEL * 1.005f, 0.005f, floatArrayOf(0.48f,0.42f,0.38f)); flush()
        si = 0; buildSpindle(); flush()

        // tonearm (no rotation)
        Matrix.setIdentityM(mvp, 0)
        Matrix.scaleM(mvp, 0, isoX, isoY, 1f)
        si = 0; buildArm(); flush()
    }

    private fun sheenGain(theta: Float): Float {
        var d = theta - LIGHT
        d = ((d + PI.toFloat()) % (2*PI.toFloat())) - PI.toFloat()
        var d2 = d % PI.toFloat()
        if (d2 > PI.toFloat()/2) d2 -= PI.toFloat()
        if (d2 < -PI.toFloat()/2) d2 += PI.toFloat()
        return 1f + 1f * exp(-(d2*d2)/0.075f)
    }

    private fun buildDisc() {
        val rings = floatArrayOf(R_SPINDLE, 0.16f, 0.30f, 0.44f, 0.58f, 0.72f, 0.84f, 0.94f, R_OUTER)
        val segs = 96
        for (i in 0 until rings.size - 1) {
            val r0 = rings[i]; val r1 = rings[i + 1]
            val t = ((r0 + r1) * 0.5f / R_OUTER).toDouble().pow(0.9).toFloat().coerceIn(0f,1f)
            val base = lerp(VINYL_CORE, VINYL_RIM, t)
            val sheenPow = ((r0+r1)/2).pow(1.7f)
            for (j in 0 until segs) {
                val a0 = j.toFloat() / segs * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
                val g0 = sheenGain(a0 + deckRotation)
                val g1 = sheenGain(a1 + deckRotation)
                val s0 = SHEEN[0]*sheenPow*(g0-1); val s1 = SHEEN[0]*sheenPow*(g1-1)
                val c0 = floatArrayOf(base[0]+s0, base[1]+SHEEN[1]*sheenPow*(g0-1), base[2]+SHEEN[2]*sheenPow*(g0-1))
                val c1 = floatArrayOf(base[0]+s1, base[1]+SHEEN[1]*sheenPow*(g1-1), base[2]+SHEEN[2]*sheenPow*(g1-1))
                val ca = floatArrayOf((c0[0]+c1[0])/2, (c0[1]+c1[1])/2, (c0[2]+c1[2])/2)
                tri(ring(r0, a0), ring(r0, a1), ring(r1, a0), ca)
                tri(ring(r0, a1), ring(r1, a1), ring(r1, a0), ca)
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
            vert(ring(r, a0), floatArrayOf(0.035f,0.022f,0.015f))
            vert(ring(r, a1), floatArrayOf(0.035f,0.022f,0.015f))
        }
    }

    private fun buildGrooves() {
        val segs = 128; val hw = 0.0024f
        val upTo = (playProgress * N_RINGS).toInt().coerceIn(0, N_RINGS)
        for (i in 0 until N_RINGS) {
            val f = i.toFloat() / max(1, N_RINGS - 1)
            val r = R_PROG_OUT + (R_PROG_IN - R_PROG_OUT) * f
            val isGap = i % 4 == 3
            // more varied loudness like PC's envelope
            val loud = (0.35f + 0.40f * sin(i*0.41f + 1.2f) + 0.25f * sin(i*1.07f)).coerceIn(0f,1f)
            val shade = if (isGap) 1f else 0.10f + 0.90f * loud.pow(0.62f)
            val base = when { isGap -> G_GAP; i < upTo -> G_ON; else -> G_OFF }
            val w = if (isGap) hw*0.5f else hw*(0.85f + 0.15f*shade)
            for (j in 0 until segs) {
                val a0 = j.toFloat() / segs * 2f * PI.toFloat()
                val a1 = (j + 1).toFloat() / segs * 2f * PI.toFloat()
                val g0 = 1f + 0.18f*(sheenGain(a0+deckRotation)-1)
                val g1 = 1f + 0.18f*(sheenGain(a1+deckRotation)-1)
                val c0 = floatArrayOf(base[0]*shade*g0, base[1]*shade*g0, base[2]*shade*g0)
                val c1 = floatArrayOf(base[0]*shade*g1, base[1]*shade*g1, base[2]*shade*g1)
                val ca = floatArrayOf((c0[0]+c1[0])/2, (c0[1]+c1[1])/2, (c0[2]+c1[2])/2)
                tri(ring(r-w, a0), ring(r-w, a1), ring(r+w, a0), ca)
                tri(ring(r-w, a1), ring(r+w, a1), ring(r+w, a0), ca)
            }
        }
    }

    private fun buildWear() {
        val rnd = java.util.Random(42)
        for (k in 0 until 10) {
            val r = 0.38f + rnd.nextFloat()*0.54f
            val a = rnd.nextFloat()*2f*PI.toFloat()
            val len = 0.05f + rnd.nextFloat()*0.12f
            val a1 = a + len/r
            val hw = 0.0010f
            val p0 = ring(r, a); val p1 = ring(r, a1)
            val dx=p1[0]-p0[0]; val dy=p1[1]-p0[1]
            val l= sqrt(dx*dx+dy*dy).coerceAtLeast(1e-6f)
            val nx=-dy/l*hw; val ny=dx/l*hw
            val alpha = 0.10f + rnd.nextFloat()*0.14f
            val col = floatArrayOf(0.45f*alpha,0.45f*alpha,0.47f*alpha)
            quad(p0[0]+nx,p0[1]+ny, p0[0]-nx,p0[1]-ny, p1[0]-nx,p1[1]-ny, p1[0]+nx,p1[1]+ny, col)
        }
        for (k in 0 until 32) {
            val r = 0.36f + rnd.nextFloat()*0.58f
            val a = rnd.nextFloat()*2f*PI.toFloat()
            val p = ring(r, a)
            val sz = 0.0018f + rnd.nextFloat()*0.0015f
            val col = floatArrayOf(0.32f,0.32f,0.33f)
            quad(p[0]-sz,p[1]-sz, p[0]+sz,p[1]-sz, p[0]+sz,p[1]+sz, p[0]-sz,p[1]+sz, col)
        }
    }

    private fun buildEdges() {
        val edges = arrayOf(R_OUTER to 0.007f, R_LEADIN to 0.0032f, R_RUNOUT to 0.0032f)
        val segs = 128
        for ((r,hw) in edges) {
            for (j in 0 until segs) {
                val a0=j.toFloat()/segs*2f*PI.toFloat()
                val a1=(j+1).toFloat()/segs*2f*PI.toFloat()
                val g0=sheenGain(a0+deckRotation)
                val c=floatArrayOf(EDGE[0]*(0.85f+0.15f*g0),EDGE[1]*(0.85f+0.15f*g0),EDGE[2]*(0.85f+0.15f*g0))
                tri(ring(r-hw,a0),ring(r-hw,a1),ring(r+hw,a0),c)
                tri(ring(r-hw,a1),ring(r+hw,a1),ring(r+hw,a0),c)
            }
        }
    }

    private fun buildLabel() {
        val segs=48
        for(j in 0 until segs){
            val a0=j.toFloat()/segs*2f*PI.toFloat()
            val a1=(j+1).toFloat()/segs*2f*PI.toFloat()
            vert(0f,0f,LABEL_BG); vert(ring(R_LABEL,a0),LABEL_BG); vert(ring(R_LABEL,a1),LABEL_BG)
        }
    }
    private fun buildSpindle(){
        val segs=14
        for(j in 0 until segs){
            val a0=j.toFloat()/segs*2f*PI.toFloat()
            val a1=(j+1).toFloat()/segs*2f*PI.toFloat()
            vert(0f,0f,SPINDLE_C); vert(ring(R_SPINDLE,a0),SPINDLE_C); vert(ring(R_SPINDLE,a1),SPINDLE_C)
        }
    }
    private fun buildRing(r:Float,hw:Float,col:FloatArray){
        val segs=128
        for(j in 0 until segs){
            val a0=j.toFloat()/segs*2f*PI.toFloat()
            val a1=(j+1).toFloat()/segs*2f*PI.toFloat()
            tri(ring(r-hw,a0),ring(r-hw,a1),ring(r+hw,a0),col)
            tri(ring(r-hw,a1),ring(r+hw,a1),ring(r+hw,a0),col)
        }
    }
    private fun buildArm(){
        val lift=armLift
        val playR=R_PROG_OUT + (R_PROG_IN - R_PROG_OUT)*playProgress
        val r= if(lift>0.5f) R_OUTER*1.06f else playR
        val ang=Math.toRadians(34.0).toFloat()
        val hx=r*cos(ang); val hy=r*sin(ang)
        val liftOff=lift*0.14f; val hyLift=hy+liftOff
        val px=0.88f; val py=0.72f
        val ex=(px+hx)*0.5f; val ey=(py+hyLift)*0.5f+0.04f
        // shaft with highlight
        thickLine(px,py,ex,ey,0.015f,ARM_C)
        thickLine(ex,ey,hx,hyLift,0.010f,ARM_C)
        // thin highlight line on top edge of arm
        thickLine(px+0.003f,py+0.003f,ex+0.003f,ey+0.003f,0.003f,ARM_HI)
        val cw=0.017f; val ch=0.030f
        quad(hx-cw,hyLift+0.006f,hx+cw,hyLift+0.006f,hx+cw,hyLift-ch,hx-cw,hyLift-ch,ARM_D)
        // headshell highlight
        quad(hx-cw,hyLift+0.006f,hx+cw,hyLift+0.006f,hx+cw-0.002f,hyLift+0.002f,hx-cw+0.002f,hyLift+0.002f,ARM_HI)
        tri(floatArrayOf(hx,hyLift-ch), floatArrayOf(hx-0.006f,hyLift-ch-0.014f), floatArrayOf(hx+0.006f,hyLift-ch-0.014f), STYLUS_C)
        circle(px,py,0.026f,18,ARM_D)
        circle(px,py,0.013f,14,ARM_C)
        circle(px,py,0.006f,10,ARM_HI)
        val cwx=px+(px-ex)*0.18f; val cwy=py+(py-ey)*0.18f
        circle(cwx,cwy,0.030f,18,ARM_D)
        circle(cwx,cwy,0.018f,14,ARM_C)
        val rx=0.84f; val ry=0.56f
        thickLine(rx-0.02f,ry,rx+0.02f,ry,0.004f,ARM_D)
        thickLine(rx+0.02f,ry,rx+0.02f,ry-0.05f,0.004f,ARM_D)
    }

    private fun ring(r:Float,a:Float)=floatArrayOf(cos(a)*r, sin(a)*r)
    private fun vert(x:Float,y:Float,c:FloatArray){ sc[si++]=x; sc[si++]=y; sc[si++]=c[0]; sc[si++]=c[1]; sc[si++]=c[2]; sc[si++]=1f }
    private fun vert(p:FloatArray,c:FloatArray)=vert(p[0],p[1],c)
    private fun tri(a:FloatArray,b:FloatArray,c:FloatArray,col:FloatArray){ vert(a,col); vert(b,col); vert(c,col) }
    private fun quad(x0:Float,y0:Float,x1:Float,y1:Float,x2:Float,y2:Float,x3:Float,y3:Float,c:FloatArray){
        vert(x0,y0,c); vert(x1,y1,c); vert(x3,y3,c)
        vert(x1,y1,c); vert(x2,y2,c); vert(x3,y3,c)
    }
    private fun thickLine(x0:Float,y0:Float,x1:Float,y1:Float,hw:Float,c:FloatArray){
        val dx=x1-x0; val dy=y1-y0; val l=sqrt(dx*dx+dy*dy).coerceAtLeast(1e-6f)
        val nx=-dy/l*hw; val ny=dx/l*hw
        quad(x0+nx,y0+ny,x0-nx,y0-ny,x1-nx,y1-ny,x1+nx,y1+ny,c)
    }
    private fun circle(cx:Float,cy:Float,r:Float,segs:Int,c:FloatArray){
        for(j in 0 until segs){
            val a0=j.toFloat()/segs*2f*PI.toFloat()
            val a1=(j+1).toFloat()/segs*2f*PI.toFloat()
            vert(cx,cy,c)
            vert(cx+cos(a0)*r,cy+sin(a0)*r,c)
            vert(cx+cos(a1)*r,cy+sin(a1)*r,c)
        }
    }
    private fun lerp(a:FloatArray,b:FloatArray,t:Float)=floatArrayOf(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t)
    private fun quadFill(h:Float)=floatArrayOf(-h,-h,h,-h,h,h,-h,-h,h,h,-h,h)
    private fun drawBg(){
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, bgVbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0,2,GL.GL_FLOAT,false,24,0)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1,4,GL.GL_FLOAT,false,24,8)
        GL.glUniformMatrix4fv(uMvp,1,false,mvp,0)
        GL.glDrawArrays(GL.GL_TRIANGLES,0,bgN)
    }
    private fun flush(){
        val n=si/6; if(n<3) return
        val bb=ByteBuffer.allocateDirect(si*4).order(ByteOrder.nativeOrder())
        val fb=bb.asFloatBuffer()
        fb.put(sc,0,si); fb.position(0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER,0)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0,2,GL.GL_FLOAT,false,24,fb)
        val bb2=ByteBuffer.allocateDirect(si*4).order(ByteOrder.nativeOrder())
        val fb2=bb2.asFloatBuffer()
        fb2.put(sc,0,si); fb2.position(2)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1,4,GL.GL_FLOAT,false,24,fb2)
        GL.glUniformMatrix4fv(uMvp,1,false,mvp,0)
        GL.glDrawArrays(GL.GL_TRIANGLES,0,n)
    }
    private fun compile(vs:String,fs:String):Int{
        fun sh(t:Int,s:String):Int{
            val c=GL.glCreateShader(t)
            GL.glShaderSource(c,s); GL.glCompileShader(c)
            val ok=IntArray(1)
            GL.glGetShaderiv(c,GL.GL_COMPILE_STATUS,ok,0)
            if(ok[0]==0) Log.e("VR","Shader: ${GL.glGetShaderInfoLog(c)}")
            return c
        }
        val p=GL.glCreateProgram()
        GL.glAttachShader(p, sh(GL.GL_VERTEX_SHADER,vs))
        GL.glAttachShader(p, sh(GL.GL_FRAGMENT_SHADER,fs))
        GL.glLinkProgram(p)
        return p
    }
    private fun uploadBg():Int{
        val data=floatArrayOf(
            -1.45f,-1.45f,PLINTH_DARK[0],PLINTH_DARK[1],PLINTH_DARK[2],1f,
             1.45f,-1.45f,PLINTH_DARK[0],PLINTH_DARK[1],PLINTH_DARK[2],1f,
             1.45f,1.45f,PLINTH_DARK[0],PLINTH_DARK[1],PLINTH_DARK[2],1f,
            -1.45f,-1.45f,PLINTH_DARK[0],PLINTH_DARK[1],PLINTH_DARK[2],1f,
             1.45f,1.45f,PLINTH_DARK[0],PLINTH_DARK[1],PLINTH_DARK[2],1f,
            -1.45f,1.45f,PLINTH_DARK[0],PLINTH_DARK[1],PLINTH_DARK[2],1f
        )
        val buf=ByteBuffer.allocateDirect(data.size*4).order(ByteOrder.nativeOrder()).asFloatBuffer()
        buf.put(data).flip()
        val ids=IntArray(1)
        GL.glGenBuffers(1,ids,0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER,ids[0])
        GL.glBufferData(GL.GL_ARRAY_BUFFER,data.size*4,buf,GL.GL_STATIC_DRAW)
        return ids[0]
    }
}
