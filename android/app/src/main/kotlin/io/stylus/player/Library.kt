package io.stylus.player

import android.content.ContentUris
import android.content.Context
import android.net.Uri
import android.provider.MediaStore

/**
 * Consulta MediaStore para álbuns e faixas — o jeito Android de varrer a coleção.
 * Mantém mesma ordem que o desktop (trackSortKey) para o índice do braço bater.
 */
object Library {

    data class Track(
        val id: Long,
        val title: String,
        val albumId: Long,
        val album: String,
        val artist: String,
        val duration: Long,
        val uri: Uri
    )

    data class Album(
        val id: Long,
        val name: String,
        val artist: String,
        val trackCount: Int,
        val artUri: Uri?
    ) {
        fun coverUri(): Uri = artUri ?: Uri.parse("content://media/external/audio/albumart/$id")
    }

    private val AUDIO_EXT = setOf(".flac", ".mp3", ".ogg", ".opus", ".m4a", ".wav", ".aac")

    private fun trackSortKey(name: String): String =
        name.replace(Regex("^\\s*\\d+\\s*[-._)]\\s*"), "").lowercase()

    /** Álbuns com pelo menos 1 faixa */
    fun albums(ctx: Context): List<Album> {
        val out = mutableListOf<Album>()
        val cr = ctx.contentResolver
        val uri = MediaStore.Audio.Albums.EXTERNAL_CONTENT_URI
        val proj = arrayOf(
            MediaStore.Audio.Albums._ID,
            MediaStore.Audio.Albums.ALBUM,
            MediaStore.Audio.Albums.ARTIST,
            MediaStore.Audio.Albums.NUMBER_OF_SONGS,
        )
        cr.query(uri, proj, null, null, "${MediaStore.Audio.Albums.ALBUM} ASC")?.use { cur ->
            val iId = cur.getColumnIndexOrThrow(MediaStore.Audio.Albums._ID)
            val iName = cur.getColumnIndexOrThrow(MediaStore.Audio.Albums.ALBUM)
            val iArtist = cur.getColumnIndexOrThrow(MediaStore.Audio.Albums.ARTIST)
            val iCount = cur.getColumnIndexOrThrow(MediaStore.Audio.Albums.NUMBER_OF_SONGS)
            while (cur.moveToNext()) {
                val id = cur.getLong(iId)
                val count = cur.getInt(iCount)
                if (count > 0) {
                    val artUri = ContentUris.withAppendedId(
                        Uri.parse("content://media/external/audio/albumart"), id
                    )
                    out.add(Album(id, cur.getString(iName), cur.getString(iArtist), count, artUri))
                }
            }
        }
        return out
    }

    /** Faixas de um álbum, ordenadas por track number */
    fun albumTracks(ctx: Context, albumId: Long): List<Track> {
        val out = mutableListOf<Track>()
        val cr = ctx.contentResolver
        val uri = MediaStore.Audio.Media.EXTERNAL_CONTENT_URI
        val sel = "${MediaStore.Audio.Media.ALBUM_ID}=? AND ${MediaStore.Audio.Media.IS_MUSIC}=1"
        val proj = arrayOf(
            MediaStore.Audio.Media._ID,
            MediaStore.Audio.Media.TITLE,
            MediaStore.Audio.Media.ALBUM_ID,
            MediaStore.Audio.Media.ALBUM,
            MediaStore.Audio.Media.ARTIST,
            MediaStore.Audio.Media.DURATION,
        )
        cr.query(uri, proj, sel, arrayOf(albumId.toString()), "${MediaStore.Audio.Media.TRACK} ASC")?.use { cur ->
            val iId = cur.getColumnIndexOrThrow(MediaStore.Audio.Media._ID)
            val iTitle = cur.getColumnIndexOrThrow(MediaStore.Audio.Media.TITLE)
            val iAlbumId = cur.getColumnIndexOrThrow(MediaStore.Audio.Media.ALBUM_ID)
            val iAlbum = cur.getColumnIndexOrThrow(MediaStore.Audio.Media.ALBUM)
            val iArtist = cur.getColumnIndexOrThrow(MediaStore.Audio.Media.ARTIST)
            val iDur = cur.getColumnIndexOrThrow(MediaStore.Audio.Media.DURATION)
            while (cur.moveToNext()) {
                val id = cur.getLong(iId)
                val contentUri = ContentUris.withAppendedId(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, id)
                out.add(Track(id, cur.getString(iTitle), cur.getLong(iAlbumId), cur.getString(iAlbum), cur.getString(iArtist), cur.getLong(iDur), contentUri))
            }
        }
        return out.sortedWith(compareBy({ it.uri.toString() }, { trackSortKey(it.title) }))
    }

