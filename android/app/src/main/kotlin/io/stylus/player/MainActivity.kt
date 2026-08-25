package io.stylus.player

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import java.io.File

/**
 * Launcher — shelf + AGORA + vinyl. Port of ui/app.py.
 * - Shelf: grid of discs from Library.shelf (local + webdav, subfolders)
 * - AGORA: now-playing + progress groove + lyrics window
 * - Deck: VinylActivity --view (observe) vs ceremony (new disc)
 */
class MainActivity : AppCompatActivity() {

    private lateinit var player: BitPerfectPlayer
    private val deck = Deck()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // setContentView(R.layout.activity_main) // shelf grid + rail
        player = BitPerfectPlayer(this)

        // Shelf click → put_on (new disc, ceremony)
        // App.put_on already uses stylus-deck --no-scope on desktop;
        // here we do BitPerfectPlayer.playAlbum with pause for ceremony.
        // Library.shelf handles webdav + subfolders (Disc 01 etc)
    }

    fun putOn(folder: File) {
        val files = Library.trackPaths(folder).map { it.path }
        // ceremony: start paused, vinyl does SPINUP 1.1→CUE 1.05→DROP 0.55 then play
        player.playAlbum(files, 0, 0)
        // VinylActivity launched with ceremony (not VIEW)
        startActivity(VinylActivity.ceremonyIntent(this, folder.path))
    }

    fun openDeck() {
        // view-only: don't restart, just observe current ExoPlayer
        // like desktop stylus-deck --view / ritual --view
        startActivity(VinylActivity.viewIntent(this))
    }

    override fun onDestroy() {
        super.onDestroy()
        // closing launcher doesn't kill player — Service keeps music
        // like desktop setsid mpv detached
    }
}
