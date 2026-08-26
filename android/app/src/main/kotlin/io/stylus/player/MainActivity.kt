package io.stylus.player

import android.Manifest
import android.content.ContentResolver
import android.content.Context
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlin.math.min

class MainActivity : AppCompatActivity() {

    private lateinit var recycler: RecyclerView
    private lateinit var emptyView: TextView
    private lateinit var statsBar: LinearLayout
    private lateinit var recentScroll: android.widget.HorizontalScrollView
    private lateinit var recentRow: LinearLayout
    private lateinit var recentHeader: TextView
    private lateinit var searchInput: EditText
    private lateinit var sortBtn: TextView
    private lateinit var dacIndicator: TextView
    private lateinit var nowPlayingBar: LinearLayout
    private lateinit var nowPlayingText: TextView
    private lateinit var prefs: SharedPreferences
    private var allAlbums = listOf<Library.Album>()
    private var filteredAlbums = listOf<Library.Album>()
    private var sortMode = 0
    private val sortLabels = listOf("A-Z", "ARTISTA", "RECENTE", "FAVORITOS")

    companion object {
        private const val PERM_REQ = 100
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = getSharedPreferences("stylus", MODE_PRIVATE)
        sortMode = prefs.getInt("sort_mode", 0)

        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_FULLSCREEN or
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        )
        window.statusBarColor = 0xFF050608.toInt()
        window.navigationBarColor = 0xFF050608.toInt()

        val root = FrameLayout(this).apply { setBackgroundColor(0xFF050608.toInt()) }