    /** Por áudio em pasta — recursivo até 4 níveis, como vinyl._collect_audio_recursive */
    fun tracksFromFolder(folder: java.io.File): List<java.io.File> {
        if (!folder.isDirectory) return emptyList()
        return folder.walkTopDown()
            .maxDepth(4)
            .filter { it.isFile && AUDIO_EXT.any { ext -> it.name.lowercase().endsWith(ext) } }
            .sortedWith(compareBy({ it.parent?.lowercase() ?: "" }, { trackSortKey(it.name) }))
            .distinctBy { it.canonicalPath }
            .toList()
    }

    /** Estante por pastas (como vinyl.shelf) — para quando a coleção está em disco/SAF */
    fun shelfByFolders(roots: List<java.io.File>): List<java.io.File> {
        val out = mutableListOf<java.io.File>()
        for (root in roots) {
            if (!root.isDirectory) continue
            val tops = root.listFiles()?.filter { it.isDirectory }?.sortedBy { it.name.lowercase() } ?: continue
            for (t in tops) {
                if (tracksFromFolder(t).size >= 1) { out.add(t); continue }
                val kids = t.listFiles()?.filter { it.isDirectory }?.sortedBy { it.name.lowercase() } ?: continue
                for (k in kids) {
                    if (tracksFromFolder(k).size >= 1) out.add(k)
                    else k.listFiles()?.filter { it.isDirectory }?.forEach { k2 ->
                        if (tracksFromFolder(k2).size >= 1) out.add(k2)
                    }
                }
            }
            if (tracksFromFolder(root).size >= 1) out.add(root)
        }
        return out.distinctBy { it.canonicalPath }.sortedBy { it.name.lowercase() }
    }

    /** Letras — .lrc ao lado da faixa, como vinyl.Album.lyrics_for */
    fun lyricsFor(trackUri: android.net.Uri, ctx: android.content.Context): List<Pair<Long,String>>? {
        return try {
            val cr = ctx.contentResolver
            val proj = arrayOf(android.provider.MediaStore.Audio.Media.DATA)
            cr.query(trackUri, proj, null, null, null)?.use { cur ->
                if (!cur.moveToFirst()) return null
                val path = cur.getString(0) ?: return null
                val lrc = java.io.File(path).let { f ->
                    java.io.File(f.parent, f.nameWithoutExtension + ".lrc")
                }
                if (!lrc.isFile) return null
                val out = mutableListOf<Pair<Long,String>>()
                lrc.forEachLine { line ->
                    val m = Regex("""\[(\d+):(\d+)[.:](\d+)\](.*)""").find(line) ?: return@forEachLine
                    val min = m.groupValues[1].toLong()
                    val sec = m.groupValues[2].toLong()
                    val cs = m.groupValues[3].padEnd(3,'0').take(3).toLong()
                    val ms = min*60*1000 + sec*1000 + cs
                    out.add(ms to m.groupValues[4].trim())
                }
                out.sortBy { it.first }
                if (out.isEmpty()) null else out
            }
        } catch (_: Exception) { null }
    }

    fun lyricAt(lyrics: List<Pair<Long,String>>, posMs: Long): String? {
        var lo = 0; var hi = lyrics.size
        while (lo < hi) {
            val mid = (lo+hi)/2
            if (lyrics[mid].first <= posMs) lo = mid+1 else hi = mid
        }
        return if (lo==0) null else lyrics[lo-1].second.takeIf { it.isNotBlank() }
    }

    /** WebDAV simples — lista pastas via PROPFIND, como rclone */
    data class WebDavConfig(val url: String, val user: String?, val pass: String?)
    fun webDavAlbums(cfg: WebDavConfig, onResult: (List<String>) -> Unit) {
        Thread {
            try {
                val client = okhttp3.OkHttpClient.Builder().build()
                val req = okhttp3.Request.Builder().url(cfg.url).method("PROPFIND", null)
                    .header("Depth", "1")
                    .apply {
                        if (!cfg.user.isNullOrEmpty()) {
                            val cred = okhttp3.Credentials.basic(cfg.user, cfg.pass ?: "")
                            header("Authorization", cred)
                        }
                    }.build()
                val resp = client.newCall(req).execute()
                val body = resp.body?.string() ?: ""
                val hrefs = Regex("<D:href>(.*?)</D:href>").findAll(body)
                    .map { it.groupValues[1] }.toList()
                onResult(hrefs)
            } catch (_: Exception) { onResult(emptyList()) }
        }.start()
    }
}
