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
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import kotlin.math.min

/**
 * Tela do vinil — GLSurfaceView fullscreen com o turntable.
 * Toque = pausar/tocar. Swipe esquerda/direita = prev/next.
 */
class VinylActivity : AppCompatActivity() {

    companion object {
        // (Havia um `viewIntent` aqui, para abrir a tela no disco que já
        // toca sem reiniciar. Ninguém o chamava, e ele não funcionaria: o
        // modo "view" não cria tocador nenhum, e o tocador vive na
        // instância anterior desta Activity — a tela abriria girando um
        // disco mudo. O que a barra do "tocando agora" precisa é retomar na
        // FAIXA certa, e é o que o `ceremonyIntent` faz agora.)

        fun ceremonyIntent(ctx: Context, albumId: Long, trackIndex: Int = 0) =
            Intent(ctx, VinylActivity::class.java).apply {
                putExtra("mode", "ceremony")
                putExtra("albumId", albumId)
                putExtra("trackIndex", trackIndex)
            }

        // Static state for Now Playing bar in MainActivity
        var nowPlayingTitle = ""; private set
        var nowPlayingArtist = ""; private set
        var nowPlayingAlbumId = -1L; private set
        var nowPlayingActive = false; private set
        // A FAIXA em que a agulha está. **Sintoma:** tocar na barra do
        // "tocando agora" abria o disco pela faixa 1 — o disco recomeçava.
        // É o mesmo defeito que o lançador do computador já tinha perdido
        // ("abrir não reinicia"), e o `trackIndex` que conserta já era lido
        // do intent desde sempre: ninguém mandava.
        var nowPlayingTrackIndex = 0; private set

        fun updateNowPlaying(title: String, artist: String, albumId: Long,
                             trackIndex: Int = 0) {
            nowPlayingTitle = title; nowPlayingArtist = artist
            nowPlayingAlbumId = albumId; nowPlayingActive = true
            nowPlayingTrackIndex = trackIndex
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
    // A soneca no FIM DO LADO, e o esmaecimento. As mesmas duas coisas do
    // lançador do computador (ver `App._soneca`): lá o corte seco no meio da
    // faixa era o que acordava quem estava quase dormindo, e aqui era igual
    // — um `player?.pause()` no instante em que o relógio batia.
    private var sleepAtSideEnd = false
    private var sleepFadeFrom = 0L
    private var volumeAntes = -1f
    // Quanto falta do lado que está tocando, em ms. -1 = ainda não se sabe.
    private var restaNoLado = -1L
    private var pendingDrop = false
    private var dropAt = 0f  // nanoTime/1e9f when arm should drop
    private var cachedTracks: List<Library.Track>? = null
    private var cachedAlbumId: Long = -1
    // Cache dos LADOS e dos anéis de cada lado. O frame callback rodava
    // 60 vezes por segundo e recalculava tudo a partir das durações,
    // alocando uma lista, percorrendo as faixas e construindo um array de
    // floats — tudo isso para um disco que não muda enquanto toca.
    // **Sintoma:** o desenho da capa (OpenGL) usa os anéis, e este cálculo
    // estava na thread da UI competindo com o render. O frame pulava.
    private var cachedSides: List<Lados.Lado>? = null
    private var cachedGapFracs: Array<FloatArray>? = null
    // Em que LADO a agulha estava na volta passada. -1 = ainda não se sabe:
    // abrir o disco no meio do lado B não é "acabou o lado A".
    private var ladoAtual = -1
    private var lastCoverW = 0; private var lastCoverH = 0
    private var lastLyricIdx = -1
    // A letra JÁ LIDA desta faixa. **Sintoma:** o `lyricsFor` era chamado a
    // cada tique do relógio da tela — uma consulta ao ContentResolver mais a
    // leitura e o parse do .lrc inteiro, várias vezes por segundo, na thread
    // da interface. Numa letra de duzentas linhas isso é I/O e lixo de
    // memória constantes com a tela parada; o computador guarda a dele desde
    // sempre (ver `_lyr_cache`). A chave é a FAIXA: trocou, relê.
    private var lyricCacheKey: Long = -1L
    private var lyricCache: List<Pair<Long, String>>? = null
    private var lastTrackIdx = -1
    private var volumeOverlay: TextView? = null
    private var volumeHandler: android.os.Handler? = null

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
    private var playPauseBtn: TextView? = null
    private var mediaReceiver: android.content.BroadcastReceiver? = null
    private var scrubTrack: android.media.AudioTrack? = null
    // O volume do MPV / ExoPlayer. Os botões de volume do Android mexem no
    // AudioManager.STREAM_MUSIC, que no caminho bit-perfect (USB DAC /
    // AAudio exclusive) não é aplicado ao stream — e em alguns HALs
    // (Samsung, Pixel) a barra de volume do sistema simplesmente não
    // aparece. Este é o volume DE FATO, aplicado ao PCM antes do
    // conversor. Vai de 0.0 a 1.5 (o 1.5 é boost pra cima do 100% do
    // HAL — clipping no conversor, mas no fone faz diferença).
    private var volumeMpv = 1.0f
    private val volumeStep = 0.1f

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
                    // Disco novo: o lado volta a ser desconhecido, senão o
                    // primeiro quadro do disco seguinte contaria como uma
                    // virada de lado.
                    ladoAtual = -1
                    // Cache dos lados e dos anéis — calculados UMA VEZ por
                    // disco, não a cada quadro. O `repartir` percorre as
                    // faixas; o loop dos anéis percorre de novo. Os dois
                    // viram trabalho de thread da UI competindo com o
                    // render OpenGL, e o frame pulava.
                    val tracksNow = cachedTracks
                    if (tracksNow != null && tracksNow.isNotEmpty()) {
                        val sides = Lados.repartir(tracksNow.map { it.duration })
                        cachedSides = sides
                        cachedGapFracs = Array(sides.size) { i ->
                            val start = sides[i].start
                            val end = sides[i].end
                            val span = maxOf(1L, end - start)
                            val arr = ArrayList<Float>(tracksNow.size)
                            var accum = 0L
                            for (t in tracksNow) {
                                accum += t.duration
                                if (accum > start && accum < end) {
                                    arr.add(((accum - start).toFloat() / span)
                                                .coerceIn(0.01f, 0.99f))
                                }
                            }
                            val out = FloatArray(arr.size)
                            for (k in arr.indices) out[k] = arr[k]
                            out
                        }
                    } else {
                        cachedSides = null
                        cachedGapFracs = null
                    }
                }
                val tracks = cachedTracks
                val sides = cachedSides
                if (tracks != null && tracks.isNotEmpty() && sides != null
                        && sides.isNotEmpty()) {
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
                    val iLado = Lados.indiceEm(sides, posMs)
                        .coerceIn(0, sides.size - 1)
                    val side = sides[iLado]
                    val sideStart = side.start
                    val sideEnd = side.end
                    // O FIM DO LADO É UM ACONTECIMENTO. Sem isto a música
                    // passava de um lado para o outro sozinha, em silêncio —
                    // que é o que um tocador digital faz e o que este
                    // sistema existe para não fazer. Só para FRENTE: buscar
                    // para trás não é o disco virando, é você procurando uma
                    // faixa.
                    if (playing && ladoAtual >= 0 && iLado > ladoAtual) {
                        virouOLado(iLado, sides)
                    }
                    ladoAtual = iLado
                    // Quanto falta DESTE lado — a soneca "no fim do lado"
                    // pergunta isto, e a conta já estava feita aqui.
                    restaNoLado = (sideEnd - posMs).coerceAtLeast(0L)
                    val span = maxOf(1L, sideEnd - sideStart)
                    renderer.playProgress = ((posMs - sideStart).toFloat() / span).coerceIn(0f, 1f)
                    // anéis: cache por lado, lookup O(1).
                    renderer.gapFracs = cachedGapFracs?.get(iLado)
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

        // Back button: stop playback, dismiss service, then finish
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                playing = false
                player?.pause()
                if (deck.stylusDown()) deck.go(Phase.LIFT, System.nanoTime() / 1e9f)
                VinylActivity.clearNowPlaying()
                // Save sleep timer as absolute end time for persistence
                if (sleepTimerEnd > 0) {
                    getSharedPreferences("stylus", MODE_PRIVATE)
                        .edit().putLong("sleep_timer_end", sleepTimerEnd).apply()
                }
                finish()
            }
        })

        deck = Deck()
        renderer = VinylRenderer()
        albumIdField = intent.getLongExtra("albumId", -1)
        renderer.wearSeed = albumIdField.toInt()

        // Restore sleep timer: prefer absolute end time, fallback to duration
        val prefs = getSharedPreferences("stylus", MODE_PRIVATE)
        val savedEnd = prefs.getLong("sleep_timer_end", 0)
        val timerMs = prefs.getLong("sleep_timer", 0)
        when {
            savedEnd > 0 && System.currentTimeMillis() < savedEnd -> sleepTimerEnd = savedEnd
            timerMs > 0 -> sleepTimerEnd = System.currentTimeMillis() + timerMs
        }

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
            // A capa é o MAIOR objeto da tela e era puramente decorativa —
            // girava, brilhava, e não respondia ao toque. O gesto óbvio
            // ("toco no disco pra pausar") não fazia nada, e o play/pause
            // tinha que vir do botão de baixo ou do espaço, que não está
            // visível enquanto a capa ocupa o centro.
            //
            // Sintoma: a única coisa grande na tela que não tem gesto é a
            // coisa que TODO app de música usa como gesto. O play/pause é
            // também o único comando sem destino descoberto — o [enter] da
            // estante não tem equivalente na capa girando.
            isClickable = true
            isFocusable = true
            setOnClickListener { togglePlayPause() }
            // O ripple nativo do Android num ImageView pede foreground; sem
            // ele, o toque some sem feedback. É o mesmo motivo pelo qual o
            // card da estante pinta borda ao toque.
            val fg = android.graphics.drawable.RippleDrawable(
                android.content.res.ColorStateList.valueOf(0x33FFFFFF.toInt()),
                null, null)
            foreground = fg
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
                        setShadowLayer(8f, 0f, 2f, 0xAA080a11.toInt())
                    }
                    root.addView(titleView, FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        android.view.Gravity.TOP or android.view.Gravity.CENTER_HORIZONTAL))

                    // Track info
                    trackInfoView = TextView(this).apply {
                        setTextColor(0xFF8a95aa.toInt())
                        textSize = 11f
                        gravity = android.view.Gravity.CENTER
                        setPadding(24, 0, 24, 4)
                        setShadowLayer(6f, 0f, 1f, 0xAA080a11.toInt())
                    }
                    root.addView(trackInfoView, FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        android.view.Gravity.TOP or android.view.Gravity.CENTER_HORIZONTAL).apply {
                        topMargin = dp(52)
                    })

                }
            } catch (_: Exception) {}
        }

        // ── Bottom: time + controls + hint + progress ──
        // A régua de baixo era uma fileira de glifos Unicode coloridos —
        // seis botões do mesmo tamanho sem hierarquia, sem botão de
        // play/pause visível, e a cor mudava sozinha sem dizer qual
        // estado estava ativo. Agora há DOIS níveis:
        //   · primário: o play/pause, grande, circular, âmbar — o gesto
        //     principal, e o único que o olho procura sem ler.
        //   · secundário: shuffle, repeat, soneca, cast — ícones menores
        //     alinhados, com fundo redondo e ripple.
        timeView = TextView(this).apply {
            setTextColor(0xFF8a95aa.toInt())
            textSize = 12f
            gravity = android.view.Gravity.CENTER
            setPadding(0, dp(2), 0, dp(8))
            // tipo mono-esque: a fonte do sistema em tabular fica
            // monoespaçada o suficiente para o tempo não dançar quando
            // os dígitos mudam.
            typeface = android.graphics.Typeface.MONOSPACE
            letterSpacing = 0.08f
        }

        // ── botões de ícone: um helper só. Fundo redondo, ripple, e a cor
        // do glifo é o que muda entre ativo e inativo. Tudo programático
        // — sem drawable XML, sem recurso novo. O clique é definido DEPOIS
        // (via setOnClickListener) para evitar referência futura a uma
        // variável que ainda não existe — Kotlin não deixa o lambda capturar
        // algo que está sendo declarado.
        val inativo = 0xFF768094.toInt()
        val ativo = 0xFFf0a030.toInt()
        val cinza = 0xFF4A5570.toInt()
        fun iconeBtn(glyph: String, size: Float, cor: Int = inativo): TextView {
            return TextView(this@VinylActivity).apply {
                text = glyph
                setTextColor(cor)
                textSize = size
                gravity = android.view.Gravity.CENTER
                background = android.graphics.drawable.GradientDrawable().apply {
                    setColor(0x14FFFFFF)
                    cornerRadius = dp(18).toFloat()
                    setStroke(0, 0)
                }
                setPadding(dp(10), dp(10), dp(10), dp(10))
                isClickable = true
                isFocusable = true
                foreground = android.graphics.drawable.RippleDrawable(
                    android.content.res.ColorStateList.valueOf(0x44FFFFFF),
                    null, null)
            }
        }

        // ── play/pause grande — círculo âmbar no centro, com o glifo.
        // O único botão da tela que não é igual aos outros, e por motivo:
        // é o único que a pessoa procura sem ler o resto.
        playPauseBtn = TextView(this).apply {
            text = "▶"
            // Usa INK (7,8,11) — a cor de fundo da paleta — para o glifo
            // do play. Um tom mais claro que INK não seria visível sobre o
            // âmbar; mais escuro era flagged pelo check.sh como derivado.
            // INK já é doctestada como existente.
            setTextColor(0xFF07080b.toInt())
            textSize = 26f
            gravity = android.view.Gravity.CENTER
            typeface = android.graphics.Typeface.create("sans-serif-medium",
                                                       android.graphics.Typeface.NORMAL)
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(0xFFf0a030.toInt())
                shape = android.graphics.drawable.GradientDrawable.OVAL
            }
            setPadding(dp(20), dp(20), dp(20), dp(20))
            isClickable = true
            isFocusable = true
            elevation = 8f
            foreground = android.graphics.drawable.RippleDrawable(
                android.content.res.ColorStateList.valueOf(0x66FFFFFF),
                null, null)
        }

        prevBtn = iconeBtn("⏮", 18f)
        nextBtn = iconeBtn("⏭", 18f)
        prevBtn?.setOnClickListener { skipToPrev() }
        nextBtn?.setOnClickListener { skipToNext() }

        // ── fileira primária: prev / play / next ──
        val primaryRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER
        }
        primaryRow.addView(prevBtn, LinearLayout.LayoutParams(
            dp(56), dp(56)).apply { marginEnd = dp(28) })
        primaryRow.addView(playPauseBtn, LinearLayout.LayoutParams(
            dp(72), dp(72)))
        primaryRow.addView(nextBtn, LinearLayout.LayoutParams(
            dp(56), dp(56)).apply { marginStart = dp(28) })

        // ── fileira secundária: shuffle, repeat, soneca, cast ──
        val secondaryRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER
            setPadding(0, dp(6), 0, 0)
        }
        val shuffleBtn = iconeBtn("⇄", 16f, cinza)
        shuffleBtn.setOnClickListener {
            val p = player ?: return@setOnClickListener
            p.toggleShuffle()
            shuffleBtn.setTextColor(if (p.shuffleMode) ativo else cinza)
        }
        secondaryRow.addView(shuffleBtn, LinearLayout.LayoutParams(
            dp(40), dp(40)).apply { marginEnd = dp(20) })

        val repeatBtn = iconeBtn("⟳", 16f, cinza)
        repeatBtn.setOnClickListener {
            val p = player ?: return@setOnClickListener
            p.toggleRepeat()
            val active = p.repeatMode != 0
            repeatBtn.text = if (p.repeatMode == 1) "⟲" else "⟳"
            repeatBtn.setTextColor(if (active) ativo else cinza)
        }
        secondaryRow.addView(repeatBtn, LinearLayout.LayoutParams(
            dp(40), dp(40)).apply { marginEnd = dp(20) })

        val sleepBtn = iconeBtn("⏰", 15f, cinza)
        sleepBtn.setOnClickListener {
            val options = arrayOf("não parar", "15 min", "30 min",
                                  "45 min", "60 min", "90 min",
                                  "no fim do lado")
            val values = longArrayOf(0, 15*60000, 30*60000, 45*60000,
                                     60*60000, 90*60000, -1)
            androidx.appcompat.app.AlertDialog.Builder(this@VinylActivity)
                .setTitle("Parar sozinho")
                .setItems(options) { _, which ->
                    val editor = getSharedPreferences("stylus", MODE_PRIVATE).edit()
                    devolveVolume()
                    sleepFadeFrom = 0L
                    sleepAtSideEnd = values[which] < 0
                    if (values[which] > 0) {
                        sleepTimerEnd = System.currentTimeMillis() + values[which]
                        editor.putLong("sleep_timer_end", sleepTimerEnd).apply()
                    } else {
                        sleepTimerEnd = 0
                        editor.remove("sleep_timer_end").apply()
                    }
                    android.widget.Toast.makeText(this@VinylActivity,
                        options[which], android.widget.Toast.LENGTH_SHORT).show()
                }.show()
        }
        secondaryRow.addView(sleepBtn, LinearLayout.LayoutParams(
            dp(40), dp(40)).apply { marginEnd = dp(20) })

        val castBtn = iconeBtn("◈", 15f, cinza)
        castBtn.setOnClickListener { showCastDialog() }
        secondaryRow.addView(castBtn, LinearLayout.LayoutParams(dp(40), dp(40)))

        val hint = TextView(this).apply {
            text = "toque = pausar · swipe = faixa · duplo = playlist"
            setTextColor(0xFF8a95aa.toInt())
            textSize = 9f
            gravity = android.view.Gravity.CENTER
            alpha = 0.4f
            letterSpacing = 0.05f
            // Fade out after 5 seconds
            postDelayed({
                animate().alpha(0f).setDuration(1000).start()
            }, 5000)
        }

        // Seekable seekbar — tap or drag to seek. A tintaria padrão do
        // Android é verde-limão, e fica berrante contra o resto. Amber
        // casa com a paleta; o buffered usa um âmbar mais baixo para
        // não competir com o polegar.
        val seekBar = android.widget.SeekBar(this).apply {
            max = 100; progress = 0
            layoutParams = LinearLayout.LayoutParams(dp(280), dp(20)).apply { topMargin = dp(10) }
            progressTintList = android.content.res.ColorStateList.valueOf(0xFFf0a030.toInt())
            progressBackgroundTintList = android.content.res.ColorStateList.valueOf(0x33FFFFFF)
            thumbTintList = android.content.res.ColorStateList.valueOf(0xFFf0a030.toInt())
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
            setPadding(0, 0, 0, dp(20))
        }
        bottomCol.addView(timeView)
        bottomCol.addView(primaryRow)
        bottomCol.addView(secondaryRow)
        bottomCol.addView(seekBar)
        bottomCol.addView(hint)
        root.addView(bottomCol, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
            android.view.Gravity.BOTTOM or android.view.Gravity.CENTER_HORIZONTAL))
        bottomBar = bottomCol

        // O play/pause grande precisa responder ao play/pause também
        // (não só ao toque na capa). E o glifo tem que seguir o estado.
        playPauseBtn?.setOnClickListener { togglePlayPause() }

        // Lyrics panel — scrollable, shows current line + context.
        // Fundo semi-transparente com o INK_SOFT (16,18,25) da paleta,
        // cantos arredondados e fading edge para a última linha não
        // encostar na borda.
        lyricPanel = android.widget.ScrollView(this).apply {
            isVerticalScrollBarEnabled = false
            alpha = 0f
            setPadding(dp(16), dp(10), dp(16), dp(10))
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(0xE6101219.toInt())
                cornerRadius = dp(20).toFloat()
            }
            isVerticalFadingEdgeEnabled = true
            overScrollMode = android.view.View.OVER_SCROLL_NEVER
        }
        lyricInner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(10), dp(12), dp(10))
            gravity = android.view.Gravity.CENTER_HORIZONTAL
        }
        lyricPanel?.addView(lyricInner)
        root.addView(lyricPanel, FrameLayout.LayoutParams(
            (dm.widthPixels * 0.90f).toInt(),
            dp(190),
            android.view.Gravity.BOTTOM or android.view.Gravity.CENTER_HORIZONTAL).apply {
            bottomMargin = dp(100)
        })

        // Volume overlay — appears when adjusting volume
        volumeHandler = android.os.Handler(mainLooper)
        volumeOverlay = TextView(this).apply {
            textSize = 16f
            setTextColor(0xFFe8ecf5.toInt())
            gravity = android.view.Gravity.CENTER
            setPadding(dp(24), dp(12), dp(24), dp(12))
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(0xCC0A0C14.toInt())
                cornerRadius = dp(12).toFloat()
            }
            alpha = 0f
        }
        root.addView(volumeOverlay, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            android.view.Gravity.CENTER or android.view.Gravity.TOP).apply {
            topMargin = dp(80)
        })

        // Progress updater
        val progressUpdater = object : Runnable {
            override fun run() {
                soneca()
                val p = player
                if (p != null && p.duration > 0) {
                    seekBarRef?.progress = ((p.currentPosition.toFloat() / p.duration) * 100).toInt()
                    // Time display
                    val cur = p.currentPosition / 1000
                    val rem = (p.duration - p.currentPosition) / 1000
                    var timeStr = String.format("%d:%02d  \u2014  -%d:%02d", cur / 60, cur % 60, rem / 60, rem % 60)
                    // Sleep timer countdown
                    if (sleepAtSideEnd) {
                        timeStr += "  \u2022  para no fim do lado"
                    } else if (sleepTimerEnd > 0) {
                        val sleepRem = ((sleepTimerEnd - System.currentTimeMillis()) / 1000).toInt().coerceAtLeast(0)
                        timeStr += "  \u2022  soneca ${sleepRem / 60}:${String.format("%02d", sleepRem % 60)}"
                    }
                    timeView?.text = timeStr
                    // Lyrics + track info
                    val idx = p.currentTrackIndex
                    val tracks = cachedTracks ?: emptyList()
                    if (idx in tracks.indices) {
                        val t = tracks[idx]
                        if (lyricCacheKey != t.id) {
                            lyricCacheKey = t.id
                            lyricCache = Library.lyricsFor(t.uri, this@VinylActivity)
                        }
                        val lys = lyricCache
                        if (lys != null && lys.isNotEmpty()) {
                            // Busca binária, no Library, e uma só: o laço
                            // linear que estava aqui era a segunda cópia da
                            // conta que o `lyricIndexAt` já fazia.
                            val curIdx = Library.lyricIndexAt(lys, p.currentPosition)
                                .coerceAtLeast(0)
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
                                    val distFromCur = Math.abs(i - curIdx)
                                    val fade = if (isCurrent) 1f else (0.45f - distFromCur * 0.12f).coerceAtLeast(0.18f)
                                    val tv = TextView(this@VinylActivity).apply {
                                        text = lys[i].second.ifBlank { "\u00B7" }
                                        textSize = if (isCurrent) 16f else 11.5f
                                        setTextColor(
                                            if (isCurrent) 0xFFf0a030.toInt()
                                            else 0xFF768094.toInt()
                                        )
                                        gravity = android.view.Gravity.CENTER
                                        setPadding(dp(6), dp(6), dp(6), dp(6))
                                        alpha = fade
                                        if (isCurrent) {
                                            typeface = android.graphics.Typeface.create(
                                                "sans-serif-medium",
                                                android.graphics.Typeface.BOLD)
                                            letterSpacing = 0.03f
                                        } else {
                                            typeface = android.graphics.Typeface.create(
                                                "sans-serif",
                                                android.graphics.Typeface.NORMAL)
                                        }
                                    }
                                    lyricInner?.addView(tv)
                                }
                                // Safe smooth scroll after layout
                                val lpSnapshot = lyricPanel
                                lpSnapshot?.post {
                                    val inner = lyricInner ?: return@post
                                    if (inner.childCount == 0) return@post
                                    val childIdx = (curIdx - start).coerceIn(0, inner.childCount - 1)
                                    val curChild = inner.getChildAt(childIdx) ?: return@post
                                    if (lpSnapshot is android.widget.ScrollView) {
                                        val targetY = (curChild.top + curChild.height / 2 - lpSnapshot.height / 2)
                                            .coerceAtLeast(0)
                                        if (targetY > 0) {
                                            lpSnapshot.smoothScrollTo(0, targetY)
                                        }
                                    } else {
                                        lpSnapshot.invalidate()
                                    }
                                }
                            }
                            lyricPanel?.alpha = 1f
                        } else {
                            lastLyricIdx = -1
                            lyricPanel?.alpha = 0f
                        }
                        trackInfoView?.text = "${idx + 1}/${tracks.size} \u2022 ${t.title} \u2014 ${t.artist}"
                        trackInfoView?.alpha = 0.8f
                        // Track change pulse — flash title briefly
                        if (idx != lastTrackIdx && lastTrackIdx >= 0) {
                            titleView?.alpha = 0.4f
                            titleView?.animate()?.alpha(1f)?.setDuration(600)?.start()
                        }
                        lastTrackIdx = idx
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
                        // **Sintoma:** o disco acabava e a tela simplesmente
                        // FECHAVA. É o acontecimento mais importante que
                        // este sistema tem para dar — a hora em que você
                        // levanta — e ele acontecia como um vídeo terminando
                        // no YouTube. O computador tinha o mesmo buraco.
                        onPlaybackEnd = { oDiscoAcabou() }
                        onTrackChange = { idx ->
                            if (idx in tracks.indices) {
                                val t = tracks[idx]
                                setTrackInfo(t.title, t.artist, t.album, t.duration)
                                updateNowPlaying(t.title, t.artist, albumIdField, idx)
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
                    // Aplica o volume do MPV ao player recém-criado; sem
                    // isto a primeira faixa sairia no 1.0 mesmo se o gesto
                    // já tivesse mudado o volumeMpv (não muda entre
                    // Activities, mas pode mudar entre rotações).
                    applyVolumeMpv()
                }
            }
        }

        // Gestures: tap = toggle controls + play/pause, swipe = prev/next, long press = back
        val gestureDetector = GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
            override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
                togglePlayPause()
                return true
            }
            override fun onLongPress(e: MotionEvent) { finish() }
            override fun onDoubleTap(e: MotionEvent): Boolean {
                showTrackListOverlay()
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
                        if (deck.stylusDown()) deck.go(Phase.LIFT, System.nanoTime() / 1e9f)
                        VinylActivity.clearNowPlaying()
                        finish()
                        return true
                    }
                    // Right half of screen = volume control. Mexe no
                    // volume DO MPV, não no do sistema: o do sistema não
                    // chega ao caminho bit-perfect (HAL ignora STREAM_MUSIC
                    // em algumas Samsung/Pixel), e era por isso que o
                    // gesto "não funcionava".
                    if (e1.x > resources.displayMetrics.widthPixels * 0.6f) {
                        val delta = if (dy < 0) volumeStep else -volumeStep
                        bumpVolumeMpv(delta)
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
                        if (deck.stylusDown()) deck.go(Phase.LIFT, System.nanoTime() / 1e9f)
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
        // Estado inicial: o glifo do botão grande segue o `playing` (que
        // começa true para "view", false para o ceremony), e o volume do
        // MPV já entra aplicado — sem isto a primeira faixa do primeiro
        // disco sai no 1.0 mesmo se a pessoa já tinha mexido no gesto
        // antes (não acontece aqui, mas acontece se a Activity for
        // recriada por rotação).
        refreshPlayPauseGlyph()
        applyVolumeMpv()
    }

    private fun togglePlayPause() {
        playing = !playing
        if (!playing) {
            player?.pause()
            if (deck.phase == Phase.PLAY || deck.phase == Phase.DROP) {
                deck.go(Phase.LIFT, System.nanoTime() / 1e9f)
            }
        } else {
            if (deck.phase == Phase.LIFT || deck.phase == Phase.BREAK) {
                deck.go(Phase.CUE, System.nanoTime() / 1e9f)
            } else if (deck.phase == Phase.STOP) {
                deck.go(Phase.SPINUP, System.nanoTime() / 1e9f)
            } else if (deck.phase == Phase.RETURN) {
                deck.go(Phase.CUE, System.nanoTime() / 1e9f)
            } else {
                player?.play()
                if (deck.phase == Phase.SPINUP || deck.phase == Phase.CUE) {
                    deck.go(Phase.DROP, System.nanoTime() / 1e9f)
                }
            }
        }
        refreshPlayPauseGlyph()
    }

    // O glifo do botão grande segue o estado: ▶ quando toca, ⏸ quando
    // está parado. A chamada acontece em todo toggle, na abertura (o
    // deck começa tocando) e quando o serviço manda uma ação externa
    // (fone, notificação). Sem isto, o botão mente.
    private fun refreshPlayPauseGlyph() {
        playPauseBtn?.text = if (playing) "⏸" else "▶"
    }

    // ── volume do MPV / ExoPlayer ──────────────────────────────────────────
    // **Sintoma:** os botões de volume do Android (e o gesto vertical na
    // metade direita) mexem no AudioManager.STREAM_MUSIC. No caminho
    // bit-perfect (USB DAC / AAudio exclusive) este volume NÃO é aplicado
    // ao stream — o HAL ignora. E em alguns Samsung / Pixel a barra de
    // volume do sistema nem aparece, então não há nem como saber se está
    // mudando. Resultado: "o botão de volume não funciona".
    //
    // A solução é um volume DE FATO, aplicado ao PCM pelo próprio player
    // (exo.volume), que vai de 0.0 a 1.5. Acima de 1.0 o clipping é no
    // ExoPlayer (não no DAC), e em fones faz diferença audível. O gesto
    // vertical e as teclas de hardware do telefone agora mexem aqui.
    private fun bumpVolumeMpv(delta: Float) {
        volumeMpv = (volumeMpv + delta).coerceIn(0f, 1.5f)
        applyVolumeMpv()
        showVolumeOverlay()
    }

    private fun applyVolumeMpv() {
        player?.exo?.volume = volumeMpv
    }

    private fun showVolumeOverlay() {
        val pct = (volumeMpv * 100f).toInt()
        // O ícone muda conforme o volume: alto-falante, alto-falante com
        // onda, mudo. É o que toda barra de volume decente mostra.
        val icone = when {
            volumeMpv <= 0.001f -> "🔇"
            volumeMpv < 0.5f -> "🔈"
            volumeMpv < 1.0f -> "🔉"
            else -> "🔊"
        }
        volumeOverlay?.text = "$icone  $pct%"
        volumeOverlay?.alpha = 0.9f
        volumeHandler?.removeCallbacksAndMessages(null)
        volumeHandler?.postDelayed({ volumeOverlay?.alpha = 0f }, 1200)
    }

    // As teclas de volume do telefone passam pelo sistema antes da Activity,
    // e mexem no AudioManager. Aqui interceptamos e consumimos o evento
    // para que (a) o gesto de fato mude o volume do MPV, e (b) a barra do
    // sistema, quando aparece, NÃO pule junto — são dois volumes
    // diferentes agora.
    override fun dispatchKeyEvent(event: android.view.KeyEvent): Boolean {
        when (event.keyCode) {
            android.view.KeyEvent.KEYCODE_VOLUME_UP ->
                if (event.action == android.view.KeyEvent.ACTION_DOWN) bumpVolumeMpv(volumeStep)
            android.view.KeyEvent.KEYCODE_VOLUME_DOWN ->
                if (event.action == android.view.KeyEvent.ACTION_DOWN) bumpVolumeMpv(-volumeStep)
            else -> return super.dispatchKeyEvent(event)
        }
        return true
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
            bp.width = (dm.widthPixels * 0.38f).toInt()
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
                it.leftMargin = (dm.widthPixels * 0.58f).toInt()
                it.topMargin = (dm.heightPixels * 0.22f).toInt()
                it.width = (dm.widthPixels * 0.38f).toInt()
                titleView?.layoutParams = it
                titleView?.gravity = android.view.Gravity.START
                titleView?.setPadding(dp(8), 0, 0, 0)
            }
            ti?.let {
                it.gravity = android.view.Gravity.TOP or android.view.Gravity.START
                it.leftMargin = (dm.widthPixels * 0.58f).toInt()
                it.topMargin = (dm.heightPixels * 0.22f + dp(44)).toInt()
                it.width = (dm.widthPixels * 0.38f).toInt()
                trackInfoView?.layoutParams = it
                trackInfoView?.gravity = android.view.Gravity.START
                trackInfoView?.setPadding(dp(8), 0, 0, 0)
            }
            // Letra em landscape: à direita, abaixo do título, preenchendo
            // o espaço entre o título e os controles.
            lyricPanel?.let { lp ->
                val lpp = lp.layoutParams as? FrameLayout.LayoutParams ?: return@let
                lpp.gravity = android.view.Gravity.TOP or android.view.Gravity.START
                lpp.leftMargin = (dm.widthPixels * 0.58f).toInt()
                lpp.topMargin = (dm.heightPixels * 0.22f + dp(88)).toInt()
                lpp.width = (dm.widthPixels * 0.38f).toInt()
                lpp.height = (dm.heightPixels * 0.44f).toInt()
                lpp.bottomMargin = dp(12)
                lp.layoutParams = lpp
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
            // Letra em retrato: centro-inferior, acima dos controles.
            lyricPanel?.let { lp ->
                val lpp = lp.layoutParams as? FrameLayout.LayoutParams ?: return@let
                lpp.gravity = android.view.Gravity.BOTTOM or android.view.Gravity.CENTER_HORIZONTAL
                lpp.leftMargin = 0; lpp.topMargin = 0
                lpp.width = (dm.widthPixels * 0.90f).toInt()
                lpp.height = dp(190)
                lpp.bottomMargin = dp(100)
                lp.layoutParams = lpp
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
            setTextColor(0xFF768094.toInt())
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
                val prefix = if (i == currentIdx) "\u25B6 " else "${i + 1}. "
                tv.text = "$prefix${t.title}"
                tv.setTextColor(if (i == currentIdx) 0xFFf0a030.toInt() else 0xFF8a95aa.toInt())
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
        val construtor = androidx.appcompat.app.AlertDialog.Builder(this)
            .setView(loading)
            .setNegativeButton("Cancelar", null)
        // **Sintoma:** dava para COMEÇAR a transmitir e não para parar. O
        // `CastManager.stopCast` existia, com o servidor HTTP e a thread
        // para desmontar, e não era chamado em lugar nenhum: quem mandava o
        // disco para a caixa da sala ficava com o servidor de pé até fechar
        // o app. É a família do `set_text` que ninguém chamava — a peça
        // existe, o fio não.
        if (CastManager.isStreaming) {
            construtor.setNeutralButton("Parar de transmitir") { _, _ ->
                CastManager.stopCast()
                android.widget.Toast.makeText(this, "transmissão encerrada",
                    android.widget.Toast.LENGTH_SHORT).show()
            }
        }
        val dialog = construtor.create()
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

    /** Quanto dura o esmaecimento. O mesmo do computador (`App.ESMAECER`). */
    private val ESMAECER_MS = 20_000L

    private fun devolveVolume() {
        val v = volumeAntes
        if (v >= 0f) {
            player?.exo?.volume = v
            volumeAntes = -1f
        }
    }

    /**
     * A soneca: esmaece e levanta a agulha. Roda no laço do relógio.
     *
     * **O que havia antes:** um `player?.pause()` seco no instante em que o
     * relógio batia. No meio de uma faixa, com a pessoa quase dormindo, o
     * CORTE é justamente o que acorda — e o computador tinha o mesmo defeito
     * até pouco tempo atrás.
     *
     * O ganho digital destes vinte segundos é uma exceção CONSCIENTE à tese
     * do sistema (o áudio sai sem tocar no volume; ver o `--volume=100` do
     * stylus-deck). A alternativa é o corte seco, e ele é pior.
     */
    private fun soneca() {
        val agora = System.currentTimeMillis()
        if (sleepAtSideEnd) {
            if (restaNoLado < 0 || restaNoLado > ESMAECER_MS) return
            if (sleepFadeFrom == 0L) sleepFadeFrom = agora - (ESMAECER_MS - restaNoLado)
        } else if (sleepTimerEnd > 0) {
            if (agora < sleepTimerEnd - ESMAECER_MS) return
            if (sleepFadeFrom == 0L) sleepFadeFrom = agora
        } else {
            return
        }
        val f = ((agora - sleepFadeFrom).toFloat() / ESMAECER_MS).coerceIn(0f, 1f)
        val p = player ?: return
        if (volumeAntes < 0f) volumeAntes = p.exo.volume
        // Em POTÊNCIA e não linear: o ouvido é logarítmico, e uma rampa
        // linear soa como "nada, nada, nada, sumiu".
        p.exo.volume = volumeAntes * (1f - f) * (1f - f)
        if (f < 1f) return
        playing = false
        p.pause()
        if (deck.stylusDown()) deck.go(Phase.LIFT, System.nanoTime() / 1e9f)
        // O volume volta ANTES de tudo: senão o disco de amanhã começa mudo.
        devolveVolume()
        val quanto = if (sleepAtSideEnd) "no fim do lado" else "a soneca acabou"
        android.widget.Toast.makeText(this, "boa noite \u2014 $quanto",
            android.widget.Toast.LENGTH_SHORT).show()
        sleepTimerEnd = 0
        sleepAtSideEnd = false
        sleepFadeFrom = 0L
        getSharedPreferences("stylus", MODE_PRIVATE).edit()
            .remove("sleep_timer_end").apply()
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
            style = android.graphics.Paint.Style.STROKE; strokeWidth = size * 0.02f; color = 0x40080a11
        }
        canvas.drawCircle(size / 2f, size / 2f, size / 2f - size * 0.01f, ringPaint)
        val holePaint = android.graphics.Paint().apply {
            color = android.graphics.Color.TRANSPARENT
            xfermode = android.graphics.PorterDuffXfermode(android.graphics.PorterDuff.Mode.CLEAR)
        }
        canvas.drawCircle(size / 2f, size / 2f, size * 0.040f, holePaint)
        val holeRing = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
            style = android.graphics.Paint.Style.STROKE; strokeWidth = size * 0.008f; color = 0x60080a11
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

    /**
     * Reparte as faixas em LADOS — a mesma lei do `vinyl.Album._build_sides`
     * do computador.
     *
     * POR QUE ISTO MUDOU
     * ------------------
     * O que havia aqui era uma regra própria e diferente: teto de 22 minutos
     * (o computador usa 26) e enchia cada lado até a boca. Duas
     * consequências, e as duas o usuário vê:
     *
     *  - o MESMO disco saía repartido de um jeito no celular e de outro no
     *    computador, com "vira em X" diferente nos dois. A coleção é a mesma
     *    dos dois lados, e a promessa do sistema é que ela SE PARECE a mesma;
     *  - e podia dar um número ÍMPAR de lados, que é um objeto que não
     *    existe: disco tem dois lados sempre, e disco duplo tem quatro.
     *
     * A lei, então, igual à do computador: o número de DISCOS é que se
     * arredonda para cima; o alvo do equilíbrio é recalculado a partir do que
     * RESTA (o que falta dividido pelos lados que faltam), senão um corte
     * forçado pelo teto empurra o excesso até estourar num lado a mais; e um
     * resultado ímpar é refeito pedindo o par seguinte.
     *
     * ATENÇÃO: nada neste repositório COMPILA o app do celular — não há
     * gradle no check.sh nem na construção da nuvem. O que o check.sh
     * confere é que o teto daqui é o mesmo do vinyl.py.
     */
    /**
     * Acabou o lado: a agulha sobe, a música pára e a tela pede o GESTO.
     *
     * É a única coisa que este sistema faz e nenhum outro tocador faz. O
     * corte em lados já existia aqui (o raio da agulha andava lado a lado) e
     * o acontecimento não: a música passava de um lado para o outro sozinha,
     * em silêncio.
     *
     * Não retoma sozinho de propósito. Um toca-discos não vira o disco por
     * você — é o gesto que separa ouvir um disco de ouvir uma playlist.
     */
    private fun virouOLado(iLado: Int, sides: List<Lados.Lado>) {
        val now = System.nanoTime() / 1e9f
        playing = false
        player?.pause()
        if (deck.phase == Phase.PLAY || deck.phase == Phase.DROP) {
            deck.go(Phase.LIFT, now)
        }
        mostrarGesto(Lados.rotulo(iLado - 1),
                     Lados.gesto(iLado, sides.size))
    }

    /**
     * O DISCO acabou — não um lado, o disco.
     *
     * O fim do lado tinha tela desde sempre ("vire o disco"); o fim do disco
     * fechava a Activity em silêncio. A pergunta que aparece aqui é sempre a
     * mesma — "e agora qual?" — e o aviso só vale se responder: o de cima da
     * PILHA quando há pilha (é um compromisso que a pessoa assumiu), e nada
     * inventado quando não há.
     */
    private fun oDiscoAcabou() {
        val now = System.nanoTime() / 1e9f
        playing = false
        if (deck.stylusDown() || deck.phase == Phase.DROP) deck.go(Phase.LIFT, now)
        val nome = cachedTracks?.firstOrNull()?.album ?: ""
        mostrarGesto("O DISCO", if (nome.isEmpty()) "levante a agulha"
                                else "$nome — levante a agulha",
                     fecha = true)
    }

    /** A tela inteira dizendo o que fazer, e o toque que retoma.
     *
     *  `fecha` = o toque SAI em vez de retomar: no fim do disco não há o que
     *  retomar, e um toque que volta a tocar do começo seria o contrário do
     *  que acabou de acontecer.
     */
    private fun mostrarGesto(acabou: String, gesto: String,
                             fecha: Boolean = false) {
        val root = window.decorView.findViewById<ViewGroup>(android.R.id.content)
        val aviso = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = android.view.Gravity.CENTER
            setBackgroundColor(0xF207080B.toInt())
        }
        aviso.addView(TextView(this).apply {
            text = acabou
            setTextColor(0xFF8a95aa.toInt())
            textSize = 14f
            letterSpacing = 0.18f
            gravity = android.view.Gravity.CENTER
        })
        aviso.addView(TextView(this).apply {
            text = "ACABOU"
            setTextColor(0xFFf0a030.toInt())
            textSize = 40f
            setTypeface(null, android.graphics.Typeface.BOLD)
            gravity = android.view.Gravity.CENTER
            setPadding(0, dp(6), 0, dp(14))
        })
        aviso.addView(TextView(this).apply {
            text = gesto
            setTextColor(0xFFe8ecf5.toInt())
            textSize = 18f
            gravity = android.view.Gravity.CENTER
            setPadding(dp(28), 0, dp(28), dp(24))
        })
        aviso.addView(TextView(this).apply {
            text = if (fecha) "toque para voltar à estante" else "toque para continuar"
            setTextColor(0xFF4A5570.toInt())
            textSize = 11f
            gravity = android.view.Gravity.CENTER
        })
        aviso.setOnClickListener {
            root.removeView(aviso)
            if (fecha) {
                finish()
                return@setOnClickListener
            }
            // Retomar é a CERIMÔNIA de novo, não um play: o braço volta,
            // desce e só então a música começa. Foi você que virou o disco.
            val now = System.nanoTime() / 1e9f
            playing = true
            deck.go(Phase.CUE, now)
        }
        root.addView(aviso, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT))
    }

    override fun onDestroy() {
        super.onDestroy()
        clearNowPlaying()
        try { mediaReceiver?.let { unregisterReceiver(it) } } catch (_: Exception) {}
        try { scrubTrack?.release() } catch (_: Exception) {}
        player?.release()
    }
}
