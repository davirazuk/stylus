package io.stylus.player

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat

/**
 * Foreground service keeps playback alive when app is backgrounded.
 */
class BitPerfectService : Service() {

    companion object {
        private const val CH = "stylus_playback"
        private const val NOTIF_ID = 1001
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            "TOGGLE" -> sendBroadcast(Intent("io.stylus.player.TOGGLE_PLAY"))
        }
        return START_STICKY
    }

    fun showNotification(title: String, playing: Boolean) {
        ensureChannel()
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        val n = NotificationCompat.Builder(this, CH)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle("STYLUS")
            .setContentText(title)
            .setContentIntent(pi)
            .setOngoing(playing)
            .setSilent(true)
            .build()
        startForeground(NOTIF_ID, n)
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
