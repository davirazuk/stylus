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
    private lateinit var coverView: android.widget.ImageView
    private lateinit var deck: Deck
    private var player: BitPerfectPlayer? = null

    private var playing = true
    private var lastTime = 0f
    private var trackDuration = 0L
    private var startedAt = 0L
    private var albumIdField: Long = -1

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
            // cover rotates with disc (screen-space, opposite direction)
            coverView.rotation = Math.toDegrees((-deck.rotation).toDouble()).toFloat()

            // Progress per SIDE (like PC: 22min per side, not per song)
            if (albumIdField > 0) {
                val tracks = Library.albumTracks(this@VinylActivity, albumIdField)
                if (tracks.isNotEmpty()) {
                    val posMs = when {
                        playing && player != null && player!!.duration > 0 -> {
                            val idx = player!!.currentTrackIndex.coerceIn(0, tracks.size-1)
                            val before = tracks.take(idx).sumOf { it.duration }
                            before + player!!.currentPosition
                        }
                        playing && trackDuration > 0 -> {
                            val elapsed = System.currentTimeMillis() - startedAt
                            elapsed.coerceIn(0, trackDuration)
                        }
                        else -> 0L
                    }
                    val sideMaxMs = 22*60*1000L
                    var acc = 0L; var sideStart = 0L; var sideEnd = 0L
                    for (t in tracks) {
                        if (acc + t.duration > sideMaxMs && acc > 0) {
                            if (posMs in sideStart until acc) { sideEnd = acc; break }
                            sideStart = acc
                        }
                        acc += t.duration
                        if (posMs < acc) { sideEnd = acc; break }
                    }
                    if (sideEnd == 0L) sideEnd = acc
                    val span = maxOf(1L, sideEnd - sideStart)
                    renderer.playProgress = ((posMs - sideStart).toFloat() / span).coerceIn(0f, 1f)
                }
            } else if (playing && player != null) {
                val dur = player!!.duration
                if (dur > 0) renderer.playProgress = (player!!.currentPosition.toFloat() / dur).coerceIn(0f, 1f)
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
        albumIdField = intent.getLongExtra("albumId", -1)

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

        // Cover art — label is 0.329 radius, disc is 1.0, so label is 32.9% of disc
        val discPx = minOf(resources.displayMetrics.widthPixels, resources.displayMetrics.heightPixels) * 0.78f
        val coverSize = (discPx * 0.329f).toInt()
        coverView = android.widget.ImageView(this).apply {
            layoutParams = android.widget.FrameLayout.LayoutParams(coverSize, coverSize, android.view.Gravity.CENTER)
            alpha = 0.0f
            clipToOutline = true
            outlineProvider = object : android.view.ViewOutlineProvider() {
                override fun getOutline(view: android.view.View, outline: android.graphics.Outline) {
                    outline.setOval(0, 0, view.width, view.height)
                }
            }
            elevation = 6f
        }
        root.addView(coverView)
        // load cover art if available
        if (albumIdField > 0) {
            try {
                val a = Library.albums(this).find { it.id == albumIdField }
                if (a != null) {
                    contentResolver.openInputStream(a.coverUri())?.use { stream ->
                        val bmp = android.graphics.BitmapFactory.decodeStream(stream)
                        if (bmp != null) {
                            val circ = android.graphics.Bitmap.createBitmap(bmp.width, bmp.height, android.graphics.Bitmap.Config.ARGB_8888)
                            val canvas = android.graphics.Canvas(circ)
                            val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
                            val rect = android.graphics.Rect(0,0,bmp.width,bmp.height)
                            val path = android.graphics.Path().apply { addCircle(bmp.width/2f, bmp.height/2f, minOf(bmp.width,bmp.height)/2f, android.graphics.Path.Direction.CW) }
                            canvas.clipPath(path)
                            canvas.drawBitmap(bmp, rect, rect, paint)
                            val holePaint = android.graphics.Paint().apply { color = android.graphics.Color.TRANSPARENT; xfermode = android.graphics.PorterDuffXfermode(android.graphics.PorterDuff.Mode.CLEAR) }
                            canvas.drawCircle(bmp.width/2f, bmp.height/2f, bmp.width*0.038f, holePaint)
                            coverView.setImageBitmap(circ)
                            coverView.alpha = 1f
                        }
                    }
                }
            } catch (_: Exception) {}
        }

        if (albumIdField > 0) {
            try {
                val album = Library.albums(this).find { it.id == albumIdField }
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
        // hint + progress bar
        val bottomCol = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            gravity = android.view.Gravity.CENTER
            setPadding(0,0,0,24)
        }
        val hint = android.widget.TextView(this).apply {
            text = "toque para pausar • dois toques para voltar"
            setTextColor(0xFF8892B0.toInt())
            textSize = 10f
            gravity = android.view.Gravity.CENTER
            alpha = 0.7f
        }
        bottomCol.addView(hint)
        // track progress
        val progress = android.widget.ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progress = 0
            layoutParams = android.widget.LinearLayout.LayoutParams(
                dp(220), dp(3)
            ).apply { topMargin = dp(8) }
        }
        bottomCol.addView(progress)
        root.addView(bottomCol, android.widget.FrameLayout.LayoutParams(
            android.view.ViewGroup.LayoutParams.MATCH_PARENT,
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT,
            android.view.Gravity.BOTTOM or android.view.Gravity.CENTER_HORIZONTAL))

        // lyric view — centered, max width 80% so not cut off
        val lyricView = android.widget.TextView(this).apply {
            setTextColor(0xFFE8ECF5.toInt())
            textSize = 14f
            gravity = android.view.Gravity.CENTER
            setPadding(dp(32), dp(12), dp(32), dp(12))
            setShadowLayer(8f, 0f, 2f, 0xCC000000.toInt())
            alpha = 0f
            maxLines = 2
            ellipsize = android.text.TextUtils.TruncateAt.END
        }
        root.addView(lyricView, android.widget.FrameLayout.LayoutParams(
            (resources.displayMetrics.widthPixels * 0.85f).toInt(),
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT,
            android.view.Gravity.CENTER
        ))

        // update progress periodically
        val progressUpdater = object : Runnable {
            override fun run() {
                val p = player
                if (p != null && p.duration > 0) {
                    progress.progress = ((p.currentPosition.toFloat() / p.duration) * 100).toInt()
                    // lyrics
                    val idx = p.currentTrackIndex
                    val tracks = if (albumIdField > 0) Library.albumTracks(this@VinylActivity, albumIdField) else emptyList()
                    if (idx in tracks.indices) {
                        val lys = Library.lyricsFor(tracks[idx].uri, this@VinylActivity)
                        val line = if (lys != null) Library.lyricAt(lys, p.currentPosition) else null
                        if (line != null) { lyricView.text = line; lyricView.alpha = 1f } else lyricView.alpha = 0f
                    }
                } else {
                    progress.progress = (renderer.playProgress * 100).toInt()
                }
                root.postDelayed(this, 500)
            }
        }
        root.post(progressUpdater)
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
            if (albumIdField > 0) {
                val tracks = Library.albumTracks(this, albumIdField)
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

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

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