        // Header
        val headerRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dp(20), dp(44), dp(20), dp(2))
            gravity = Gravity.CENTER_VERTICAL
        }
        val header = TextView(this).apply {
            text = "STYLUS"
            setTextColor(0xFF6A7590.toInt())
            textSize = 10f
            letterSpacing = 0.22f
            typeface = Typeface.DEFAULT_BOLD
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        headerRow.addView(header)

        dacIndicator = TextView(this).apply {
            text = ""
            setTextColor(0xFF5A8A5A.toInt())
            textSize = 8f
            setPadding(dp(6), dp(2), dp(6), dp(2))
            visibility = View.GONE
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(0x185A8A5A.toInt())
                cornerRadius = dp(4).toFloat()
                setStroke(1, 0x335A8A5A)
            }
        }
        headerRow.addView(dacIndicator)

        sortBtn = TextView(this).apply {
            text = sortLabels[sortMode]
            setTextColor(0xFF4A5570.toInt())
            textSize = 9f
            letterSpacing = 0.06f
            setPadding(dp(12), dp(4), dp(4), dp(4))
            setOnClickListener {
                sortMode = (sortMode + 1) % sortLabels.size
                text = sortLabels[sortMode]
                prefs.edit().putInt("sort_mode", sortMode).apply()
                applyFilter()
            }
        }
        headerRow.addView(sortBtn)

        val menuBtn = TextView(this).apply {
            text = "\u22EE"
            setTextColor(0xFF4A5570.toInt())
            textSize = 18f
            setPadding(dp(12), dp(4), dp(4), dp(4))
            setOnClickListener { showMenuDialog() }
        }
        headerRow.addView(menuBtn)
        root.addView(headerRow, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ))

        // Search
        val searchContainer = FrameLayout(this).apply {
            setPadding(dp(16), dp(50), dp(16), dp(0))
        }
        searchInput = EditText(this).apply {
            hint = "Buscar..."
            setTextColor(0xFFD0D8E8.toInt())
            setHintTextColor(0xFF3A4560.toInt())
            textSize = 13f
            setPadding(dp(12), dp(8), dp(12), dp(8))
            isSingleLine = true
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(0xFF0A0C12.toInt())
                cornerRadius = dp(8).toFloat()
                setStroke(1, 0xFF151A28.toInt())
            }
            addTextChangedListener(object : android.text.TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { applyFilter() }
                override fun afterTextChanged(s: android.text.Editable?) {}
            })
        }
        searchContainer.addView(searchInput, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ))
        root.addView(searchContainer, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(80) })

        // Stats bar
        statsBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dp(20), dp(4), dp(20), dp(2))
            gravity = Gravity.CENTER_VERTICAL
        }
        root.addView(statsBar, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(118) })

        // Recently played horizontal section
        recentHeader = TextView(this).apply {
            text = "RECENTE"
            setTextColor(0xFF3A4560.toInt())
            textSize = 9f
            letterSpacing = 0.08f
            setPadding(dp(20), dp(8), dp(20), dp(2))
        }
        root.addView(recentHeader, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(138) })

        recentScroll = android.widget.HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            setPadding(dp(16), dp(0), dp(16), dp(0))
        }
        recentRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        recentScroll.addView(recentRow)
        root.addView(recentScroll, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(155) })

        // Grid
        recycler = RecyclerView(this).apply {
            layoutManager = GridLayoutManager(this@MainActivity, calcCols())
            setPadding(dp(10), dp(280), dp(10), dp(60))
            clipToPadding = false
            overScrollMode = RecyclerView.OVER_SCROLL_NEVER
        }
        root.addView(recycler, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
        ))

        // Empty
        emptyView = TextView(this).apply {
            text = "\u25CE\nNenhuma musica encontrada\n\nConecte um USB com musicas\nou configure o WebDAV"
            setTextColor(0xFF3A4560.toInt())
            textSize = 14f
            visibility = View.GONE
            gravity = Gravity.CENTER
            setLineSpacing(0f, 1.4f)
        }
        root.addView(emptyView, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
        ))

        // Bottom bar
        val bottomBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(0xFF0A0C12.toInt())
            setPadding(dp(16), dp(8), dp(16), dp(8))
            gravity = Gravity.CENTER_VERTICAL
        }
        val bottomText = TextView(this).apply {
            text = ""
            setTextColor(0xFF4A5570.toInt())
            textSize = 11f
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        statsBar.tag = bottomText  // store reference

        val shuffleBtn = TextView(this).apply {
            text = "\u21C4"
            setTextColor(0xFF4A5570.toInt())
            textSize = 16f
            setPadding(dp(10), dp(4), dp(10), dp(4))
            setOnClickListener {
                if (filteredAlbums.isNotEmpty()) {
                    val shuffled = filteredAlbums.shuffled()
                    val intent = VinylActivity.ceremonyIntent(this@MainActivity, shuffled[0].id)
                    intent.putExtra("shuffle", true)
                    startActivity(intent)
                }
            }
        }

        val playBtn = TextView(this).apply {
            text = "\u25B6"
            setTextColor(0xFFB0B8D0.toInt())
            textSize = 16f
            setPadding(dp(10), dp(4), dp(10), dp(4))
            setOnClickListener {
                if (filteredAlbums.isNotEmpty()) {
                    prefs.edit().putLong("played_${filteredAlbums[0].id}", System.currentTimeMillis()).apply()
                    startActivity(VinylActivity.ceremonyIntent(this@MainActivity, filteredAlbums[0].id))
                }
            }
        }

        bottomBar.addView(bottomText)
        bottomBar.addView(shuffleBtn)
        bottomBar.addView(playBtn)
        root.addView(bottomBar, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM
        ))

        // Now Playing bar — shows when returning from player
        nowPlayingBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(0xFF111620.toInt())
            setPadding(dp(14), dp(8), dp(14), dp(8))
            gravity = Gravity.CENTER_VERTICAL
            visibility = View.GONE
            elevation = dp(4).toFloat()
        }
        nowPlayingText = TextView(this).apply {
            setTextColor(0xFF8892B0.toInt())
            textSize = 10f
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        nowPlayingBar.addView(nowPlayingText)
        val npGoBtn = TextView(this).apply {
            text = "\u25B6"
            setTextColor(0xFFE8ECF5.toInt())
            textSize = 14f
            setPadding(dp(8), dp(2), dp(2), dp(2))
            setOnClickListener {
                val np = VinylActivity
                if (np.nowPlayingActive && np.nowPlayingAlbumId > 0) {
                    startActivity(VinylActivity.ceremonyIntent(this@MainActivity, np.nowPlayingAlbumId))
                }
            }
        }
        nowPlayingBar.addView(npGoBtn)
        root.addView(nowPlayingBar, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM
        ).apply { bottomMargin = dp(36) })

        setContentView(root)
        if (hasPermission()) loadAlbums() else requestPermission()
    }

    private fun calcCols(): Int {
        val px = resources.displayMetrics.widthPixels
        return (px / dp(170)).coerceIn(2, 5)
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun hasPermission(): Boolean = if (Build.VERSION.SDK_INT >= 33) {
        ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_AUDIO) == PackageManager.PERMISSION_GRANTED
    } else {
        @Suppress("DEPRECATION")
        ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestPermission() {
        val perm = if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_AUDIO
        else @Suppress("DEPRECATION") Manifest.permission.READ_EXTERNAL_STORAGE
        ActivityCompat.requestPermissions(this, arrayOf(perm), PERM_REQ)
    }

    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code, permissions, results)
        if (code == PERM_REQ && results.isNotEmpty() && results[0] == PackageManager.PERMISSION_GRANTED) loadAlbums()
        else if (code == PERM_REQ) { emptyView.text = "Sem permissao"; emptyView.visibility = View.VISIBLE }
    }

    private fun loadAlbums() {
        var list = Library.albums(this)
        try {
            val roots = listOf(
                java.io.File("/sdcard/Music"), java.io.File("/sdcard/Musicas"),
                java.io.File("/storage/emulated/0/Music"), java.io.File("/storage/emulated/0/Musicas"),
                java.io.File(getExternalFilesDir(null)?.path ?: "")
            ).filter { it.isDirectory }
            val folderAlbums = Library.shelfByFolders(roots)
            if (list.isEmpty() && folderAlbums.isNotEmpty()) {
                list = folderAlbums.mapIndexed { idx, f ->
                    Library.Album(id = 900000L + idx, name = f.name,
                        artist = f.parentFile?.name ?: "Desconhecido",
                        trackCount = Library.tracksFromFolder(f).size, artUri = null)
                }
            }
        } catch (_: Exception) {}
        allAlbums = list
        applyFilter()
    }

    private fun applyFilter() {
        val query = searchInput?.text?.toString()?.trim()?.lowercase() ?: ""
        filteredAlbums = if (query.isEmpty()) allAlbums else {
            allAlbums.filter { it.name.lowercase().contains(query) || it.artist.lowercase().contains(query) }
        }
        filteredAlbums = when (sortMode) {
            1 -> filteredAlbums.sortedBy { it.artist.lowercase() }
            2 -> filteredAlbums.recentlyPlayed(prefs)
            3 -> filteredAlbums.filter { prefs.getBoolean("fav_${it.id}", false) }
            else -> filteredAlbums.sortedBy { it.name.lowercase() }
        }

        // Stats
        val totalTracks = filteredAlbums.sumOf { it.trackCount }
        val totalMs = filteredAlbums.sumOf { it.totalDuration }
        val totalH = totalMs / 3600000
        val totalM = (totalMs % 3600000) / 60000
        val statsText = when {
            filteredAlbums.isEmpty() -> "Nenhum album"
            query.isNotEmpty() -> "${filteredAlbums.size} resultado${if (filteredAlbums.size != 1) "s" else ""}"
            else -> "${filteredAlbums.size} albuns \u2022 ${totalTracks} faixas \u2022 ${totalH}h${totalM}m"
        }
        val tv = statsBar.tag as? TextView
        tv?.text = statsText

        // Recently played section
        val recentAlbums = allAlbums
            .filter { prefs.getLong("played_${it.id}", 0L) > 0 }
            .sortedByDescending { prefs.getLong("played_${it.id}", 0L) }
            .take(8)

        recentRow.removeAllViews()
        if (recentAlbums.isNotEmpty()) {
            recentScroll.visibility = View.VISIBLE
            recentHeader.visibility = View.VISIBLE
            for (album in recentAlbums) {
                val card = LinearLayout(this).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(dp(3), dp(3), dp(3), dp(3))
                    isClickable = true
                    layoutParams = LinearLayout.LayoutParams(dp(110), ViewGroup.LayoutParams.WRAP_CONTENT)
                }
                val img = ImageView(this).apply {
                    layoutParams = LinearLayout.LayoutParams(dp(104), dp(104))
                    scaleType = ImageView.ScaleType.CENTER_CROP
                    setBackgroundColor(0xFF08090C.toInt())
                }
                card.addView(img)
                val name = TextView(this).apply {
                    text = album.name
                    setTextColor(0xFF8892B0.toInt())
                    textSize = 8f
                    maxLines = 1
                    ellipsize = android.text.TextUtils.TruncateAt.END
                    setPadding(dp(2), dp(2), dp(2), 0)
                }
                card.addView(name)
                card.setOnClickListener {
                    prefs.edit().putLong("played_${album.id}", System.currentTimeMillis()).apply()
                    startActivity(VinylActivity.ceremonyIntent(this, album.id))
                }
                recentRow.addView(card)

                // Load cover async
                Thread {
                    try {
                        contentResolver.openInputStream(album.coverUri())?.use { stream ->
                            val bmp = BitmapFactory.decodeStream(stream)
                            if (bmp != null) img.post { img.setImageBitmap(bmp) }
                        }
                    } catch (_: Exception) {}
                }.start()
            }
        } else {
            recentScroll.visibility = View.GONE
            recentHeader.visibility = View.GONE
        }

        if (filteredAlbums.isEmpty()) {
            emptyView.text = if (query.isNotEmpty()) "Nada para \"$query\"" else "Nenhuma musica encontrada"
            emptyView.visibility = View.VISIBLE
        } else {
            emptyView.visibility = View.GONE
            recycler.adapter = AlbumAdapter(filteredAlbums, contentResolver, prefs,
                onClick = { album ->
                    prefs.edit().putLong("played_${album.id}", System.currentTimeMillis()).apply()
                    startActivity(VinylActivity.ceremonyIntent(this, album.id))
                },
                onLongClick = { album -> showTrackList(album) }
            )
        }
    }

    private var usbReceiver: android.content.BroadcastReceiver? = null

    override fun onResume() {
        super.onResume()
        checkDacStatus()
        updateNowPlayingBar()
        recycler.adapter?.notifyDataSetChanged()
        // Listen for USB plug/unplug
        usbReceiver = object : android.content.BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: android.content.Intent) {
                checkDacStatus()
            }
        }
        val usbFilter = android.content.IntentFilter().apply {
            addAction(android.hardware.usb.UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(android.hardware.usb.UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(usbReceiver, usbFilter, Context.RECEIVER_EXPORTED)
        } else {
            registerReceiver(usbReceiver, usbFilter)
        }
    }

    override fun onPause() {
        super.onPause()
        usbReceiver?.let { unregisterReceiver(it) }
        usbReceiver = null
    }

    private fun updateNowPlayingBar() {
        val np = VinylActivity
        if (np.nowPlayingActive && np.nowPlayingAlbumId > 0) {
            nowPlayingBar.visibility = View.VISIBLE
            nowPlayingText.text = "${np.nowPlayingArtist} \u2022 ${np.nowPlayingTitle}"
        } else {
            nowPlayingBar.visibility = View.GONE
        }
    }

    private fun checkDacStatus() {
        try {
            val am = getSystemService(Context.AUDIO_SERVICE) as android.media.AudioManager
            val devices = am.getDevices(android.media.AudioManager.GET_DEVICES_OUTPUTS)
            val hasDac = devices.any {
                it.type == android.media.AudioDeviceInfo.TYPE_USB_DEVICE ||
                it.type == android.media.AudioDeviceInfo.TYPE_USB_HEADSET ||
                it.type == android.media.AudioDeviceInfo.TYPE_WIRED_HEADPHONES
            }
            if (hasDac) {
                val usbDev = devices.firstOrNull {
                    it.type == android.media.AudioDeviceInfo.TYPE_USB_DEVICE ||
                    it.type == android.media.AudioDeviceInfo.TYPE_USB_HEADSET
                }
                val name = usbDev?.productName?.toString() ?: "USB DAC"
                val rates = usbDev?.sampleRates
                val rateStr = if (rates != null && rates.isNotEmpty()) " \u2022 ${rates.max() / 1000}kHz" else ""
                dacIndicator.text = "DAC: $name$rateStr"
                dacIndicator.visibility = View.VISIBLE
            } else dacIndicator.visibility = View.GONE
        } catch (_: Exception) { dacIndicator.visibility = View.GONE }
    }

    private fun showMenuDialog() {
        val timerOptions = arrayOf("Sem timer", "15 min", "30 min", "60 min", "90 min")
        val timerValues = longArrayOf(0, 15*60000, 30*60000, 60*60000, 90*60000)
        val currentTimer = prefs.getLong("sleep_timer", 0)
        val timerIdx = timerValues.indexOf(currentTimer).coerceAtLeast(0)

        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("STYLUS")
            .setItems(arrayOf("WebDAV \u2022 Sleep Timer (atual: ${timerOptions[timerIdx]})", "Sobre")) { _, which ->
                when (which) {
                    0 -> showWebdavDialog()
                    1 -> showAboutDialog()
                }
            }
            .setNegativeButton("Fechar", null)
            .show()
    }

    private fun showWebdavDialog() {
        val cur = prefs.getString("webdav_url", "") ?: ""
        val input = EditText(this).apply {
            hint = "https://seu.webdav/exemplo/"
            setText(cur)
            setTextColor(0xFFE8ECF5.toInt())
            setHintTextColor(0xFF6B7898.toInt())
            textSize = 13f
        }
        val pad = dp(20)
        val container = FrameLayout(this).apply { setPadding(pad, pad, pad, pad); addView(input) }

        val timerOptions = arrayOf("Sem timer", "15 min", "30 min", "60 min", "90 min")
        val timerValues = longArrayOf(0, 15*60000, 30*60000, 60*60000, 90*60000)

        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("WebDAV")
            .setMessage("URL da colecao remota")
            .setView(container)
            .setPositiveButton("Salvar") { _, _ ->
                prefs.edit().putString("webdav_url", input.text.toString().trim()).apply()
                android.widget.Toast.makeText(this, "WebDAV salvo", android.widget.Toast.LENGTH_SHORT).show()
            }
            .setNeutralButton("Sleep Timer") { _, _ ->
                androidx.appcompat.app.AlertDialog.Builder(this)
                    .setTitle("Sleep Timer")
                    .setItems(timerOptions) { _, which ->
                        prefs.edit().putLong("sleep_timer", timerValues[which]).apply()
                        android.widget.Toast.makeText(this, timerOptions[which], android.widget.Toast.LENGTH_SHORT).show()
                    }.show()
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun showAboutDialog() {
        val tv = TextView(this).apply {
            text = "STYLUS Player\nBit-perfect audio for Android\n\n" +
                   "Formatos: FLAC, ALAC, WAV, AIFF, MP3, AAC, OGG\n" +
                   "Saidas: USB DAC bit-perfect, DLNA/UPnP\n" +
                   "last.fm: scrobble autom\u00e1tico\n\n" +
                   "${allAlbums.size} albuns na estante"
            setTextColor(0xFF8892B0.toInt())
            textSize = 12f
            setPadding(dp(24), dp(16), dp(24), dp(8))
            setLineSpacing(0f, 1.3f)
        }
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("STYLUS")
            .setView(tv)
            .setPositiveButton("OK", null)
            .show()
    }

    private fun showTrackList(album: Library.Album) {
        Thread {
            val tracks = Library.albumTracks(this, album.id)
            runOnUiThread {
                if (tracks.isEmpty()) {
                    android.widget.Toast.makeText(this, "Nenhuma faixa", android.widget.Toast.LENGTH_SHORT).show()
                    return@runOnUiThread
                }
                val items = tracks.mapIndexed { i, t ->
                    val min = t.duration / 60000
                    val sec = (t.duration / 1000) % 60
                    "${i + 1}. ${t.title} (${min}:${String.format("%02d", sec)})"
                }.toTypedArray()
                androidx.appcompat.app.AlertDialog.Builder(this)
                    .setTitle("${album.artist} — ${album.name}")
                    .setItems(items) { _, which ->
                        prefs.edit().putLong("played_${album.id}", System.currentTimeMillis()).apply()
                        val intent = VinylActivity.ceremonyIntent(this, album.id)
                        intent.putExtra("trackIndex", which)
                        startActivity(intent)
                    }
                    .setPositiveButton("Tocar", null)
                    .setNegativeButton("Fechar", null)
                    .show()
            }
        }.start()
    }

    private fun List<Library.Album>.recentlyPlayed(prefs: SharedPreferences): List<Library.Album> {
        return sortedByDescending { prefs.getLong("played_${it.id}", 0L) }
    }

    // ═══════════════════════════════════════════════════════════════════
    // ADAPTER — album cards
    // ═══════════════════════════════════════════════════════════════════
    private class AlbumAdapter(
        private val items: List<Library.Album>,
        private val resolver: ContentResolver,
        private val prefs: SharedPreferences,
        private val onClick: (Library.Album) -> Unit,
        private val onLongClick: (Library.Album) -> Unit
    ) : RecyclerView.Adapter<VH>() {
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val ctx = parent.context
            val card = LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp2(ctx, 3), dp2(ctx, 3), dp2(ctx, 3), dp2(ctx, 3))
                isClickable = true
                isFocusable = true
                val bg = android.graphics.drawable.GradientDrawable().apply {
                    setColor(0xFF0A0C12.toInt())
                    cornerRadius = dp2(ctx, 6).toFloat()
                }
                background = bg
                setOnTouchListener { v, event ->
                    when (event.action) {
                        android.view.MotionEvent.ACTION_DOWN -> {
                            bg.setColor(0xFF141828.toInt())
                            bg.setStroke(1, 0xFF252E48.toInt())
                        }
                        android.view.MotionEvent.ACTION_UP, android.view.MotionEvent.ACTION_CANCEL -> {
                            bg.setColor(0xFF0A0C12.toInt())
                            bg.setStroke(0, 0)
                        }
                    }
                    false
                }
            }

            val cover = ImageView(ctx).apply {
                layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp2(ctx, 140))
                scaleType = ImageView.ScaleType.CENTER_CROP
                setBackgroundColor(0xFF08090C.toInt())
                adjustViewBounds = true
                id = View.generateViewId()
            }
            card.addView(cover)

            val title = TextView(ctx).apply {
                setTextColor(0xFFC0C8DD.toInt())
                textSize = 11f
                maxLines = 1
                ellipsize = android.text.TextUtils.TruncateAt.END
                setPadding(dp2(ctx, 6), dp2(ctx, 5), dp2(ctx, 6), 0)
                id = View.generateViewId()
            }
            card.addView(title)

            val artist = TextView(ctx).apply {
                setTextColor(0xFF4A5570.toInt())
                textSize = 9f
                maxLines = 1
                ellipsize = android.text.TextUtils.TruncateAt.END
                setPadding(dp2(ctx, 6), dp2(ctx, 1), dp2(ctx, 6), dp2(ctx, 5))
                id = View.generateViewId()
            }
            card.addView(artist)

            // Track count + duration row
            val meta = TextView(ctx).apply {
                setTextColor(0xFF2E3650.toInt())
                textSize = 8f
                maxLines = 1
                setPadding(dp2(ctx, 6), 0, dp2(ctx, 6), dp2(ctx, 3))
                id = View.generateViewId()
            }
            card.addView(meta)

            // Favorite star button (click handled in onBindViewHolder)
            val favBtn = TextView(ctx).apply {
                text = "\u2606"
                setTextColor(0xFF4A5570.toInt())
                textSize = 14f
                setPadding(dp2(ctx, 4), 0, dp2(ctx, 6), dp2(ctx, 2))
                id = View.generateViewId()
            }
            card.addView(favBtn)

            return VH(card, cover, title, artist, meta, favBtn)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val album = items[position]
            holder.title.text = album.name
            holder.artist.text = album.artist
            holder.meta.text = album.durationString()
            holder.cover.setImageBitmap(null)
            holder.cover.setBackgroundColor(0xFF08090C.toInt())

            // Square cover
            holder.cover.post {
                val params = holder.cover.layoutParams
                params.height = min(holder.cover.width, dp2(holder.itemView.context, 200))
                holder.cover.layoutParams = params
            }

            // Load cover async
            try {
                Thread {
                    try {
                        resolver.openInputStream(album.coverUri())?.use { stream ->
                            val bmp = BitmapFactory.decodeStream(stream)
                            if (bmp != null) holder.cover.post { holder.cover.setImageBitmap(bmp) }
                        }
                    } catch (_: Exception) {}
                }.start()
            } catch (_: Exception) {}

            // Recently played indicator
            val lastPlayed = prefs.getLong("played_${album.id}", 0L)
            if (lastPlayed > 0 && System.currentTimeMillis() - lastPlayed < 7 * 24 * 60 * 60 * 1000) {
                holder.artist.setTextColor(0xFF5A8A5A.toInt())
            } else {
                holder.artist.setTextColor(0xFF4A5570.toInt())
            }

            // Favorite state + click
            val isFav = prefs.getBoolean("fav_${album.id}", false)
            holder.favBtn?.text = if (isFav) "\u2605" else "\u2606"
            holder.favBtn?.setTextColor(if (isFav) 0xFFFFC107.toInt() else 0xFF4A5570.toInt())
            holder.favBtn?.setOnClickListener {
                val wasFav = prefs.getBoolean("fav_${album.id}", false)
                prefs.edit().putBoolean("fav_${album.id}", !wasFav).apply()
                holder.favBtn.text = if (!wasFav) "\u2605" else "\u2606"
                holder.favBtn.setTextColor(if (!wasFav) 0xFFFFC107.toInt() else 0xFF4A5570.toInt())
            }

            // Fix click and long-click
            holder.card.setOnClickListener { onClick(album) }
            holder.card.setOnLongClickListener { onLongClick(album); true }
        }

        override fun getItemCount() = items.size

        private fun dp2(ctx: Context, v: Int) = (v * ctx.resources.displayMetrics.density).toInt()
    }

    private class VH(
        val card: LinearLayout,
        val cover: ImageView,
        val title: TextView,
        val artist: TextView,
        val meta: TextView,
        val favBtn: TextView? = null
    ) : RecyclerView.ViewHolder(card)
}
