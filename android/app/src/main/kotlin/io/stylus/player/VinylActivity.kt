package io.stylus.player

import android.content.Context
import android.content.Intent
import android.opengl.GLSurfaceView
import android.os.Bundle
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import androidx.appcompat.app.AppCompatActivity

/**
 * Tela do vinil — GLSurfaceView fullscreen com o turntable.
 * Modos: "ceremony" (SPINUP→CUE→DROP→PLAY com audio) e "view" (já está tocando, só observa).
 * Toque = pausar/tocar.
 */
class VinylActivity : AppCompatActivity() {

    companion object {
        fun viewIntent(ctx: Context) =
            Intent(ctx, VinylActivity::class.java).apply { putExtra("mode", "view") }

        fun ceremonyIntent(ctx: Context, albumId: Long) =
            Intent(ctx, VinylActivity::class.java).apply {
                putExtra("mode", "ceremony")
                putExtra("albumId", albumId)
            }
    }

    private lateinit var glView: GLSurfaceView
    private lateinit var renderer: VinylRenderer
    private lateinit var deck: Deck
    private var player: BitPerfectPlayer? = null

    private var playing = true
    private var lastTime = 0f
    private var trackDuration = 0L
    private var startedAt = 0L

    private val frameCallback = object : Runnable {
        override fun run() {
            val now = System.nanoTime() / 1e9f
            val dt = if (lastTime == 0f) 0.016f else (now - lastTime).coerceIn(0.001f, 0.05f)
            lastTime = now

            val phase = deck.update(dt, now, playing)

            // Needle sync with player
            when (phase) {
                Phase.PLAY -> player?.play()
                Phase.LIFT, Phase.BREAK, Phase.RETURN -> player?.pause()
                else -> {}
            }

            renderer.deckRotation = deck.rotation
            renderer.armLift = deck.armLift(now)

            // Progress (if playing)
            if (playing && player != null) {
                val dur = player!!.duration
                if (dur > 0) {
                    renderer.playProgress = (player!!.currentPosition.toFloat() / dur).coerceIn(0f, 1f)
                }
            } else if (playing && trackDuration > 0) {
                val elapsed = System.currentTimeMillis() - startedAt
                renderer.playProgress = (elapsed.toFloat() / trackDuration).coerceIn(0f, 1f)
            }

            glView.requestRender()
            glView.postOnAnimation(this)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Fullscreen immersive
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_FULLSCREEN or
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        )

        deck = Deck()
        renderer = VinylRenderer()

        glView = GLSurfaceView(this).apply {
            setEGLContextClientVersion(3)
            setRenderer(renderer)
            renderMode = GLSurfaceView.RENDERMODE_CONTINUOUSLY
        }
        // Overlay: cover + track info on top of GL
        val root = android.widget.FrameLayout(this)
        root.addView(glView, android.widget.FrameLayout.LayoutParams(
            android.view.ViewGroup.LayoutParams.MATCH_PARENT,
            android.view.ViewGroup.LayoutParams.MATCH_PARENT))

        val coverAlbumId = intent.getLongExtra("albumId", -1)
        if (coverAlbumId > 0) {
            try {
                val album = Library.albums(this).find { it.id == coverAlbumId }
                if (album != null) {
                    val titleView = android.widget.TextView(this).apply {
                        text = "${album.artist} — ${album.name}"
                        setTextColor(0xFFE8ECF5.toInt())
                        textSize = 13f
                        setPadding(24, 24, 24, 8)
                        gravity = android.view.Gravity.CENTER
                        setShadowLayer(8f, 0f, 2f, 0xAA000000.toInt())
                    }
                    root.addView(titleView, android.widget.FrameLayout.LayoutParams(
                        android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                        android.view.ViewGroup.LayoutParams.WRAP_CONTENT,
                        android.view.Gravity.TOP or android.view.Gravity.CENTER_HORIZONTAL))
                }
            } catch (_: Exception) {}
        }
        // hint
        val hint = android.widget.TextView(this).apply {
            text = "toque para pausar • dois toques para voltar"
            setTextColor(0xFF8892B0.toInt())
            textSize = 10f
            gravity = android.view.Gravity.CENTER
            alpha = 0.7f
            setPadding(0,0,0,32)
        }
        root.addView(hint, android.widget.FrameLayout.LayoutParams(
            android.view.ViewGroup.LayoutParams.MATCH_PARENT,
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT,
            android.view.Gravity.BOTTOM or android.view.Gravity.CENTER_HORIZONTAL))
        setContentView(root)

        val mode = intent.getStringExtra("mode") ?: "view"

        if (mode == "view") {
            // Already playing, just show the disc at speed
            deck.go(Phase.PLAY, System.nanoTime() / 1e9f)
            deck.speed = VinylConst.REV_PER_SEC
            renderer.armLift = 0f
            // Get current player state from intent extras if available
            playing = true
        } else {
            // Ceremony: SPINUP → CUE → DROP → play
            deck.go(Phase.SPINUP, System.nanoTime() / 1e9f)
            playing = false  // start paused, audio starts after DROP

            // Load album tracks
            val albumId = intent.getLongExtra("albumId", -1)
            if (albumId > 0) {
                val tracks = Library.albumTracks(this, albumId)
                if (tracks.isNotEmpty()) {
                    player = BitPerfectPlayer(this).apply {
                        prepareAlbum(tracks.map { it.uri })
                        onPlaybackEnd = { finish() }
                    }
                    trackDuration = tracks.sumOf { it.duration }
                    // Delay play until deck reaches PLAY phase
                    startedAt = System.currentTimeMillis() + 2700L  // SPINUP+CUE+DROP
                }
            }
        }

        // Tap to toggle play/pause
        val gesture = GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
            override fun onSingleTapUp(e: MotionEvent): Boolean {
                playing = !playing
                if (!playing) player?.pause() else {
                    if (deck.phase == Phase.PLAY) player?.play()
                }
                return true
            }
            override fun onDoubleTap(e: MotionEvent): Boolean {
                finish()
                return true
            }
        })
        glView.setOnTouchListener { _, ev -> gesture.onTouchEvent(ev); true }
    }

    override fun onResume() {
        super.onResume()
        glView.onResume()
        lastTime = 0f
        glView.postOnAnimation(frameCallback)
    }

    override fun onPause() {
        super.onPause()
        glView.onPause()
        glView.removeCallbacks(frameCallback)
        player?.pause()
    }

    override fun onDestroy() {
        super.onDestroy()
        player?.release()
    }
}
