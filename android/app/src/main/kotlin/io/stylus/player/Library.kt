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

    /** Por áudio em pasta (fallback para WebDAV ou storage local via SAF) */
    fun tracksFromFolder(folder: java.io.File): List<java.io.File> {
        if (!folder.isDirectory) return emptyList()
        return folder.walkTopDown()
            .maxDepth(4)
            .filter { it.isFile && AUDIO_EXT.any { ext -> it.name.lowercase().endsWith(ext) } }
            .sortedWith(compareBy({ it.parent?.lowercase() ?: "" }, { trackSortKey(it.name) }))
            .distinctBy { it.canonicalPath }
            .toList()
    }
}
