package io.stylus.player

import android.Manifest
import android.content.ContentResolver
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
    private var albums = listOf<Library.Album>()

    companion object {
        private const val PERM_REQ = 100
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
        window.statusBarColor = 0xFF07080B.toInt()
        window.navigationBarColor = 0xFF07080B.toInt()

        val root = FrameLayout(this).apply { setBackgroundColor(0xFF07080B.toInt()) }

        // Header
        val header = TextView(this).apply {
            text = "STYLUS"
            setTextColor(0xFF8892B0.toInt())
            textSize = 11f
            letterSpacing = 0.18f
            typeface = Typeface.DEFAULT_BOLD
            setPadding(dp(20), dp(52), dp(20), dp(4))
        }
        root.addView(header, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ))

        // Grid
        recycler = RecyclerView(this).apply {
            layoutManager = GridLayoutManager(this@MainActivity, calcCols())
            setPadding(dp(14), dp(88), dp(14), dp(14))
            clipToPadding = false
        }
        root.addView(recycler, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
        ))

        // Empty state
        emptyView = TextView(this).apply {
            text = "Nenhuma música encontrada"
            setTextColor(0xFF5A6480.toInt())
            textSize = 15f
            visibility = View.GONE
            gravity = Gravity.CENTER
        }
        root.addView(emptyView, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT
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
            emptyView.text = "Sem permissão de leitura"
            emptyView.visibility = View.VISIBLE
        }
    }

    private fun loadAlbums() {
        albums = Library.albums(this)
        if (albums.isEmpty()) {
            emptyView.visibility = View.VISIBLE
        } else {
            emptyView.visibility = View.GONE
            recycler.adapter = AlbumAdapter(albums, contentResolver) { album ->
                startActivity(VinylActivity.ceremonyIntent(this, album.id))
            }
        }
    }

    private class AlbumAdapter(
        private val items: List<Library.Album>,
        private val resolver: ContentResolver,
        private val onClick: (Library.Album) -> Unit
    ) : RecyclerView.Adapter<AlbumVH>() {
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): AlbumVH {
            val view = LayoutInflater.from(parent.context).inflate(R.layout.item_album, parent, false)
            return AlbumVH(view)
        }
        override fun onBindViewHolder(holder: AlbumVH, position: Int) = holder.bind(items[position], resolver, onClick)
        override fun getItemCount() = items.size
    }

    private class AlbumVH(view: View) : RecyclerView.ViewHolder(view) {
        private val cover: ImageView = view.findViewById(R.id.cover)
        private val title: TextView = view.findViewById(R.id.title)
        private val artist: TextView = view.findViewById(R.id.artist)

        fun bind(album: Library.Album, resolver: ContentResolver, onClick: (Library.Album) -> Unit) {
            title.text = album.name
            artist.text = album.artist
            cover.setImageBitmap(null)
            cover.setBackgroundColor(0xFF0E1018.toInt())
            try {
                resolver.openInputStream(album.coverUri())?.use { stream ->
                    val bmp = BitmapFactory.decodeStream(stream)
                    if (bmp != null) cover.setImageBitmap(bmp)
                }
            } catch (_: Exception) {}
            itemView.setOnClickListener { onClick(album) }
        }
    }
}
