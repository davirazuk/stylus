package io.stylus.player

import android.content.Context
import android.content.SharedPreferences

/**
 * O que você pôs no celular — para a estante do computador saber.
 *
 * POR QUE ISTO ESCREVE UM ARQUIVO
 * -------------------------------
 * A memória da coleção (quantas vezes, há quanto tempo) mora no
 * `plays.tsv` do computador, e metade da escuta acontece longe dele. O
 * caminho que existia para trazer isso era: instalar o Pano Scrobbler,
 * instalar o Termux, EXPORTAR à mão do Pano para /sdcard, rodar o agente e
 * só então `stylus phone scrobbles`. Cinco passos, e um deles é manual —
 * ou seja, na prática o computador nunca soube o que tocou aqui.
 *
 * Este aplicativo sabe: é ele que põe o disco. Uma linha por colocação, no
 * MESMO formato que o `stylus phone scrobbles` lê (`carimbo, artista,
 * álbum, pasta`), no diretório do próprio app — que o `adb pull` alcança
 * sem root e sem permissão de armazenamento nenhuma.
 *
 * A quarta coluna vai VAZIA de propósito: a pasta é do computador, e é ele
 * quem resolve o par artista/álbum para a pasta dele. (Essa resolução
 * também não existia até pouco tempo atrás; ver o `_resolver` do
 * stylus-phone.)
 */
object PlayTracker {

    // O MESMO do computador: `vinyl.PLAY_COOLDOWN`, dez minutos. O
    // comentário aqui dizia "same as PC" com 30 segundos escritos ao lado —
    // e trinta segundos anotam a mesma colocação de novo a cada faixa curta,
    // inflando a contagem que o `stylus record` usa para achar o disco
    // esquecido. Contagem que mente é pior do que contagem nenhuma.
    private const val COOLDOWN_MS = 600_000L

    private var lastPlayedKey: String = ""
    private var lastPlayedAt: Long = 0L
    private var _appContext: Context? = null

    fun init(ctx: Context) {
        _appContext = ctx.applicationContext
    }

    /**
     * Record a play. Cooldown prevents duplicate entries.
     */
    fun record(album: Library.Album, prefs: SharedPreferences) {
        val now = System.currentTimeMillis()
        val key = "${album.artist}|${album.name}"

        // Cooldown check
        if (key == lastPlayedKey && (now - lastPlayedAt) < COOLDOWN_MS) return

        lastPlayedKey = key
        lastPlayedAt = now

        // Update SharedPreferences for local stats (recently played, play count)
        prefs.edit()
            .putLong("played_${album.id}", now)
            .putInt("playcount_${album.id}", (prefs.getInt("playcount_${album.id}", 0)) + 1)
            .apply()

        anotarParaOComputador(album, now)
    }

    /** O nome do arquivo, e o formato, que o `stylus phone scrobbles` lê. */
    const val ARQUIVO = "stylus-scrobbles.tsv"

    private fun anotarParaOComputador(album: Library.Album, quando: Long) {
        val ctx = _appContext ?: return
        try {
            val dir = ctx.getExternalFilesDir(null) ?: return
            val f = java.io.File(dir, ARQUIVO)
            // Sem crescer para sempre: o computador junta e não apaga nada
            // do lado dele, mas um arquivo de anos aqui é desperdício. Duas
            // mil linhas são anos de escuta.
            if (f.length() > 200_000L) {
                val linhas = f.readLines()
                f.writeText(linhas.takeLast(1000).joinToString("\n") + "\n")
            }
            val artista = album.artist.replace('\t', ' ').replace('\n', ' ')
            val disco = album.name.replace('\t', ' ').replace('\n', ' ')
            // A quarta coluna é a PASTA no computador, que o celular não
            // conhece: fica vazia e o outro lado resolve pelo par
            // artista/álbum.
            f.appendText("${quando / 1000L}\t$artista\t$disco\t\n")
        } catch (_: Exception) {
            // Anotar é um bônus: não pode derrubar quem só quer ouvir.
        }
    }

    fun playCount(albumId: Long, prefs: SharedPreferences): Int =
        prefs.getInt("playcount_$albumId", 0)

    fun lastPlayed(albumId: Long, prefs: SharedPreferences): Long =
        prefs.getLong("played_$albumId", 0L)

    fun wasRecent(albumId: Long, prefs: SharedPreferences, days: Int = 7): Boolean {
        val last = lastPlayed(albumId, prefs)
        return last > 0 && (System.currentTimeMillis() - last) < days * 24 * 60 * 60 * 1000L
    }
}
