package io.stylus.player

import android.content.Context
import android.content.Intent
import android.opengl.GLSurfaceView
import android.os.Bundle
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import androidx.appcompat.app.AppCompatActivity
import kotlin.math.sqrt
import kotlin.math.min

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
    private var manualNeedleProgress: Float? = null

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
            coverView.rotation = Math.toDegrees((-deck.rotation).toDouble()).toFloat()

            // Manual needle overrides computed progress for a short time after drag
            manualNeedleProgress?.let {
                renderer.playProgress = it
                // clear after 2s once player catches up
                if (playing && player != null && player!!.isPlaying) manualNeedleProgress = null
            } ?: run {
                // Progress per SIDE (like PC: 22min per side, not per song)
                if (albumIdField > 0) {
                    val tracks = Library.albumTracks(this@VinylActivity, albumIdField)
                    if (tracks.isNotEmpty()) {
                        val posMs = when {
                            playing && player != null && player!!.duration > 0 -> {
                                val idx = player!!.currentTrackIndex.coerceIn(0, tracks.size-1)
                                var before=0L; for(i in 0 until idx) before+=tracks[i].duration
                                before + player!!.currentPosition
                            }
                            playing && trackDuration > 0 -> {
                                val elapsed = System.currentTimeMillis() - startedAt
                                elapsed.coerceIn(0, trackDuration)
                            }
                            else -> 0L
                        }
                        val sideMaxMs = 22*60*1000L
                        val sides = mutableListOf<Pair<Long,Long>>()
                        var curStart = 0L; var curDur = 0L
                        for (t in tracks) {
                            if (curDur + t.duration > sideMaxMs && curDur > 0) {
                                sides.add(curStart to curStart + curDur)
                                curStart += curDur; curDur = 0L
                            }
                            curDur += t.duration
                        }
                        if (curDur > 0) sides.add(curStart to curStart + curDur)
                        if (sides.isEmpty()) {
                            var tot=0L; for(tt in tracks) tot+=tt.duration
                            sides.add(0L to maxOf(1L, tot))
                        }
                        var sideStart = sides[0].first; var sideEnd = sides[0].second
                        for ((s,e) in sides) {
                            if (posMs in s until e) { sideStart = s; sideEnd = e; break }
                            if (posMs >= e) { sideStart = s; sideEnd = e }
                        }
                        val span = maxOf(1L, sideEnd - sideStart)
                        renderer.playProgress = ((posMs - sideStart).toFloat() / span).coerceIn(0f, 1f)
                    }
                } else if (playing && player != null) {
                    val dur = player!!.duration
                    if (dur > 0) renderer.playProgress = (player!!.currentPosition.toFloat() / dur).coerceIn(0f, 1f)
                }
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

        // lyric view — bottom, above hint, with dark pill background
        val lyricView = android.widget.TextView(this).apply {
            setTextColor(0xFFF0F4FF.toInt())
            textSize = 13f
            gravity = android.view.Gravity.CENTER
            setPadding(dp(16), dp(10), dp(16), dp(10))
            alpha = 0f
            maxLines = 2
            ellipsize = android.text.TextUtils.TruncateAt.END
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(0xAA0A0C14.toInt())
                cornerRadius = dp(20).toFloat()
            }
        }
        // place lyrics just above bottom hint/progress
        val lyricParams = android.widget.FrameLayout.LayoutParams(
            (resources.displayMetrics.widthPixels * 0.82f).toInt(),
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT,
            android.view.Gravity.BOTTOM or android.view.Gravity.CENTER_HORIZONTAL
        ).apply { bottomMargin = dp(72) }
        root.addView(lyricView, lyricParams)

        // update progress periodically
        val progressUpdater = object : Runnable {
            override fun run() {
                val p = player
                if (p != null && p.duration > 0) {
                    progress.progress = ((p.currentPosition.toFloat() / p.duration) * 100).toInt()
                    // lyrics
                    val idx = p.currentTrackIndex
                    val tracks = if (albumIdField > 0) Library.albumTracks(this@VinylActivity, albumIdField) else emptyList<Library.Track>()
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
            deck.go(Phase.PLAY, System.nanoTime() / 1e9f)
            deck.speed = VinylConst.REV_PER_SEC
            renderer.armLift = 0f
            playing = true
        } else {
            // Manual needle: disc spins at outer edge, arm lifted at rest, wait for user to drag needle
            deck.go(Phase.BREAK, System.nanoTime() / 1e9f)
            deck.speed = VinylConst.REV_PER_SEC
            renderer.armLift = 1f
            renderer.playProgress = 0f
            playing = false

            if (albumIdField > 0) {
                val tracks = Library.albumTracks(this, albumIdField)
                if (tracks.isNotEmpty()) {
                    player = BitPerfectPlayer(this).apply {
                        prepareAlbum(tracks.map { it.uri })
                        onPlaybackEnd = { finish() }
                    }
                    var tot2=0L; for(tt in tracks) tot2+=tt.duration; trackDuration = tot2
                }
            }
        }

        // Manual needle: drag on disc to set progress, tap to play/pause
        var isDragging = false
        glView.setOnTouchListener { _, ev ->
            val w = glView.width.toFloat(); val h = glView.height.toFloat()
            val cx = w/2f; val cy = h/2f
            val dx = ev.x - cx; val dy = ev.y - cy
            val isoX = min(1f, h/w); val isoY = min(1f, w/h)
            val mx = dx / (min(w,h)*0.39f) / isoX
            val my = dy / (min(w,h)*0.39f) / isoY
            val r = sqrt(mx*mx + my*my)
            when (ev.action) {
                MotionEvent.ACTION_DOWN -> {
                    if (r in 0.33f..1.08f) {
                        isDragging = true
                        deck.go(Phase.CUE, System.nanoTime()/1e9f)
                        playing = false
                        player?.pause()
                        val prog = ((0.945f - r) / (0.945f - 0.395f)).coerceIn(0f,1f)
                        renderer.playProgress = prog
                        manualNeedleProgress = prog
                        // also seek player to that side position
                        if (albumIdField > 0) {
                            val tracks = Library.albumTracks(this, albumIdField)
                            if (tracks.isNotEmpty()) {
                                val sideMaxMs = 22*60*1000L
                                val sides = mutableListOf<Pair<Long,Long>>()
                                var cs=0L; var cd=0L
                                for(t in tracks){ if(cd+t.duration>sideMaxMs && cd>0){ sides.add(cs to cs+cd); cs+=cd; cd=0L }; cd+=t.duration }
                                if(cd>0) sides.add(cs to cs+cd)
                                val sideStart=sides[0].first; val sideEnd=sides[0].second
                                val targetMs = sideStart + (prog*(sideEnd-sideStart)).toLong()
                                var acc=0L; var targetIdx=0; var targetPos=0L
                                for((idx,t) in tracks.withIndex()){
                                    if(targetMs in acc until acc+t.duration){ targetIdx=idx; targetPos=targetMs-acc; break }
                                    acc+=t.duration
                                }
                                player?.exo?.seekTo(targetIdx, targetPos)
                            }
                        }
                        true
                    } else false
                }
                MotionEvent.ACTION_MOVE -> {
                    if (isDragging && r in 0.30f..1.10f) {
                        val prog = ((0.945f - r) / (0.945f - 0.395f)).coerceIn(0f,1f)
                        renderer.playProgress = prog
                        manualNeedleProgress = prog
                        glView.requestRender()
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (isDragging) {
                        isDragging = false
                        // drop needle and play
                        deck.go(Phase.DROP, System.nanoTime()/1e9f)
                        // after DROP (0.55s) will go to PLAY and play via frameCallback
                        // we set playing true after drop
                        glView.postDelayed({
                            playing = true
                            player?.play()
                            deck.go(Phase.PLAY, System.nanoTime()/1e9f)
                        }, 600)
                    }
                    true
                }
                else -> false
            }
        }
        // tap disc when playing to pause (lift), when at rest show hint — must drag needle to start
        root.setOnClickListener {
            if (isDragging) return@setOnClickListener
            if (deck.phase == Phase.PLAY) {
                playing = false
                player?.pause()
                deck.go(Phase.LIFT, System.nanoTime()/1e9f)
            } else if (deck.phase == Phase.BREAK || deck.phase == Phase.LIFT) {
                android.widget.Toast.makeText(this, "Arraste a agulha até o sulco para tocar", android.widget.Toast.LENGTH_SHORT).show()
            } else if (!playing) {
                playing = true
                if (deck.phase == Phase.CUE) deck.go(Phase.DROP, System.nanoTime()/1e9f)
            }
        }
        root.setOnLongClickListener { finish(); true }
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
