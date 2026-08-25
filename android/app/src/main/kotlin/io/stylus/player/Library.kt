package io.stylus.player

import java.io.File
import java.util.concurrent.ConcurrentHashMap

/**
 * Port of deck/vinyl.py: shelf, track_paths, library_roots + webdav.
 * Subfolders (Disc 01/Disc 02, Genre/Artist/Album) até 4 níveis, mesma
 * ordem que o desktop para o índice do braço não quebrar.
 */
object Library {
    private val AUDIO_EXT = setOf(".flac",".mp3",".ogg",".opus",".m4a",".wav",".aac",".wma")
    private val DATED = Regex("^\\d{4}-\\d{2}-\\d{2}.*")

    fun isAudio(f: File) = AUDIO_EXT.any { f.name.lowercase().endsWith(it) }

    fun trackSortKey(name: String): String {
        // "01 - Title" -> "Title" para ordenar, mas mantém estável
        return name.replace(Regex("^\\s*\\d+\\s*[-._)]\\s*"), "").lowercase()
    }

    /** Recursivo até 4, como vinyl._collect_audio_recursive */
    fun collectAudio(folder: File, maxDepth: Int = 4): List<File> {
        if (!folder.isDirectory) return emptyList()
        val out = mutableListOf<File>()
        val stack = ArrayDeque<Pair<File,Int>>()
        stack.add(folder to 0)
        while (stack.isNotEmpty()) {
            val (cur, depth) = stack.removeLast()
            if (depth > maxDepth) continue
            val entries = cur.listFiles()?.sortedBy { it.name.lowercase() } ?: continue
            for (e in entries) {
                if (e.isFile && isAudio(e)) out.add(e)
            }
            if (depth == maxDepth) continue
            for (e in entries.reversed()) {
                if (e.isDirectory && !DATED.matches(e.name) && !e.name.startsWith(".")) {
                    stack.add(e to depth+1)
                }
            }
        }
        return out.sortedWith(compareBy(
            { it.relativeTo(folder).path.lowercase() },
            { trackSortKey(it.name) }
        )).distinctBy { it.canonicalPath }
    }

    fun trackPaths(folder: File): List<File> {
        val direct = folder.listFiles()
            ?.filter { it.isFile && isAudio(it) }
            ?.sortedBy { trackSortKey(it.name) } ?: emptyList()
        val rec = collectAudio(folder)
        if (rec.size == direct.size && rec.toSet() == direct.toSet()) return direct
        return if (rec.size > direct.size) rec else direct.ifEmpty { rec }
    }

    fun hasAudio(folder: File, minTracks: Int = 6): Boolean {
        if (collectAudio(folder).size >= minTracks) return true
        return false
    }

    /** Uma estante pode ser local (SAF tree) ou WebDAV virtual. */
    fun shelf(roots: List<File>, minTracks: Int = 6): List<File> {
        val out = mutableListOf<File>()
        for (root in roots) {
            if (!root.isDirectory) continue
            val tops = root.listFiles()?.filter { it.isDirectory }?.sortedBy { it.name } ?: continue
            for (t in tops) {
                if (hasAudio(t, minTracks)) { out.add(t); continue }
                // tenta t como artista → álbuns dentro
                val kids = t.listFiles()?.filter { it.isDirectory }?.sortedBy { it.name } ?: continue
                for (k in kids) {
                    if (hasAudio(k, minTracks)) out.add(k)
                    else {
                        // um nível mais fundo para webdav bagunçado
                        k.listFiles()?.filter { it.isDirectory }?.forEach { k2 ->
                            if (hasAudio(k2, minTracks)) out.add(k2)
                        }
                    }
                }
                // também tenta t ele mesmo ser álbum flat (root/álbum)
                if (t.listFiles()?.any { it.isFile && isAudio(it) } == true) {
                    // já tratado acima como hasAudio(t)
                }
            }
            // flat: root é o próprio álbum (subpastas diretas)
            if (hasAudio(root, minTracks)) out.add(root)
        }
        return out.distinctBy { it.canonicalPath }.sortedBy { it.name.lowercase() }
    }

    /** WebDAV via OkHttp — espelha vinyl.library_roots + rclone config */
    class WebDavRoot(val baseUrl: String, val user: String?, val pass: String?) {
        // PROPFIND → lista, GET streaming com range, cache 64MiB como desktop
        // Implementado em OkHttp + DocumentFile; aqui só stub da interface.
        fun list(path: String): List<String> = emptyList() // TODO PROPFIND
    }
}
