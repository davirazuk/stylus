package io.stylus.player

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View
import android.view.animation.LinearInterpolator
import kotlin.math.sin
import kotlin.random.Random

/**
 * Floating amber dust particles — atmospheric depth on the library screen.
 * Matches the PC's T.Particles class. Points drift upward, fading in/out.
 */
class AmbientParticles(context: Context) : View(context) {

    private data class Particle(
        var x: Float,
        var y: Float,
        var radius: Float,
        var speed: Float,
        var alpha: Float,
        var maxAlpha: Float,
        var phase: Float,
        var drift: Float
    )

    private val particles = mutableListOf<Particle>()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(240, 160, 48)  // amber
        style = Paint.Style.FILL
    }
    private val rng = Random(System.nanoTime())
    private var time = 0f

    private val animator = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 16L  // ~60fps
        repeatCount = ValueAnimator.INFINITE
        interpolator = LinearInterpolator()
        addUpdateListener {
            time += 0.016f
            updateParticles()
            invalidate()
        }
    }

    init {
        // Create 18 particles
        for (i in 0 until 18) {
            particles.add(Particle(
                x = rng.nextFloat(),
                y = rng.nextFloat(),
                radius = 1.5f + rng.nextFloat() * 3f,
                speed = 0.003f + rng.nextFloat() * 0.005f,
                alpha = 0f,
                maxAlpha = 30f + rng.nextFloat() * 40f,
                phase = rng.nextFloat() * 6.28f,
                drift = (rng.nextFloat() - 0.5f) * 0.002f
            ))
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        animator.start()
    }

    override fun onDetachedFromWindow() {
        super.onDetachedFromWindow()
        animator.cancel()
    }

    private fun updateParticles() {
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0 || h <= 0) return

        for (p in particles) {
            // Drift upward
            p.y -= p.speed
            p.x += p.drift + sin(time * 0.7f + p.phase) * 0.0003f

            // Wrap around
            if (p.y < -0.05f) {
                p.y = 1.05f
                p.x = rng.nextFloat()
            }
            if (p.x < -0.05f) p.x = 1.05f
            if (p.x > 1.05f) p.x = -0.05f

            // Fade in/out based on lifecycle
            val life = (1f - p.y)  // 0 at top, 1 at bottom
            p.alpha = when {
                life < 0.1f -> p.maxAlpha * (life / 0.1f)
                life > 0.9f -> p.maxAlpha * ((1f - life) / 0.1f)
                else -> p.maxAlpha
            }
            // Twinkle
            p.alpha *= 0.7f + 0.3f * sin(time * 1.3f + p.phase * 5.3f)
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()

        for (p in particles) {
            if (p.alpha <= 0f) continue
            paint.alpha = p.alpha.toInt()
            canvas.drawCircle(p.x * w, p.y * h, p.radius, paint)
        }
    }
}
