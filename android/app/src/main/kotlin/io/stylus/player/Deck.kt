package io.stylus.player

import kotlin.math.*

/**
 * Deck state machine — SPINUP→CUE→DROP→PLAY, LIFT→BREAK→RETURN→CUE→DROP.
 * Mesma cronologia do desktop: SPINUP 1.1, CUE 1.05, DROP 0.55 (2.7s total).
 * Tambem controla a posicao radial do braço para o renderer.
 */
object VinylConst {
    const val R_OUTER = 1.0f
    const val R_LABEL = 0.329f
    const val R_SPINDLE = 0.024f
    const val RPM = 33.0f + 1.0f / 3.0f
    const val REV_PER_SEC = RPM / 60.0f
    const val SPINUP_T = 1.1f
    const val CUE_T = 1.05f
    const val DROP_T = 0.55f
    const val LIFT_T = 1.3f
    const val RETURN_T = 1.4f
    const val N_RINGS = 96
}

enum class Phase { SPINUP, CUE, DROP, PLAY, LIFT, BREAK, RETURN, STOP }

class Deck {
    var phase: Phase = Phase.SPINUP
        private set
    var t0: Float = 0f
    var rotation: Float = 0f
    var speed: Float = 0f
    var crackle: Float = 0f
    var cueRamp: Float = 0f
    private var wowPhase: Float = 0f  // wow/flutter oscillator phase

    fun elapsed(now: Float) = now - t0
    fun go(p: Phase, now: Float) { phase = p; t0 = now }

    /** A agulha está no sulco? A pergunta é da FASE, e a resposta é uma só.
     *
     *  Ela existia e ninguém a chamava: a VinylActivity escrevia
     *  `deck.phase == Phase.PLAY` em quatro lugares. É a mesma lição que o
     *  ritual do computador já tinha aprendido — duas respostas para a
     *  mesma pergunta é onde elas derivam.
     *
     *  (Havia também um `spinning()`, e esse não era segunda cópia de nada:
     *  não era chamado em lugar nenhum e nada perguntava a mesma coisa por
     *  outro caminho. Saiu.)
     */
    fun stylusDown() = phase == Phase.PLAY

    /** 0.0 = tonearm fully up (off record), 1.0 = fully down (on record) */
    fun armLift(now: Float): Float {
        val e = elapsed(now)
        val raw = when (phase) {
            Phase.SPINUP, Phase.CUE -> 1.0f
            Phase.BREAK, Phase.RETURN, Phase.STOP -> 1.0f
            Phase.DROP -> 1.0f - smootherstep((e / VinylConst.DROP_T).coerceIn(0f, 1f))
            Phase.LIFT -> smootherstep((e / VinylConst.LIFT_T).coerceIn(0f, 1f))
            Phase.PLAY -> 0.0f
        }
        return max(raw, cueRamp)
    }

    /**
     * 0.0 = arm swung over the record (at outer groove radius)
     * 1.0 = arm at rest position (off to the side)
     *
     * During CUE the arm swings IN from rest (1→0).
     * During RETURN the arm swings OUT to rest (0→1).
     * During DROP/PLAY the arm stays over the record (0).
     * During LIFT the arm starts over the record, drifts outward slightly.
     */
    fun armSwing(now: Float): Float {
        val e = elapsed(now)
        return when (phase) {
            Phase.SPINUP -> 1.0f  // still at rest
            Phase.CUE -> {
                // Swings from rest to over the record during CUE
                // Starts swinging after 40% of CUE time (first part is spin-up settling)
                val swingT = (e / VinylConst.CUE_T - 0.4f).coerceIn(0f, 0.6f) / 0.6f
                1.0f - smootherstep(swingT)
            }
            Phase.DROP, Phase.PLAY -> 0.0f  // over the record
            Phase.LIFT -> {
                // During lift: arm starts to drift outward slightly (0 → 0.25)
                // This makes the lift feel like the arm is both lifting AND beginning to swing away
                val liftT = (e / VinylConst.LIFT_T).coerceIn(0f, 1f)
                smootherstep(liftT) * 0.25f
            }
            Phase.BREAK -> 0.25f  // partially drifted outward
            Phase.RETURN -> {
                // Continues outward from 0.25 to 1.0
                val swingT = (e / VinylConst.RETURN_T).coerceIn(0f, 1f)
                0.25f + smootherstep(swingT) * 0.75f
            }
            Phase.STOP -> 1.0f  // at rest
        }
    }

    fun update(dt: Float, now: Float, playing: Boolean): Phase {
        val alvo = if (playing) 0.0f else 1.0f
        cueRamp += (alvo - cueRamp) * min(1.0f, dt * 3.2f)

        when (phase) {
            Phase.SPINUP -> {
                speed += (VinylConst.REV_PER_SEC - speed) * min(1.0f, dt * 2.2f)
                if (elapsed(now) >= VinylConst.SPINUP_T) go(Phase.CUE, now)
            }
            Phase.STOP -> speed *= max(0.0f, 1.0f - dt * 1.1f)
            else -> speed += (VinylConst.REV_PER_SEC - speed) * min(1.0f, dt * 3.0f)
        }
        val e = elapsed(now)
        when {
            phase == Phase.CUE && playing && e >= VinylConst.CUE_T -> go(Phase.DROP, now)
            phase == Phase.DROP && e >= VinylConst.DROP_T -> { crackle = 1.0f; go(Phase.PLAY, now) }
            phase == Phase.LIFT && e >= VinylConst.LIFT_T -> go(Phase.BREAK, now)
            phase == Phase.BREAK && e >= 0.4f -> go(Phase.RETURN, now)
            phase == Phase.RETURN && e >= VinylConst.RETURN_T -> {
                if (playing) go(Phase.CUE, now) else go(Phase.STOP, now)
            }
        }
        rotation = (rotation + speed * dt * 2.0f * PI.toFloat()) % (2.0f * PI.toFloat())
        // Wow/flutter: subtle speed variation that makes the disc feel mechanical
        wowPhase += dt * 0.7f  // slow drift
        val wow = 0.0008f * sin(wowPhase) + 0.0004f * sin(wowPhase * 3.7f)  // two overlapping oscillators
        rotation += wow * dt * speed
        crackle *= max(0.0f, 1.0f - dt * 2.5f)
        return phase
    }

    private fun smootherstep(t: Float): Float {
        val t2 = t * t
        return t2 * t2 * (t * (t * 6f - 15f) + 10f)
    }
}
