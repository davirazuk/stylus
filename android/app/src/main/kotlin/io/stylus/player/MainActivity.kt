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
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView

class MainActivity : AppCompatActivity() {

    private lateinit var recycler: RecyclerView
    private lateinit var emptyView: TextView
    private lateinit var bottomText: TextView
    private lateinit var searchInput: android.widget.EditText
    private lateinit var sortBtn: TextView
    private lateinit var dacIndicator: TextView
    private lateinit var prefs: SharedPreferences
    private var allAlbums = listOf<Library.Album>()
    private var filteredAlbums = listOf<Library.Album>()
    private var sortMode = 0 // 0=name, 1=artist, 2=recent

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
        window.statusBarColor = 0xFF07080B.toInt()
        window.navigationBarColor = 0xFF07080B.toInt()

        val root = FrameLayout(this).apply { setBackgroundColor(0xFF07080B.toInt()) }

        // Header row: STYLUS + sort + settings
        val headerRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(dp(20), dp(48), dp(20), dp(4))
            gravity = Gravity.CENTER_VERTICAL
        }
        val header = TextView(this).apply {
            text = "STYLUS"
            setTextColor(0xFF8892B0.toInt())
            textSize = 11f
            letterSpacing = 0.18f
            typeface = Typeface.DEFAULT_BOLD
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        headerRow.addView(header)

        // USB DAC indicator
        dacIndicator = TextView(this).apply {
            text = ""
            setTextColor(0xFF5A8A5A.toInt())
            textSize = 9f
            setPadding(dp(6), dp(2), dp(6), dp(2))
            visibility = View.GONE
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(0x225A8A5A.toInt())
                cornerRadius = dp(6).toFloat()
                setStroke(1, 0x445A8A5A)
            }
        }
        headerRow.addView(dacIndicator)

        // Sort button
        val sortLabels = arrayOf("A-Z", "Artista", "Recente")
        sortBtn = TextView(this).apply {
            text = sortLabels[sortMode]
            setTextColor(0xFF6B7898.toInt())
            textSize = 10f
            setPadding(dp(12), dp(4), dp(4), dp(4))
            setOnClickListener {
                sortMode = (sortMode + 1) % 3
                text = sortLabels[sortMode]
                prefs.edit().putInt("sort_mode", sortMode).apply()
                applyFilter()
            }
        }
        headerRow.addView(sortBtn)

        val menuBtn = TextView(this).apply {
            text = "⋮"
            setTextColor(0xFF6B7898.toInt())
            textSize = 20f
            setPadding(dp(12), dp(4), dp(4), dp(4))
            setOnClickListener { showWebdavDialog() }
        }
        headerRow.addView(menuBtn)
        root.addView(headerRow, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ))

        // Search bar
        val searchContainer = FrameLayout(this).apply {
            setPadding(dp(20), dp(56), dp(20), dp(0))
        }
        searchInput = android.widget.EditText(this).apply {
            hint = "Buscar album ou artista..."
            setTextColor(0xFFD0D8E8.toInt())
            setHintTextColor(0xFF4A5570.toInt())
            textSize = 13f
            setPadding(dp(14), dp(10), dp(14), dp(10))
            isSingleLine = true
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(0xFF0E1018.toInt())
                cornerRadius = dp(10).toFloat()
                setStroke(1, 0xFF1A2030.toInt())
            }
            setCompoundDrawablesRelativeWithIntrinsicBounds(0, 0, android.R.drawable.ic_menu_search, 0)
            compoundDrawablePadding = dp(8)
            addTextChangedListener(object : android.text.TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                    applyFilter()
                }
                override fun afterTextChanged(s: android.text.Editable?) {}
            })
        }
        searchContainer.addView(searchInput, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ))
        root.addView(searchContainer, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(88) })

        // Grid
        recycler = RecyclerView(this).apply {
            layoutManager = GridLayoutManager(this@MainActivity, calcCols())
            setPadding(dp(14), dp(140), dp(14), dp(72))
            clipToPadding = false
        }
        root.addView(recycler, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
        ))

        // Empty state
        emptyView = TextView(this).apply {
            text = "Nenhuma musica encontrada"
            setTextColor(0xFF5A6480.toInt())
            textSize = 15f
            visibility = View.GONE
            gravity = Gravity.CENTER
        }
        root.addView(emptyView, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
        ))

        // Bottom bar: album count + shuffle + play
        val bottomBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(0xFF141824.toInt())
            setPadding(dp(16), dp(10), dp(16), dp(10))
            gravity = Gravity.CENTER_VERTICAL
            elevation = dp(8).toFloat()
        }
        bottomText = TextView(this).apply {
            text = "${allAlbums.size} albuns"
            setTextColor(0xFF8A94B0.toInt())
            textSize = 12f
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        bottomBar.addView(bottomText)

        // Shuffle button
        val shuffleBtn = TextView(this).apply {
            text = "\u21C4"  // shuffle symbol
            setTextColor(0xFF6B7898.toInt())
            textSize = 16f
            setPadding(dp(8), dp(4), dp(12), dp(4))
            setOnClickListener {
                if (filteredAlbums.isNotEmpty()) {
                    val shuffled = filteredAlbums.shuffled()
                    val intent = VinylActivity.ceremonyIntent(this@MainActivity, shuffled[0].id)
                    intent.putExtra("shuffle", true)
                    startActivity(intent)
                }
            }
        }
        bottomBar.addView(shuffleBtn)

        // Play button
        val playBtn = TextView(this).apply {
            text = "\u25B6"
            setTextColor(0xFFE8ECF5.toInt())
            textSize = 18f
            setPadding(dp(12), dp(4), dp(12), dp(4))
            setOnClickListener {
                if (filteredAlbums.isNotEmpty()) {
                    startActivity(VinylActivity.ceremonyIntent(this@MainActivity, filteredAlbums[0].id))
                }
            }
        }
        bottomBar.addView(playBtn)
        root.addView(bottomBar, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM
        ))

        setContentView(root)
        if (hasPermission()) loadAlbums() else requestPermission()
    }

    private fun calcCols(): Int {
        val px = resources.displayMetrics.widthPixels
        return (px / dp(160)).coerceIn(2, 5)
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun hasPermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= 33) {
            ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_AUDIO) == PackageManager.PERMISSION_GRANTED
        } else {
            @Suppress("DEPRECATION")
            ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        }
    }

    private fun requestPermission() {
        val perm = if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_AUDIO
        else @Suppress("DEPRECATION") Manifest.permission.READ_EXTERNAL_STORAGE
        ActivityCompat.requestPermissions(this, arrayOf(perm), PERM_REQ)
    }

    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code, permissions, results)
        if (code == PERM_REQ && results.isNotEmpty() && results[0] == PackageManager.PERMISSION_GRANTED) {
            loadAlbums()
        } else if (code == PERM_REQ) {
            emptyView.text = "Sem permissao de leitura"
            emptyView.visibility = View.VISIBLE
        }
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
                    Library.Album(
                        id = 900000L + idx,
                        name = f.name,
                        artist = f.parentFile?.name ?: "Desconhecido",
                        trackCount = Library.tracksFromFolder(f).size,
                        artUri = null
                    )
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
        // Sort
        filteredAlbums = when (sortMode) {
            1 -> filteredAlbums.sortedBy { it.artist.lowercase() }
            2 -> filteredAlbums.recentlyPlayed(prefs)
            else -> filteredAlbums.sortedBy { it.name.lowercase() }
        }

        bottomText.text = when {
            filteredAlbums.isEmpty() -> "Nenhum album"
            query.isNotEmpty() -> "${filteredAlbums.size} resultado${if (filteredAlbums.size != 1) "s" else ""}"
            else -> "${filteredAlbums.size} albuns"
        }
        if (filteredAlbums.isEmpty()) {
            emptyView.text = if (query.isNotEmpty()) "Nada para \"$query\"" else "Nenhuma musica encontrada"
            emptyView.visibility = View.VISIBLE
        } else {
            emptyView.visibility = View.GONE
            recycler.adapter = AlbumAdapter(filteredAlbums, contentResolver, prefs) { album ->
                // Record play for recently played
                prefs.edit().putLong("played_${album.id}", System.currentTimeMillis()).apply()
                startActivity(VinylActivity.ceremonyIntent(this, album.id))
            }
        }
    }

    override fun onResume() {
        super.onResume()
        checkDacStatus()
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
                val rateStr = if (rates != null && rates.isNotEmpty()) {
                    val maxRate = rates.max() / 1000
                    " \u2022 ${maxRate}kHz"
                } else ""
                dacIndicator.text = "DAC: $name$rateStr"
                dacIndicator.visibility = View.VISIBLE
            } else {
                dacIndicator.visibility = View.GONE
            }
        } catch (_: Exception) {
            dacIndicator.visibility = View.GONE
        }
    }

    private fun showWebdavDialog() {
        val cur = prefs.getString("webdav_url", "") ?: ""
        val input = android.widget.EditText(this).apply {
            hint = "https://seu.webdav/exemplo/"
            setText(cur)
            setTextColor(0xFFE8ECF5.toInt())
            setHintTextColor(0xFF6B7898.toInt())
        }
        val pad = dp(20)
        val container = FrameLayout(this).apply {
            setPadding(pad, pad, pad, pad)
            addView(input)
        }
        // Sleep timer option
        val timerOptions = arrayOf("Sem timer", "15 min", "30 min", "60 min", "90 min")
        val timerValues = longArrayOf(0, 15*60*1000, 30*60*1000, 60*60*1000, 90*60*1000)
        val currentTimer = prefs.getLong("sleep_timer", 0)
        val timerIdx = timerValues.indexOf(currentTimer).coerceAtLeast(0)

        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("STYLUS")
            .setItems(arrayOf("WebDAV", "Sleep Timer (atual: ${timerOptions[timerIdx]})")) { _, which ->
                when (which) {
                    0 -> showWebdavInput(input)
                    1 -> showSleepTimerPicker(timerOptions, timerValues)
                }
            }
            .setNegativeButton("Fechar", null)
            .show()
    }

    private fun showWebdavInput(input: android.widget.EditText) {
        val pad = dp(20)
        val container = FrameLayout(this).apply {
            setPadding(pad, pad, pad, pad)
            addView(input)
        }
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("WebDAV")
            .setMessage("URL da colecao remota")
            .setView(container)
            .setPositiveButton("Salvar") { _, _ ->
                prefs.edit().putString("webdav_url", input.text.toString().trim()).apply()
                android.widget.Toast.makeText(this, "WebDAV salvo", android.widget.Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun showSleepTimerPicker(options: Array<String>, values: LongArray) {
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("Sleep Timer")
            .setItems(options) { _, which ->
                val ms = values[which]
                prefs.edit().putLong("sleep_timer", ms).apply()
                if (ms > 0) {
                    android.widget.Toast.makeText(this, "Timer: ${options[which]}", android.widget.Toast.LENGTH_SHORT).show()
                } else {
                    android.widget.Toast.makeText(this, "Timer desligado", android.widget.Toast.LENGTH_SHORT).show()
                }
            }
            .show()
    }

    // Recently played helper
    private fun List<Library.Album>.recentlyPlayed(prefs: SharedPreferences): List<Library.Album> {
        return sortedByDescending { prefs.getLong("played_${it.id}", 0L) }
    }

    private class AlbumAdapter(
        private val items: List<Library.Album>,
        private val resolver: ContentResolver,
        private val prefs: SharedPreferences,
        private val onClick: (Library.Album) -> Unit
    ) : RecyclerView.Adapter<AlbumVH>() {
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): AlbumVH {
            val view = LayoutInflater.from(parent.context).inflate(R.layout.item_album, parent, false)
            return AlbumVH(view)
        }
        override fun onBindViewHolder(holder: AlbumVH, position: Int) = holder.bind(items[position], resolver, prefs, onClick)
        override fun getItemCount() = items.size
    }

    private class AlbumVH(view: View) : RecyclerView.ViewHolder(view) {
        private val cover: ImageView = view.findViewById(R.id.cover)
        private val title: TextView = view.findViewById(R.id.title)
        private val artist: TextView = view.findViewById(R.id.artist)

        fun bind(album: Library.Album, resolver: ContentResolver, prefs: SharedPreferences, onClick: (Library.Album) -> Unit) {
            title.text = album.name
            artist.text = "${album.artist} \u2022 ${album.durationString()}"
            cover.setImageBitmap(null)
            cover.setBackgroundColor(0xFF0E1018.toInt())

            // Set cover aspect ratio (square)
            cover.post {
                val params = cover.layoutParams
                params.height = cover.width  // square
                cover.layoutParams = params
            }

            try {
                resolver.openInputStream(album.coverUri())?.use { stream ->
                    val bmp = BitmapFactory.decodeStream(stream)
                    if (bmp != null) cover.setImageBitmap(bmp)
                }
            } catch (_: Exception) {}

            // Recently played indicator
            val lastPlayed = prefs.getLong("played_${album.id}", 0L)
            if (lastPlayed > 0 && System.currentTimeMillis() - lastPlayed < 7 * 24 * 60 * 60 * 1000) {
                artist.setTextColor(0xFF7A9A5A.toInt())
            } else {
                artist.setTextColor(0xFF586888.toInt())
            }

            // Click handling — explicit on the itemView
            itemView.setOnClickListener { onClick(album) }
            itemView.isClickable = true
            itemView.isFocusable = true
        }
    }
}
