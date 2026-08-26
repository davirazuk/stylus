package io.stylus.player

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.media.session.MediaSession
import android.os.Build
import android.os.IBinder

/**
 * Foreground service keeps playback alive when app is backgrounded.
 * Shows a MediaStyle notification with prev/pause/next actions and session token
 * so Pano Scrobbler can detect the MediaSession.
 */
class BitPerfectService : Service() {

    companion object {
        private const val CH = "stylus_playback"
        private const val NOTIF_ID = 1001
        var instance: BitPerfectService? = null
            private set
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
    }

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            "TOGGLE" -> sendBroadcast(Intent("io.stylus.player.TOGGLE_PLAY"))
        }
        return START_STICKY
    }

    fun showNotification(token: MediaSession.Token, title: String, artist: String, album: String, playing: Boolean, albumUri: android.net.Uri? = null) {
        ensureChannel()
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )

        // Pending intents for prev/pause/next broadcast to activity
        val prevPi = PendingIntent.getBroadcast(this, 1,
            Intent("io.stylus.player.MEDIA_PREV"), PendingIntent.FLAG_IMMUTABLE)
        val togglePi = PendingIntent.getBroadcast(this, 2,
            Intent("io.stylus.player.MEDIA_TOGGLE"), PendingIntent.FLAG_IMMUTABLE)
        val nextPi = PendingIntent.getBroadcast(this, 3,
            Intent("io.stylus.player.MEDIA_NEXT"), PendingIntent.FLAG_IMMUTABLE)

        val builder = Notification.Builder(this, CH)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(title.ifEmpty { "STYLUS" })
            .setContentText(artist)
            .setSubText(album)
            .setContentIntent(pi)
            .setOngoing(playing)
            .setShowWhen(false)
            .addAction(Notification.Action.Builder(null, "Prev", prevPi).build())
            .addAction(Notification.Action.Builder(null,
                if (playing) "Pause" else "Play", togglePi).build())
            .addAction(Notification.Action.Builder(null, "Next", nextPi).build())
            .setStyle(
                Notification.MediaStyle()
                    .setMediaSession(token)
                    .setShowActionsInCompactView(0, 1, 2)
            )

        // Album art in notification
        if (albumUri != null && android.os.Build.VERSION.SDK_INT >= 23) {
            try {
                val bmp = android.graphics.BitmapFactory.decodeStream(contentResolver.openInputStream(albumUri))
                if (bmp != null) {
                    val circBmp = android.graphics.Bitmap.createBitmap(bmp.width, bmp.height, android.graphics.Bitmap.Config.ARGB_8888)
                    val canvas = android.graphics.Canvas(circBmp)
                    val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
                    canvas.drawCircle(bmp.width / 2f, bmp.height / 2f, bmp.width / 2f, paint)
                    paint.xfermode = android.graphics.PorterDuffXfermode(android.graphics.PorterDuff.Mode.SRC_IN)
                    canvas.drawBitmap(bmp, 0f, 0f, paint)
                    builder.setLargeIcon(circBmp)
                }
            } catch (_: Exception) {}
        }

        startForeground(NOTIF_ID, builder.build())
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
            if (nm.getNotificationChannel(CH) == null) {
                nm.createNotificationChannel(
                    NotificationChannel(CH, "STYLUS", NotificationManager.IMPORTANCE_LOW)
                )
            }
        }
    }
}
