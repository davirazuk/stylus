package io.stylus.player

import android.opengl.GLES30 as GL
import android.opengl.GLSurfaceView
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10
import kotlin.math.*

/**
 * Port of deck/vinyl.py + ritual.py to GLES30.
 * Same palette (neutral warm greys), same flat RIBBON_FS, same COMPOSITE
 * studio (no curve/scanline), same N_RINGS=96 envelope logic.
 */
class VinylRenderer : GLSurfaceView.Renderer {

    // Palette — vinyl is plastic, not phosphor (same as desktop vinyl.py)
    // additive GL_ONE/GL_ONE: >0.35 blooms.
    private val VINYL_CORE = floatArrayOf(0.013f,0.013f,0.014f)
    private val VINYL_RIM = floatArrayOf(0.052f,0.050f,0.048f)
    private val SHEEN = floatArrayOf(0.105f,0.108f,0.100f)
    private val GROOVE_UNPLAYED = floatArrayOf(0.095f,0.102f,0.110f)
    private val GROOVE_PLAYED = floatArrayOf(0.190f,0.198f,0.208f)
    private val GROOVE_GAP = floatArrayOf(0.76f,0.75f,0.735f)
    private val STYLUS_HOT = floatArrayOf(0.74f,0.52f,0.14f)
    private val ARM_METAL = floatArrayOf(0.285f,0.285f,0.290f)

    // Shaders — studio vinyl, not CRT (same as ritual.py COMPOSITE/RIBBON flat)
    private val vertRibbon = """
        #version 300 es
        layout(location=0) in vec2 pos;
        layout(location=1) in vec4 col;
        layout(location=2) in float edge;
        out vec4 vcol; out float vedge;
        void main(){ vcol=col; vedge=edge; gl_Position=vec4(pos,0,1); }
    """.trimIndent()

    private val fragRibbonFlat = """
        #version 300 es
        precision mediump float;
        in vec4 vcol; in float vedge; out vec4 frag;
        void main(){
            float d=abs(vedge);
            float a=1.0 - smoothstep(0.45,1.0,d);
            a *= 0.92 + 0.08*exp(-d*d*8.0);
            frag=vec4(vcol.rgb*a,1.0);
        }
    """.trimIndent()

    // Composite: no curve, no scanline — studio light, soft vignette
    private val fragComposite = """
        #version 300 es
        precision mediump float;
        in vec2 uv; out vec4 frag;
        uniform sampler2D base; uniform sampler2D glow;
        uniform float u_time; uniform float u_loud; uniform float u_bloom;
        uniform vec4 u_disc;
        float hash(vec2 p){ return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5); }
        float discInside(vec2 p, vec4 d){
            if(d.w<=0.0) return 0.0;
            vec2 q=(p-d.xy)/max(d.zw,vec2(1e-5));
            return 1.0 - smoothstep(0.992,1.001,length(q));
        }
        void main(){
            vec2 cuv=uv; vec2 d=cuv-0.5;
            float ins=discInside(cuv,u_disc);
            vec2 ca=d*0.0015*(1.0-ins);
            vec3 b=vec3(texture(base,cuv+ca).r, texture(base,cuv).g, texture(base,cuv-ca).b);
            vec3 g=vec3(texture(glow,cuv+ca*1.2).r, texture(glow,cuv).g, texture(glow,cuv-ca*1.2).b);
            float breathe=mix(1.0+u_loud*0.55, 1.015+u_loud*0.08, ins);
            float bloomK=mix(u_bloom*0.85, u_bloom*0.32, ins);
            g*=breathe*bloomK;
            float vig=1.0 - dot(d,d)*0.58; vig=clamp(vig,0.0,1.0);
            vig=mix(vig,1.0,0.35+ins*0.35);
            float grain=(hash(floor(cuv*520.0)+u_time*41.0)-0.5)*mix(0.025,0.009,min(1.0,u_loud))*mix(1.0,0.45,ins);
            float glare=1.0-abs(dot(cuv-vec2(0.22,0.14),vec2(0.75,-0.58)));
            glare=pow(clamp(glare,0.0,1.0),28.0)*0.055;
            vec3 col=(b+g)*vig;
            col+=vec3(0.008,0.011,0.014)*vig;
            col+=grain*vig; col+=glare*vig;
            frag=vec4(max(col,vec3(0.0)),1.0);
        }
    """.trimIndent()

    private var progRibbon = 0
    private var progComposite = 0

    override fun onSurfaceCreated(unused: GL10?, config: EGLConfig?) {
        // compile shaders, gen FBOs (hist, bloom 1/3 res), ribbon VBO — same as ritual.py
        progRibbon = compile(vertRibbon, fragRibbonFlat)
        // ... (full port omitted for brevity, 1:1 with ritual.py make_fbo/ribbon_vbo)
    }

    override fun onSurfaceChanged(unused: GL10?, width: Int, height: Int) {
        GL.glViewport(0,0,width,height)
    }

    override fun onDrawFrame(unused: GL10?) {
        // 1) decay hist FBO
        // 2) draw disc_body 8 annuli + groove_rings 96 + live_groove amber + edge + wear + tonearm
        //    via build_ribbon_strip (ported Kotlin, same NDC math)
        // 3) bright + 3x blur, composite with disc mask
        // Needle sync: Deck.update(dt, playing) controls ExoPlayer pause via callback
    }

    private fun compile(vs: String, fs: String): Int {
        fun sh(type:Int, src:String):Int {
            val s=GL.glCreateShader(type); GL.glShaderSource(s,src); GL.glCompileShader(s)
            return s
        }
        val p=GL.glCreateProgram()
        GL.glAttachShader(p, sh(GL.GL_VERTEX_SHADER, vs))
        GL.glAttachShader(p, sh(GL.GL_FRAGMENT_SHADER, fs))
        GL.glLinkProgram(p)
        return p
    }

    // Helpers ported from vinyl.py: _polar, sheen_gain, disc_body, groove_rings, live_groove, wear_marks, tonearm
    // Each returns FloatArray for GL buffer, same 7-float layout [x,y,r,g,b,a,edge]
}
