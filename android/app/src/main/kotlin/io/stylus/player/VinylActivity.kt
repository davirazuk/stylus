package io.stylus.player

import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.opengl.GLSurfaceView
import android.os.Bundle
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import kotlin.math.min

/**
 * Tela do vinil — GLSurfaceView fullscreen com o turntable.
 * Toque = pausar/tocar. Swipe esquerda/direita = prev/next.
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

        // Static state for Now Playing bar in MainActivity
        var nowPlayingTitle = ""; private set
        var nowPlayingArtist = ""; private set
        var nowPlayingAlbumId = -1L; private set
        var nowPlayingActive = false; private set

        fun updateNowPlaying(title: String, artist: String, albumId: Long) {
            nowPlayingTitle = title; nowPlayingArtist = artist; nowPlayingAlbumId = albumId; nowPlayingActive = true
        }
        fun clearNowPlaying() { nowPlayingActive = false }
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
    private var lastTracks: List<Library.Track> = emptyList()
    private var isLandscape = false
    private var sleepTimerEnd = 0L
    private var pendingDrop = false
    private var dropAt = 0f  // nanoTime/1e9f when arm should drop
    private var cachedTracks: List<Library.Track>? = null
    private var cachedAlbumId: Long = -1
    private var lastCoverW = 0; private var lastCoverH = 0
    private var lastLyricIdx = -1

    // UI refs
    private var titleView: TextView? = null
    private var trackInfoView: TextView? = null
    private var timeView: TextView? = null
    private var bottomBar: LinearLayout? = null
    private var progressBar: ProgressBar? = null
    private var seekBarRef: android.widget.SeekBar? = null
    private var lyricPanel: android.widget.ScrollView? = null
    private var lyricInner: LinearLayout? = null
    private var prevBtn: TextView? = null
    private var nextBtn: TextView? = null
    private var mediaReceiver: android.content.BroadcastReceiver? = null
    private var scrubTrack: android.media.AudioTrack? = null

    /** Synthesize a short vinyl scrub/scratch sound */
    private fun playScrubSound() {
        try {
            val sr = 22050
            val dur = 80  // ms
            val samples = sr * dur / 1000
            val buf = ShortArray(samples)
            val now = System.nanoTime()
            for (i in 0 until samples) {
                val t = i.toFloat() / sr
                // Filtered noise + crackle-like transients
                val noise = (Math.random() * 2.0 - 1.0).toFloat()
                val freq = 200f + 1200f * Math.sin((now + i * 47000.0).toDouble() / sr).toFloat()
                val tone = Math.sin(2.0 * Math.PI * freq * t).toFloat() * 0.3f
                // Envelope: sharp attack, fast decay
                val env = (1.0f - t * sr / samples.toFloat()).coerceIn(0f, 1f)
                val mix = (noise * 0.5f + tone) * env * 0.6f
                buf[i] = (mix * Short.MAX_VALUE).toInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
            }
            scrubTrack?.release()
            scrubTrack = android.media.AudioTrack.Builder()
                .setAudioAttributes(android.media.AudioAttributes.Builder()
                    .setUsage(android.media.AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                    .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build())
                .setAudioFormat(android.media.AudioFormat.Builder()
                    .setSampleRate(sr)
                    .setEncoding(android.media.AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(android.media.AudioFormat.CHANNEL_OUT_MONO)
                    .build())
                .setBufferSizeInBytes(samples * 2)
                .setTransferMode(android.media.AudioTrack.MODE_STATIC)
                .build()
            scrubTrack?.write(buf, 0, samples)
            scrubTrack?.setVolume(0.25f)
            scrubTrack?.play()
        } catch (_: Exception) {}
    }

    private val frameCallback = object : Runnable {
        override fun run() {
            val now = System.nanoTime() / 1e9f
            val dt = if (lastTime == 0f) 0.016f else (now - lastTime).coerceIn(0.001f, 0.05f)
            lastTime = now

            val phase = deck.update(dt, now, playing)

            // After a skip: arm lifted → hold at top → then drop
            if (pendingDrop && now >= dropAt) {
                pendingDrop = false
                if (playing) {
                    deck.go(Phase.DROP, now)
                } else {
                    deck.go(Phase.CUE, now)
                }
            }

            when (phase) {
                Phase.PLAY -> player?.play()
                Phase.LIFT, Phase.BREAK, Phase.RETURN -> player?.pause()
                else -> {}
            }

            renderer.deckRotation = deck.rotation
            renderer.armLift = deck.armLift(now)
            renderer.armSwing = deck.armSwing(now)
            renderer.crackle = deck.crackle
            renderer.audioLevel = deck.crackle
            coverView.rotation = Math.toDegrees(deck.rotation.toDouble()).toFloat()

            // Landscape detection
            val dm = resources.displayMetrics
            val newLandscape = dm.widthPixels > dm.heightPixels
            if (newLandscape != isLandscape) {
                isLandscape = newLandscape
                renderer.discCx = if (isLandscape) -0.32f else 0f
                renderer.discCy = 0f
                repositionBottomBar()
                repositionTitle()
                repositionCover()
            }
            // Reposition cover only when viewport changes (not every frame)
            val vw = renderer.viewW; val vh = renderer.viewH
            if (vw != lastCoverW || vh != lastCoverH) {
                lastCoverW = vw; lastCoverH = vh
                repositionCover()
            }

            // Progress per SIDE
            if (albumIdField > 0) {
                if (cachedAlbumId != albumIdField) {
                    cachedAlbumId = albumIdField
                    cachedTracks = Library.albumTracks(this@VinylActivity, albumIdField)
                }
                val tracks = cachedTracks
                if (tracks != null && tracks.isNotEmpty()) {
                    lastTracks = tracks
                    val posMs = when {
                        playing && player != null && player!!.duration > 0 -> {
                            val idx = player!!.currentTrackIndex.coerceIn(0, tracks.size - 1)
                            var before = 0L; for (i in 0 until idx) before += tracks[i].duration
                            before + player!!.currentPosition
                        }
                        playing && trackDuration > 0 -> {
                            val elapsed = System.currentTimeMillis() - startedAt
                            elapsed.coerceIn(0, trackDuration)
                        }
                        else -> 0L
                    }
                    val sideMaxMs = 22 * 60 * 1000L
                    val sides = mutableListOf<Pair<Long, Long>>()
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
                        var tot = 0L; for (tt in tracks) tot += tt.duration
                        sides.add(0L to maxOf(1L, tot))
                    }
                    var sideStart = sides[0].first; var sideEnd = sides[0].second
                    for ((s, e) in sides) {
                        if (posMs in s until e) { sideStart = s; sideEnd = e; break }
                        if (posMs >= e) { sideStart = s; sideEnd = e }
                    }
                    val span = maxOf(1L, sideEnd - sideStart)
                    renderer.playProgress = ((posMs - sideStart).toFloat() / span).coerceIn(0f, 1f)
                    val gaps = mutableListOf<Float>()
                    var accum = 0L
                    for (t in tracks) {
                        accum += t.duration
                        if (accum > sideStart && accum < sideEnd) {
                            gaps.add(((accum - sideStart).toFloat() / span).coerceIn(0.01f, 0.99f))
                        }
                    }
                    renderer.gapFracs = gaps.toFloatArray()
                }
            } else if (playing && player != null) {
                val dur = player!!.duration
                if (dur > 0) renderer.playProgress = (player!!.currentPosition.toFloat() / dur).coerceIn(0f, 1f)
                renderer.gapFracs = null
            }

            glView.requestRender()
            glView.postOnAnimation(this)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_FULLSCREEN or
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            )

        deck = Deck()
        renderer = VinylRenderer()
        albumIdField = intent.getLongExtra("albumId", -1)
        renderer.wearSeed = albumIdField.toInt()

        val timerMs = getSharedPreferences("stylus", MODE_PRIVATE).getLong("sleep_timer", 0)
        if (timerMs > 0) sleepTimerEnd = System.currentTimeMillis() + timerMs

        glView = GLSurfaceView(this).apply {
            setEGLContextClientVersion(3)
            setRenderer(renderer)
            renderMode = GLSurfaceView.RENDERMODE_CONTINUOUSLY
        }

        val root = FrameLayout(this)
        root.addView(glView, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT))

        // ── Cover art ──
        val dm = resources.displayMetrics
        val discDiamPx = 0.84f * minOf(dm.widthPixels, dm.heightPixels)
        val coverPx = (discDiamPx * 0.329f).toInt()
        coverView = android.widget.ImageView(this).apply {
            layoutParams = FrameLayout.LayoutParams(coverPx, coverPx).apply {
                gravity = android.view.Gravity.CENTER
            }
            alpha = 0.0f
            clipToOutline = true
            outlineProvider = object : android.view.ViewOutlineProvider() {
                override fun getOutline(view: View, outline: android.graphics.Outline) {
                    outline.setOval(0, 0, view.width, view.height)
                }
            }
            elevation = 6f
        }
        root.addView(coverView)

        // Position cover after layout is measured (handles initial placement + orientation changes)
        root.viewTreeObserver.addOnGlobalLayoutListener(object : android.view.ViewTreeObserver.OnGlobalLayoutListener {
            override fun onGlobalLayout() {
                root.viewTreeObserver.removeOnGlobalLayoutListener(this)
                repositionCover()
            }
        })

        if (albumIdField > 0) {
            try {
                val a = Library.albums(this).find { it.id == albumIdField }
                if (a != null) {
                    contentResolver.openInputStream(a.coverUri())?.use { stream ->
                        val bmp = BitmapFactory.decodeStream(stream)
                        if (bmp != null) {
                            coverView.setImageBitmap(createCircularCover(bmp))
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
                    // Title
                    titleView = TextView(this).apply {
                        text = "${album.artist} — ${album.name}"
                        setTextColor(0xFFE8ECF5.toInt())
                        textSize = 13f
                        setPadding(24, 24, 24, 8)
                        gravity = android.view.Gravity.CENTER
                        setShadowLayer(8f, 0f, 2f, 0xAA000000.toInt())
                    }
                    root.addView(titleView, FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        android.view.Gravity.TOP or android.view.Gravity.CENTER_HORIZONTAL))

                    // Track info
                    trackInfoView = TextView(this).apply {
                        setTextColor(0xFF8892B0.toInt())
                        textSize = 11f
                        gravity = android.view.Gravity.CENTER
                        setPadding(24, 0, 24, 4)
                        setShadowLayer(6f, 0f, 1f, 0xAA000000.toInt())
                    }
                    root.addView(trackInfoView, FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        android.view.Gravity.TOP or android.view.Gravity.CENTER_HORIZONTAL).apply {
                        topMargin = dp(52)
                    })

                    // Cast button — top right
                    val castBtn = TextView(this).apply {
                        text = "\u25C7"
                        setTextColor(0xFF5A6888.toInt())
                        textSize = 18f
                        setPadding(dp(16), dp(20), dp(16), dp(8))
                        setOnClickListener { showCastDialog() }
                    }
                    root.addView(castBtn, FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        android.view.Gravity.TOP or android.view.Gravity.END))
                }
            } catch (_: Exception) {}
        }

        // ── Bottom: time + controls + hint + progress ──
        timeView = TextView(this).apply {
            setTextColor(0xFF6B7394.toInt())
            textSize = 11f
            gravity = android.view.Gravity.CENTER
            setPadding(0, 0, 0, 4)
            setShadowLayer(4f, 0f, 1f, 0xAA000000.toInt())
        }

        val controlsRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER
            setPadding(0, 0, 0, 0)
        }
        prevBtn = TextView(this).apply {
            text = "\u25C0"
            setTextColor(0xFF6B7394.toInt())
            textSize = 18f
            setPadding(dp(24), dp(8), dp(24), dp(8))
            setOnClickListener { skipToPrev() }
        }
        controlsRow.addView(prevBtn)
        controlsRow.addView(TextView(this).apply {
            setPadding(dp(16), 0, dp(16), 0)
        })
        nextBtn = TextView(this).apply {
            text = "\u25B6"
            setTextColor(0xFF6B7394.toInt())
            textSize = 18f
            setPadding(dp(24), dp(8), dp(24), dp(8))
            setOnClickListener { skipToNext() }
        }
        controlsRow.addView(nextBtn)

        // Shuffle button
        var shuffleBtnRef: TextView? = null
        val shuffleBtn = TextView(this).apply {
            text = "\u21C4"
            setTextColor(0xFF4A5570.toInt())
            textSize = 14f
            setPadding(dp(16), dp(8), dp(16), dp(8))
            setOnClickListener {
                val p = player ?: return@setOnClickListener
                p.toggleShuffle()
                setTextColor(if (p.shuffleMode) 0xFFE8ECF5.toInt() else 0xFF4A5570.toInt())
            }
            shuffleBtnRef = this
        }
        controlsRow.addView(shuffleBtn)

        // Repeat button
        val repeatBtn = TextView(this).apply {
            text = "\u27F3"
            setTextColor(0xFF4A5570.toInt())
            textSize = 14f
            setPadding(dp(16), dp(8), dp(16), dp(8))
            setOnClickListener {
                val p = player ?: return@setOnClickListener
                p.toggleRepeat()
                text = when (p.repeatMode) {
                    1 -> "\u27F3\u2081"  // repeat one
                    2 -> "\u27F3"        // repeat all
                    else -> "\u27F3"
                }
                setTextColor(if (p.repeatMode != 0) 0xFFE8ECF5.toInt() else 0xFF4A5570.toInt())
            }
        }
        controlsRow.addView(repeatBtn)

        // Sleep timer button
        val sleepBtn = TextView(this).apply {
            text = "\u23F0"
            setTextColor(0xFF6B7394.toInt())
            textSize = 14f
            setPadding(dp(20), dp(8), dp(20), dp(8))
            setOnClickListener {
                val options = arrayOf("Sem timer", "15 min", "30 min", "60 min", "90 min")
                val values = longArrayOf(0, 15*60000, 30*60000, 60*60000, 90*60000)
                androidx.appcompat.app.AlertDialog.Builder(this@VinylActivity)
                    .setTitle("Sleep Timer")
                    .setItems(options) { _, which ->
                        if (values[which] > 0) {
                            sleepTimerEnd = System.currentTimeMillis() + values[which]
                            android.widget.Toast.makeText(this@VinylActivity, options[which], android.widget.Toast.LENGTH_SHORT).show()
                        } else {
                            sleepTimerEnd = 0
                        }
                    }.show()
            }
        }
        controlsRow.addView(sleepBtn)

        // DLNA cast button
        val castBtn = TextView(this).apply {
            text = "\u25C8"
            setTextColor(0xFF4A5570.toInt())
            textSize = 14f
            setPadding(dp(16), dp(8), dp(16), dp(8))
            setOnClickListener { showCastDialog() }
        }
        controlsRow.addView(castBtn)

        val hint = TextView(this).apply {
            text = "toque = pausar | swipe = faixa | duplo toque = playlist"
            setTextColor(0xFF8892B0.toInt())
            textSize = 8f
            gravity = android.view.Gravity.CENTER
            alpha = 0.4f
        }
        progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100; progress = 0
            layoutParams = LinearLayout.LayoutParams(dp(260), dp(3)).apply { topMargin = dp(6) }
            visibility = View.GONE
        }

        // Seekable seekbar — tap or drag to seek
        val seekBar = android.widget.SeekBar(this).apply {
            max = 100; progress = 0
            layoutParams = LinearLayout.LayoutParams(dp(260), dp(16)).apply { topMargin = dp(2) }
            setOnSeekBarChangeListener(object : android.widget.SeekBar.OnSeekBarChangeListener {
                override fun onStartTrackingTouch(sb: android.widget.SeekBar) {}
                override fun onProgressChanged(sb: android.widget.SeekBar, progress: Int, fromUser: Boolean) {
                    if (fromUser) {
                        val p = player ?: return
                        if (p.duration > 0) {
                            val ms = (progress.toLong() * p.duration / 100)
                            p.exo.seekTo(ms)
                        }
                    }
                }
                override fun onStopTrackingTouch(sb: android.widget.SeekBar) {}
            })
        }
        seekBarRef = seekBar

        val bottomCol = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = android.view.Gravity.CENTER
            setPadding(0, 0, 0, dp(16))
        }
        bottomCol.addView(timeView)
        bottomCol.addView(controlsRow)
        bottomCol.addView(hint)
        bottomCol.addView(seekBar)
        root.addView(bottomCol, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
            android.view.Gravity.BOTTOM or android.view.Gravity.CENTER_HORIZONTAL))
        bottomBar = bottomCol

        // Lyrics panel — scrollable, shows current line + context
        lyricPanel = android.widget.ScrollView(this).apply {
            isVerticalScrollBarEnabled = false
            alpha = 0f
            setPadding(dp(16), dp(8), dp(16), dp(8))
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(0xCC0A0C14.toInt())
                cornerRadius = dp(16).toFloat()
            }
        }
        lyricInner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(8), dp(12), dp(8))
            gravity = android.view.Gravity.CENTER_HORIZONTAL
        }
        lyricPanel?.addView(lyricInner)
        root.addView(lyricPanel, FrameLayout.LayoutParams(
            (dm.widthPixels * 0.88f).toInt(),
            dp(160),
            android.view.Gravity.BOTTOM or android.view.Gravity.CENTER_HORIZONTAL).apply {
            bottomMargin = dp(90)
        })

        // Progress updater
        val progressUpdater = object : Runnable {
            override fun run() {
                if (sleepTimerEnd > 0 && System.currentTimeMillis() >= sleepTimerEnd) {
                    sleepTimerEnd = 0; playing = false; player?.pause()
                    if (deck.phase == Phase.PLAY) deck.go(Phase.LIFT, System.nanoTime() / 1e9f)
                    android.widget.Toast.makeText(this@VinylActivity, "Sleep timer", android.widget.Toast.LENGTH_SHORT).show()
                }
                val p = player
                if (p != null && p.duration > 0) {
                    seekBarRef?.progress = ((p.currentPosition.toFloat() / p.duration) * 100).toInt()
                    // Time display
                    val cur = p.currentPosition / 1000
                    val rem = (p.duration - p.currentPosition) / 1000
                    var timeStr = String.format("%d:%02d  \u2014  -%d:%02d", cur / 60, cur % 60, rem / 60, rem % 60)
                    // Sleep timer countdown
                    if (sleepTimerEnd > 0) {
                        val sleepRem = ((sleepTimerEnd - System.currentTimeMillis()) / 1000).toInt().coerceAtLeast(0)
                        timeStr += "  \u2022  Sleep ${sleepRem / 60}:${String.format("%02d", sleepRem % 60)}"
                    }
                    timeView?.text = timeStr
                    // Lyrics + track info
                    val idx = p.currentTrackIndex
                    val tracks = cachedTracks ?: emptyList()
                    if (idx in tracks.indices) {
                        val t = tracks[idx]
                        val lys = Library.lyricsFor(t.uri, this@VinylActivity)
                        if (lys != null && lys.isNotEmpty()) {
                            var curIdx = 0
                            for (i in lys.indices) {
                                if (lys[i].first <= p.currentPosition) curIdx = i
                            }
                            // Only rebuild view when line changes
                            if (curIdx != lastLyricIdx) {
                                lastLyricIdx = curIdx
                                lyricInner?.removeAllViews()
                                val contextBefore = 2
                                val contextAfter = 1
                                val start = (curIdx - contextBefore).coerceAtLeast(0)
                                val end = (curIdx + contextAfter + 1).coerceAtMost(lys.size)
                                for (i in start until end) {
                                    val isCurrent = i == curIdx
                                    val tv = TextView(this@VinylActivity).apply {
                                        text = lys[i].second.ifBlank { "\u00B7" }
                                        textSize = if (isCurrent) 14f else 11f
                                        setTextColor(if (isCurrent) 0xFFF0F4FF.toInt() else 0xFF5A6580.toInt())
                                        gravity = android.view.Gravity.CENTER
                                        setPadding(dp(4), dp(3), dp(4), dp(3))
                                        alpha = if (isCurrent) 1f else 0.5f
                                        if (isCurrent) typeface = android.graphics.Typeface.DEFAULT_BOLD
                                    }
                                    lyricInner?.addView(tv)
                                }
                            }
                            lyricPanel?.alpha = 1f
                        } else {
                            lastLyricIdx = -1
                            lyricPanel?.alpha = 0f
                        }
                        trackInfoView?.text = "${idx + 1}/${tracks.size} \u2022 ${t.title} \u2014 ${t.artist}"
                        trackInfoView?.alpha = 0.8f
                    }
                } else {
                    seekBarRef?.progress = (renderer.playProgress * 100).toInt()
                    timeView?.text = ""
                }
                root.postDelayed(this, 500)
            }
        }
        root.post(progressUpdater)
        setContentView(root)

        val mode = intent.getStringExtra("mode") ?: "view"

        if (mode == "view") {
            // Start with arm at rest, let it swing in naturally
            deck.go(Phase.SPINUP, System.nanoTime() / 1e9f)
            renderer.armSwing = 1f
            renderer.armLift = 1f
            playing = true
        } else {
            deck.go(Phase.SPINUP, System.nanoTime() / 1e9f)
            renderer.armSwing = 1f
            renderer.armLift = 1f
            renderer.playProgress = 0f
            playing = false

            if (albumIdField > 0) {
                val tracks = Library.albumTracks(this, albumIdField)
                if (tracks.isNotEmpty()) {
                    val startIdx = intent.getIntExtra("trackIndex", 0).coerceIn(0, tracks.size - 1)
                    player = BitPerfectPlayer(this).apply {
                        prepareAlbum(tracks.map { it.uri }, startIndex = startIdx)
                        onPlaybackEnd = { finish() }
                        onTrackChange = { idx ->
                            if (idx in tracks.indices) {
                                val t = tracks[idx]
                                setTrackInfo(t.title, t.artist, t.album, t.duration)
                                updateNowPlaying(t.title, t.artist, albumIdField)
                            }
                        }
                    }
                    var tot2 = 0L; for (tt in tracks) tot2 += tt.duration; trackDuration = tot2
                    if (tracks.isNotEmpty()) {
                        player!!.setTrackInfo(tracks[0].title, tracks[0].artist, tracks[0].album, tracks[0].duration)
                    }
                    try {
                        val svcIntent = Intent(this, BitPerfectService::class.java)
                        startForegroundService(svcIntent)
                        player!!.onMetadataChanged = { token, title, artist, album, playing ->
                            runOnUiThread {
                                val artUri = if (albumIdField > 0)
                                    android.net.Uri.parse("content://media/external/audio/albumart/$albumIdField") else null
                                BitPerfectService.instance?.showNotification(token, title, artist, album, playing, artUri)
                            }
                        }
                    } catch (_: Exception) {}
                    player?.pause()
                }
            }
        }

        // Gestures: tap = toggle controls + play/pause, swipe = prev/next, long press = back
        var controlsVisible = true
        val gestureDetector = GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
            override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
                togglePlayPause()
                return true
            }
            override fun onLongPress(e: MotionEvent) { finish() }
            override fun onDoubleTap(e: MotionEvent): Boolean {
                // Double tap toggles controls visibility
                controlsVisible = !controlsVisible
                val alpha = if (controlsVisible) 1f else 0f
                bottomBar?.animate()?.alpha(alpha)?.setDuration(200)?.start()
                titleView?.animate()?.alpha(alpha)?.setDuration(200)?.start()
                trackInfoView?.animate()?.alpha(alpha)?.setDuration(200)?.start()
                return true
            }
            override fun onFling(e1: MotionEvent?, e2: MotionEvent, vx: Float, vy: Float): Boolean {
                if (e1 == null) return false
                val dx = e2.x - e1.x
                val dy = e2.y - e1.y
                if (Math.abs(dx) > 100 && Math.abs(dx) > Math.abs(dy)) {
                    if (dx > 0) skipToPrev() else skipToNext()
                    return true
                }
                // Vertical swipe
                if (Math.abs(dy) > 120 && Math.abs(dy) > Math.abs(dx)) {
                    // Swipe down = exit to library
                    if (dy > 0 && e1.y < resources.displayMetrics.heightPixels * 0.3f) {
                        playing = false; player?.pause()
                        if (deck.phase == Phase.PLAY) deck.go(Phase.LIFT, System.nanoTime() / 1e9f)
                        VinylActivity.clearNowPlaying()
                        finish()
                        return true
                    }
                    // Right half of screen = volume control
                    if (e1.x > resources.displayMetrics.widthPixels * 0.6f) {
                        val am = getSystemService(Context.AUDIO_SERVICE) as android.media.AudioManager
                        val maxVol = am.getStreamMaxVolume(android.media.AudioManager.STREAM_MUSIC)
                        val curVol = am.getStreamVolume(android.media.AudioManager.STREAM_MUSIC)
                        val delta = if (dy < 0) 1 else -1
                        am.setStreamVolume(android.media.AudioManager.STREAM_MUSIC,
                            (curVol + delta).coerceIn(0, maxVol), 0)
                        return true
                    }
                    // Left half = seek
                    val p = player
                    if (p != null && p.duration > 0) {
                        val seekMs = if (dy < 0) (p.currentPosition + 10000).coerceAtMost(p.duration)
                        else (p.currentPosition - 10000).coerceAtLeast(0)
                        p.exo.seekTo(seekMs)
                        playScrubSound()
                    }
                    return true
                }
                return false
            }
        })

        root.setOnTouchListener { _, ev ->
            gestureDetector.onTouchEvent(ev)
            true
        }

        // Notification action receivers + volume control
        val audioManager = getSystemService(Context.AUDIO_SERVICE) as android.media.AudioManager
        val maxVol = audioManager.getStreamMaxVolume(android.media.AudioManager.STREAM_MUSIC)
        mediaReceiver = object : android.content.BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                when (intent.action) {
                    "io.stylus.player.MEDIA_PREV" -> skipToPrev()
                    "io.stylus.player.MEDIA_NEXT" -> skipToNext()
                    "io.stylus.player.MEDIA_TOGGLE" -> togglePlayPause()
                    "io.stylus.player.TOGGLE_PLAY" -> togglePlayPause()
                    "io.stylus.player.MEDIA_STOP" -> {
                        playing = false; player?.pause()
                        if (deck.phase == Phase.PLAY) deck.go(Phase.LIFT, System.nanoTime() / 1e9f)
                        VinylActivity.clearNowPlaying()
                        finish()
                    }
                }
            }
        }
        val filter = android.content.IntentFilter().apply {
            addAction("io.stylus.player.MEDIA_PREV")
            addAction("io.stylus.player.MEDIA_NEXT")
            addAction("io.stylus.player.MEDIA_TOGGLE")
            addAction("io.stylus.player.TOGGLE_PLAY")
            addAction("io.stylus.player.MEDIA_STOP")
        }
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            registerReceiver(mediaReceiver, filter, android.content.Context.RECEIVER_EXPORTED)
        } else {
            registerReceiver(mediaReceiver, filter)
        }
    }

    private fun togglePlayPause() {
        playing = !playing
        if (!playing) {
            player?.pause()
            if (deck.phase == Phase.PLAY) deck.go(Phase.LIFT, System.nanoTime() / 1e9f)
        } else {
            if (deck.phase == Phase.LIFT || deck.phase == Phase.BREAK) {
                deck.go(Phase.CUE, System.nanoTime() / 1e9f)
            } else {
                player?.play()
                if (deck.phase == Phase.SPINUP || deck.phase == Phase.CUE) {
                    deck.go(Phase.DROP, System.nanoTime() / 1e9f)
                }
            }
        }
    }

    private fun skipToNext() {
        val p = player ?: return
        if (p.currentTrackIndex < p.trackCount - 1) {
            playScrubSound()
            p.skipToNext()
            if (deck.phase == Phase.PLAY || deck.phase == Phase.DROP) {
                val now = System.nanoTime() / 1e9f
                deck.go(Phase.LIFT, now)
                pendingDrop = true
                // Wait for full lift (1.0s) + brief pause (0.4s) before dropping
                dropAt = now + VinylConst.LIFT_T + 0.4f
            }
        }
    }

    private fun skipToPrev() {
        val p = player ?: return
        if (p.currentTrackIndex > 0) {
            playScrubSound()
            p.skipToPrev()
            if (deck.phase == Phase.PLAY || deck.phase == Phase.DROP) {
                val now = System.nanoTime() / 1e9f
                deck.go(Phase.LIFT, now)
                pendingDrop = true
                dropAt = now + VinylConst.LIFT_T + 0.4f
            }
        }
    }

    private fun repositionCover() {
        val w = renderer.viewW; val h = renderer.viewH
        val base = 0.84f
        // Disc diameter in pixels = base * min(viewport_w, viewport_h)
        val discDiam = base * minOf(w, h)
        // Label = 32.9% of disc radius → cover diameter = disc * 0.329
        val coverPx = (discDiam * 0.329f).toInt()
        // Disc center in screen pixels from NDC
        val discCenterX = (renderer.discCx + 1f) / 2f * w
        val discCenterY = (1f - renderer.discCy) / 2f * h
        val params = coverView.layoutParams as FrameLayout.LayoutParams
        params.width = coverPx; params.height = coverPx
        params.gravity = android.view.Gravity.TOP or android.view.Gravity.START
        params.leftMargin = (discCenterX - coverPx / 2).toInt()
        params.topMargin = (discCenterY - coverPx / 2).toInt()
        coverView.layoutParams = params
    }

    private fun repositionBottomBar() {
        val bp = bottomBar?.layoutParams as? FrameLayout.LayoutParams ?: return
        val dm = resources.displayMetrics
        if (isLandscape) {
            bp.gravity = android.view.Gravity.BOTTOM or android.view.Gravity.END
            bp.width = (dm.widthPixels * 0.35f).toInt()
        } else {
            bp.gravity = android.view.Gravity.BOTTOM or android.view.Gravity.CENTER_HORIZONTAL
            bp.width = ViewGroup.LayoutParams.MATCH_PARENT
        }
        bottomBar?.layoutParams = bp
    }

    private fun repositionTitle() {
        val dm = resources.displayMetrics
        val tp = titleView?.layoutParams as? FrameLayout.LayoutParams
        val ti = trackInfoView?.layoutParams as? FrameLayout.LayoutParams
        if (isLandscape) {
            // Title on right side, vertically centered
            tp?.let {
                it.gravity = android.view.Gravity.TOP or android.view.Gravity.START
                it.leftMargin = (dm.widthPixels * 0.60f).toInt()
                it.topMargin = (dm.heightPixels * 0.35f).toInt()
                it.width = ViewGroup.LayoutParams.WRAP_CONTENT
                titleView?.layoutParams = it
                titleView?.gravity = android.view.Gravity.START
                titleView?.setPadding(0, 0, 0, 0)
            }
            ti?.let {
                it.gravity = android.view.Gravity.TOP or android.view.Gravity.START
                it.leftMargin = (dm.widthPixels * 0.60f).toInt()
                it.topMargin = (dm.heightPixels * 0.35f + dp(40)).toInt()
                it.width = ViewGroup.LayoutParams.WRAP_CONTENT
                trackInfoView?.layoutParams = it
                trackInfoView?.gravity = android.view.Gravity.START
                trackInfoView?.setPadding(0, 0, 0, 0)
            }
        } else {
            tp?.let {
                it.gravity = android.view.Gravity.TOP or android.view.Gravity.CENTER_HORIZONTAL
                it.leftMargin = 0; it.topMargin = 0
                it.width = ViewGroup.LayoutParams.MATCH_PARENT
                titleView?.layoutParams = it
                titleView?.gravity = android.view.Gravity.CENTER
                titleView?.setPadding(24, 24, 24, 8)
            }
            ti?.let {
                it.gravity = android.view.Gravity.TOP or android.view.Gravity.CENTER_HORIZONTAL
                it.leftMargin = 0; it.topMargin = dp(52)
                it.width = ViewGroup.LayoutParams.MATCH_PARENT
                trackInfoView?.layoutParams = it
                trackInfoView?.gravity = android.view.Gravity.CENTER
                trackInfoView?.setPadding(24, 0, 24, 4)
            }
        }
    }

    private fun showTrackListOverlay() {
        val tracks = cachedTracks ?: return
        if (tracks.isEmpty()) return
        val currentIdx = player?.currentTrackIndex ?: 0

        val root = window.decorView.findViewById<ViewGroup>(android.R.id.content)

        val overlay = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(0xE807080B.toInt())
            setPadding(0, dp(24), 0, 0)
        }

        val header = TextView(this).apply {
            text = "FAIXAS"
            setTextColor(0xFF6A7590.toInt())
            textSize = 10f
            letterSpacing = 0.15f
            setPadding(dp(20), dp(8), dp(20), dp(8))
        }
        overlay.addView(header)

        val list = android.widget.ListView(this)
        list.adapter = object : android.widget.BaseAdapter() {
            override fun getCount() = tracks.size
            override fun getItem(i: Int) = tracks[i]
            override fun getItemId(i: Int) = i.toLong()
            override fun getView(i: Int, convertView: View?, parent: ViewGroup): View {
                val tv = (convertView as? TextView) ?: TextView(this@VinylActivity).apply {
                    setPadding(dp(20), dp(10), dp(20), dp(10))
                    textSize = 12f
                }
                val t = tracks[i]
                tv.text = "${i + 1}. ${t.title}"
                tv.setTextColor(if (i == currentIdx) 0xFFE8ECF5.toInt() else 0xFF8892B0.toInt())
                return tv
            }
        }
        list.setOnItemClickListener { _, _, i, _ ->
            player?.exo?.seekToDefaultPosition(i)
            player?.play()
            root.removeView(overlay)
        }
        list.divider = null
        list.selector = android.graphics.drawable.ColorDrawable(0x20FFFFFF)
        overlay.addView(list, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        val closeBtn = TextView(this).apply {
            text = "FECHAR"
            setTextColor(0xFF4A5570.toInt())
            textSize = 10f
            letterSpacing = 0.1f
            gravity = android.view.Gravity.CENTER
            setPadding(0, dp(12), 0, dp(16))
            setOnClickListener { root.removeView(overlay) }
        }
        overlay.addView(closeBtn)

        root.addView(overlay, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
        ))
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun showCastDialog() {
        val loading = TextView(this).apply {
            text = "Procurando dispositivos DLNA..."
            setTextColor(0xFFE8ECF5.toInt())
            textSize = 14f
            setPadding(dp(24), dp(16), dp(24), dp(16))
        }
        val dialog = androidx.appcompat.app.AlertDialog.Builder(this)
            .setView(loading)
            .setNegativeButton("Cancelar", null)
            .create()
        dialog.show()
        CastManager.discover { devices ->
            runOnUiThread {
                loading.text = if (devices.isEmpty()) "Nenhum dispositivo encontrado" else "Escolha um dispositivo:"
                if (devices.isNotEmpty()) {
                    val names = devices.map { it.name }.toTypedArray()
                    androidx.appcompat.app.AlertDialog.Builder(this)
                        .setTitle("Cast DLNA")
                        .setItems(names) { _, which -> castToDevice(devices[which]) }
                        .setNegativeButton("Cancelar", null)
                        .show()
                }
                dialog.dismiss()
            }
        }
    }

    private fun castToDevice(device: CastManager.DlnaDevice) {
        val p = player ?: return
        val idx = p.currentTrackIndex
        val tracks = if (albumIdField > 0) Library.albumTracks(this, albumIdField) else emptyList()
        if (idx !in tracks.indices) return
        val track = tracks[idx]
        android.widget.Toast.makeText(this, "Casting: ${track.title}", android.widget.Toast.LENGTH_SHORT).show()
        CastManager.castFile(this, track.uri, device) { success ->
            runOnUiThread {
                android.widget.Toast.makeText(this,
                    if (success) "Casting para ${device.name}" else "Falha ao castar",
                    android.widget.Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun createCircularCover(src: android.graphics.Bitmap): android.graphics.Bitmap {
        val size = maxOf(src.width, src.height)
        val out = android.graphics.Bitmap.createBitmap(size, size, android.graphics.Bitmap.Config.ARGB_8888)
        val canvas = android.graphics.Canvas(out)
        val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
        val dstRect = android.graphics.Rect(0, 0, size, size)
        val srcRect = android.graphics.Rect(
            (src.width - size) / 2, (src.height - size) / 2,
            (src.width + size) / 2, (src.height + size) / 2
        )
        val path = android.graphics.Path().apply {
            addCircle(size / 2f, size / 2f, size / 2f, android.graphics.Path.Direction.CW)
        }
        canvas.clipPath(path)
        canvas.drawBitmap(src, srcRect, dstRect, paint)
        val ringPaint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
            style = android.graphics.Paint.Style.STROKE; strokeWidth = size * 0.02f; color = 0x40000000
        }
        canvas.drawCircle(size / 2f, size / 2f, size / 2f - size * 0.01f, ringPaint)
        val holePaint = android.graphics.Paint().apply {
            color = android.graphics.Color.TRANSPARENT
            xfermode = android.graphics.PorterDuffXfermode(android.graphics.PorterDuff.Mode.CLEAR)
        }
        canvas.drawCircle(size / 2f, size / 2f, size * 0.040f, holePaint)
        val holeRing = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
            style = android.graphics.Paint.Style.STROKE; strokeWidth = size * 0.008f; color = 0x60000000
        }
        canvas.drawCircle(size / 2f, size / 2f, size * 0.042f, holeRing)
        return out
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
        clearNowPlaying()
        try { mediaReceiver?.let { unregisterReceiver(it) } } catch (_: Exception) {}
        try { scrubTrack?.release() } catch (_: Exception) {}
        player?.release()
    }
}
