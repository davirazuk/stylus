package io.stylus.player

import android.content.ContentUris
import android.content.Context
import android.net.Uri
import android.provider.MediaStore

/**
 * Consulta MediaStore para álbuns e faixas — o jeito Android de varrer a coleção.
 * Mantém a MESMA ORDEM que o desktop (ver `trackNumber`) para o índice do
 * braço bater.
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
        val artUri: Uri?,
        val totalDuration: Long = 0L
    ) {
        fun coverUri(): Uri = artUri ?: Uri.parse("content://media/external/audio/albumart/$id")
        fun durationString(): String {
            // Pelo Texto.plural: "1 faixas" é o mesmo defeito que custou
            // quinze lugares no lançador, e aqui estava em dois.
            val faixas = Texto.plural(trackCount, "faixa")
            if (totalDuration <= 0) return faixas
            // Pelo `Texto.humano`, que existe exatamente para isto e não era
            // chamado por ninguém: aqui a duração era montada à mão como
            // "45:30" e no computador o mesmo disco diz "45min". O arquivo
            // Texto.kt diz, na própria docstring, que o vocabulário tem que
            // ser o mesmo dos dois lados — e a primeira coisa que divergiu
            // foi ele.
            return "$faixas \u2022 ${Texto.humano(totalDuration)}"
        }
    }

    // A MESMA lista do `vinyl.AUDIO_EXT` do computador. Esta era a SÉTIMA
    // cópia dela no sistema e discordava das outras: faltavam .wma, .shn e
    // .ape, então uma coleção com rip antigo (Windows Media, Shorten,
    // Monkey's Audio) ficava invisível no celular — e invisível sem erro
    // nenhum, que é o pior jeito de não funcionar. O tools/check.sh confere
    // as duas listas uma contra a outra.
    private val AUDIO_EXT = setOf(".flac", ".mp3", ".ogg", ".opus", ".m4a",
                                  ".wav", ".aac", ".wma", ".shn", ".ape")

    // A ORDEM DO DISCO. Transliteração do `_track_sort_key` do vinyl.py:
    //
    //     m = re.match(r"\s*(\d+)", basename)
    //     return (int(m.group(1)) if m else 10_000, basename.lower())
    //
    // **Sintoma:** isto fazia o CONTRÁRIO. Ele TIRAVA o número da frente e
    // ordenava pelo que sobrava, ou seja, pelo título em ordem alfabética —
    // enquanto o cabeçalho deste arquivo afirma, com todas as letras,
    // "mantém mesma ordem que o desktop para o índice do braço bater".
    //
    // O que se via: OK Computer começando por "Airbag", depois "Climbing Up
    // the Walls", depois "Electioneering"… a ordem do disco desmontada. E
    // como os LADOS são repartidos por tempo acumulado na ordem da lista, o
    // "vire o disco" caía no meio de outra faixa, a agulha apontava para
    // outro sulco e o scrobble anotava outra coisa. Nada disso dá erro.
    //
    // Número primeiro, nome depois — e sem número vai para o fim (10000),
    // que é o mesmo desempate do computador.
    private fun trackNumber(name: String): Int =
        Regex("^\\s*(\\d+)").find(name)?.groupValues?.get(1)?.toIntOrNull() ?: 10_000

    /** Álbuns com pelo menos 1 faixa */
    fun albums(ctx: Context): List<Album> {
        val out = mutableListOf<Album>()
        val cr = ctx.contentResolver

        // Single query: sum durations grouped by album_id
        val durMap = mutableMapOf<Long, Long>()
        try {
            cr.query(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
                arrayOf(MediaStore.Audio.Media.ALBUM_ID, "SUM(${MediaStore.Audio.Media.DURATION}) AS total_dur"),
                "${MediaStore.Audio.Media.IS_MUSIC}=1",
                null,
                MediaStore.Audio.Media.ALBUM_ID)?.use { cur ->
                val iId = cur.getColumnIndexOrThrow(MediaStore.Audio.Media.ALBUM_ID)
                val iDur = cur.getColumnIndexOrThrow("total_dur")
                while (cur.moveToNext()) {
                    durMap[cur.getLong(iId)] = cur.getLong(iDur)
                }
            }
        } catch (_: Exception) {}

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
                    out.add(Album(id, cur.getString(iName), cur.getString(iArtist), count, artUri, durMap[id] ?: 0L))
                }
            }
        }
        return out
    }

    /** Faixas de um álbum, ordenadas por disc number e track number */
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
            MediaStore.Audio.Media.TRACK,
            MediaStore.Audio.Media.DISC_NUMBER,
        )
        cr.query(uri, proj, sel, arrayOf(albumId.toString()), "${MediaStore.Audio.Media.DISC_NUMBER} ASC, ${MediaStore.Audio.Media.TRACK} ASC")?.use { cur ->
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
        return out
    }

    /** Por áudio em pasta — recursivo até 4 níveis, como vinyl._collect_audio_recursive */
    fun tracksFromFolder(folder: java.io.File): List<java.io.File> {
        if (!folder.isDirectory) return emptyList()
        return folder.walkTopDown()
            .maxDepth(4)
            .filter { it.isFile && AUDIO_EXT.any { ext -> it.name.lowercase().endsWith(ext) } }
            .sortedWith(compareBy({ it.parent?.lowercase() ?: "" },
                                  { trackNumber(it.name) },
                                  { it.name.lowercase() }))
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

    /** O .lrc desta faixa, procurado como as coleções de verdade guardam.
     *
     *  Transliteração do `vinyl.find_lrc`. Só se procurava `faixa.lrc` ao
     *  lado do arquivo, com a caixa exata — e um acervo que passou por um
     *  Windows guarda `Faixa.LRC`, e vários programas de sincronia guardam
     *  tudo numa subpasta `Lyrics/`. Metade da coleção "não tinha letra", e
     *  o arquivo estava lá.
     */
    fun findLrc(path: String): java.io.File? {
        val f = java.io.File(path)
        val direto = java.io.File(f.parent, f.nameWithoutExtension + ".lrc")
        if (direto.isFile) return direto
        val querido = f.nameWithoutExtension.lowercase()
        for (sub in listOf("", "Lyrics", "lyrics", "Letras", "letras", ".lyrics")) {
            val d = if (sub.isEmpty()) java.io.File(f.parent ?: ".")
                    else java.io.File(f.parent, sub)
            val achado = d.listFiles()?.firstOrNull {
                it.isFile && it.name.lowercase().endsWith(".lrc") &&
                    it.nameWithoutExtension.lowercase() == querido
            }
            if (achado != null) return achado
        }
        return null
    }

    // O carimbo do começo da linha, e o [offset:±ms]. Os MESMOS dois do
    // `vinyl.parse_lrc` — ver lá o porquê de cada um.
    private val LRC_CARIMBO = Regex("""\[(\d+):(\d{1,2}(?:[.:]\d{1,3})?)\]""")
    private val LRC_OFFSET = Regex("""^\[offset:\s*([+-]?\d+)\s*\]""",
                                   RegexOption.IGNORE_CASE)

    /** Letras sincronizadas, do jeito que o computador lê. Ver vinyl.parse_lrc.
     *
     *  Três coisas faltavam aqui, e as três se veem na tela:
     *
     *  · carimbo REPETIDO (`[00:42][02:15]refrão`, que é como todo refrão é
     *    escrito) casava só o primeiro, e os outros colchetes iam para o
     *    TEXTO — apareciam na tela, e a linha só era cantada uma vez.
     *  · `[offset:±ms]` era ignorado. Meio segundo é o valor mais comum e é
     *    exatamente o que separa a linha certa da errada numa música rápida.
     *    Positivo quer dizer "mostre mais cedo": SUBTRAI do carimbo.
     *  · `[01:23]` sem fração não casava com nada e a linha sumia. O regex
     *    exigia os centésimos.
     */
    fun lyricsFor(trackUri: android.net.Uri, ctx: android.content.Context): List<Pair<Long,String>>? {
        return try {
            val cr = ctx.contentResolver
            val proj = arrayOf(android.provider.MediaStore.Audio.Media.DATA)
            cr.query(trackUri, proj, null, null, null)?.use { cur ->
                if (!cur.moveToFirst()) return null
                val path = cur.getString(0) ?: return null
                val lrc = findLrc(path) ?: return null
                val out = mutableListOf<Pair<Long,String>>()
                var offset = 0L
                lrc.forEachLine { bruta ->
                    val line = bruta.trim()
                    if (line.isEmpty()) return@forEachLine
                    val mo = LRC_OFFSET.find(line)
                    if (mo != null) {
                        offset = mo.groupValues[1].toLongOrNull() ?: 0L
                        return@forEachLine
                    }
                    val carimbos = mutableListOf<Long>()
                    var fim = 0
                    for (m in LRC_CARIMBO.findAll(line)) {
                        if (m.range.first != fim) break   // o texto começou
                        val min = m.groupValues[1].toLong()
                        val ss = m.groupValues[2]
                        val ms = if (ss.contains('.') || ss.contains(':')) {
                            val partes = ss.split('.', ':')
                            val seg = partes[0].toLong()
                            // Centésimos, não milésimos: ".45" são 450 ms.
                            val frac = partes[1].padEnd(3, '0').take(3).toLong()
                            seg * 1000 + frac
                        } else {
                            ss.toLong() * 1000
                        }
                        carimbos.add(min * 60_000 + ms)
                        fim = m.range.last + 1
                    }
                    if (carimbos.isEmpty()) return@forEachLine
                    val corpo = line.substring(fim).trim()
                    for (c in carimbos) out.add(maxOf(0L, c - offset) to corpo)
                }
                out.sortBy { it.first }
                if (out.isEmpty()) null else out
            }
        } catch (_: Exception) { null }
    }

    /** O ÍNDICE da linha que está sendo cantada agora, ou -1 antes da
     *  primeira.
     *
     *  Devolvia o TEXTO e chamava-se `lyricAt` — e ninguém a chamava: a
     *  VinylActivity refazia a conta com um laço linear sobre a letra
     *  inteira a cada tique do relógio, porque o painel precisa do índice
     *  (para saber quais linhas mostrar em volta) e não do texto. Função
     *  escrita, com o nome certo, e uma segunda cópia da mesma decisão ao
     *  lado — que é onde as duas derivam.
     *
     *  A busca binária devolve a primeira linha que ainda NÃO chegou; quem
     *  canta é a anterior. (No computador esse -1 faltava e a tela
     *  destacava o verso seguinte o tempo todo.)
     */
    fun lyricIndexAt(lyrics: List<Pair<Long,String>>, posMs: Long): Int {
        var lo = 0; var hi = lyrics.size
        while (lo < hi) {
            val mid = (lo + hi) / 2
            if (lyrics[mid].first <= posMs) lo = mid + 1 else hi = mid
        }
        return lo - 1
    }

    // (Havia aqui um `webDavAlbums` — um cliente WebDAV com PROPFIND, para
    // o celular ver a coleção do computador pela rede. Escrito inteiro e
    // chamado em lugar nenhum: nenhuma tela pedia, nenhuma configuração
    // apontava para um servidor. O caminho que EXISTE é o contrário — o
    // `stylus webdav` do computador monta o celular na estante de lá — e um
    // cliente que ninguém abre lê como um recurso que existe. Está no
    // histórico do git, que é onde código que ninguém executa mora.)
}
