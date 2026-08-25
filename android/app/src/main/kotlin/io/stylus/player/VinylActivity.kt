package io.stylus.player

import android.content.Context
import android.content.Intent
import android.opengl.GLSurfaceView
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

class VinylActivity : AppCompatActivity() {
    private lateinit var glView: GLSurfaceView
    private lateinit var renderer: VinylRenderer
    private lateinit var deck: Deck

    companion object {
        fun viewIntent(ctx: Context) = Intent(ctx, VinylActivity::class.java).apply { putExtra("mode","view") }
        fun ceremonyIntent(ctx: Context, folder: String) = Intent(ctx, VinylActivity::class.java).apply {
            putExtra("mode","ceremony"); putExtra("folder", folder)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val mode = intent.getStringExtra("mode") ?: "view"
        glView = GLSurfaceView(this).apply { setEGLContextClientVersion(3) }
        renderer = VinylRenderer()
        glView.setRenderer(renderer)
        setContentView(glView)
        deck = Deck()
        if (mode == "view") { deck.phase = Phase.PLAY; deck.speed = VinylConst.REV_PER_SEC }
        // Library + BitPerfectPlayer wired here; deck controls play via onNeedleDrop/Lift
    }

    override fun onPause() { super.onPause(); glView.onPause() }
    override fun onResume() { super.onResume(); glView.onResume() }
}
