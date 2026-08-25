package io.stylus.player

import kotlin.math.*

/**
 * Port of deck/vinyl.py Deck — same SPINUP 1.1, CUE 1.05, DROP 0.55,
 * same arm math, same vinyl.R_* constants, for parity phone↔desktop.
 */
object VinylConst {
    const val R_OUTER = 1.0
    const val R_LEADIN = 0.962
    const val R_PROG_OUT = 0.945
    const val R_PROG_IN = 0.395
    const val R_RUNOUT = 0.36
    const val R_LABEL = 0.329
    const val R_SPINDLE = 0.024
    const val RPM = 33.0 + 1.0/3.0
    const val REV_PER_SEC = RPM / 60.0
    const val SPINUP_T = 1.1
    const val CUE_T = 1.05
    const val DROP_T = 0.55
    const val LIFT_T = 1.0
    const val RETURN_T = 1.4
    const val TRAVEL_T = 1.3
    const val N_RINGS = 96
}

enum class Phase { SPINUP, CUE, DROP, PLAY, LIFT, BREAK, RETURN, STOP }

class Deck {
    var phase = Phase.SPINUP
    var t0 = System.nanoTime() / 1e9
    var rotation = 0.0
    var speed = 0.0
    var crackle = 0.0
    var cueRamp = 0.0

    fun elapsed() = System.nanoTime()/1e9 - t0
    fun go(p: Phase) { phase = p; t0 = System.nanoTime()/1e9 }

    fun spinning() = phase != Phase.STOP
    fun stylusDown() = phase == Phase.PLAY

    fun update(dt: Double, playing: Boolean): Phase {
        val e0 = elapsed()
        val alvo = if (playing) 0.0 else 1.0
        cueRamp += (alvo - cueRamp) * min(1.0, dt * 3.2)
        when (phase) {
            Phase.SPINUP -> {
                speed += (VinylConst.REV_PER_SEC - speed) * min(1.0, dt*2.2)
                if (e0 >= VinylConst.SPINUP_T) go(Phase.CUE)
            }
            Phase.STOP -> speed *= max(0.0, 1.0 - dt*1.1)
            else -> speed += (VinylConst.REV_PER_SEC - speed) * min(1.0, dt*3.0)
        }
        val e = elapsed()
        when {
            phase == Phase.CUE && e >= VinylConst.CUE_T -> go(Phase.DROP)
            phase == Phase.DROP && e >= VinylConst.DROP_T -> { crackle = 1.0; go(Phase.PLAY) }
            phase == Phase.LIFT && e >= VinylConst.LIFT_T -> go(Phase.BREAK) // afterLift handled by caller
            phase == Phase.RETURN && e >= VinylConst.RETURN_T -> go(Phase.CUE)
        }
        rotation = (rotation + speed * dt * 2*PI) % (2*PI)
        crackle *= max(0.0, 1.0 - dt*2.5)
        return phase
    }

    fun armLift(): Double {
        val e = elapsed()
        return when (phase) {
            Phase.SPINUP, Phase.CUE, Phase.BREAK, Phase.RETURN, Phase.STOP -> 1.0
            Phase.DROP -> max(0.0, 1.0 - ease(min(1.0, e / VinylConst.DROP_T)))
            Phase.LIFT -> ease(min(1.0, e / VinylConst.LIFT_T))
            else -> 0.0
        }.let { max(it, cueRamp) }
    }

    private fun ease(t: Double) = t*t*t*(t*(t*6-15)+10) // smootherstep
}
