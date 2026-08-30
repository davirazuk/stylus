package io.stylus.player

/**
 * Os LADOS de um disco — e o gesto que cada um pede.
 *
 * Isto é a tese do sistema, do lado do celular: um disco não é uma fila de
 * músicas, é um objeto com dois lados, e no meio dele você levanta e vira.
 * Estava pela metade aqui: o corte em lados existia (o raio da agulha já
 * andava lado a lado) e o ACONTECIMENTO não — a música passava de um lado
 * para o outro sozinha, em silêncio, que é exatamente o que um tocador
 * digital faz e o que este sistema existe para não fazer.
 *
 * A regra é a mesma do computador, e tem que continuar sendo: o
 * `vinyl.Album._build_sides` e o `gesto_do_lado` do `deck/vinyl.py`. O
 * `tools/check.sh` traduz este arquivo de volta para Python e compara os dois
 * em centenas de formas de disco — nada neste repositório compila o app, e
 * "parece certo" não é prova.
 */
object Lados {

    /** O teto FÍSICO de um lado. 26 min: o lado A de Abbey Road tem 23min30. */
    const val SIDE_MAX_MS = 26L * 60L * 1000L

    data class Lado(val start: Long, val end: Long, val rotulo: String)

    /** Quantos DISCOS: o objeto é o disco, e ele tem dois lados sempre. */
    fun discos(nLados: Int): Int = maxOf(1, (nLados + 1) / 2)

    /** "LADO A", "LADO B"… — o vocabulário do sistema. */
    fun rotulo(i: Int): String = "LADO " + ('A' + i)

    /**
     * "vire o disco para o LADO B" / "ponha o DISCO 2, LADO C".
     *
     * A pergunta certa não é "este é o último lado?", é "que gesto o objeto
     * pede agora?" — e o objeto responde pelo índice: lado ÍMPAR é o verso do
     * que já está no prato (vire), lado PAR é o começo de outro disco
     * (troque). Num LP de dois lados as duas perguntas acertam por acidente;
     * num duplo, a errada erra em dois dos três casos.
     */
    fun gesto(i: Int, nLados: Int): String {
        val rot = rotulo(i)
        if (i % 2 == 1) return "vire o disco para o $rot"
        if (i > 0 && discos(nLados) > 1) return "ponha o DISCO ${i / 2 + 1}, $rot"
        return "agora o $rot"
    }

    /** Em que lado cai este instante (em ms desde o começo do disco). */
    fun indiceEm(lados: List<Lado>, posMs: Long): Int {
        for (i in lados.indices) if (posMs < lados[i].end) return i
        return maxOf(0, lados.size - 1)
    }

    /**
     * Reparte a ordem do disco em lados, sempre em fronteira de faixa.
     *
     * Um lado nunca corta uma música ao meio — foi essa restrição que decidiu
     * a ordem de todo álbum já prensado em vinil.
     */
    fun repartir(durs: List<Long>): List<Lado> {
        var total = 0L
        for (d in durs) total += d
        if (total <= 0L) return listOf(Lado(0L, 1L, rotulo(0)))

        // O número de DISCOS é que se arredonda, não o de lados: não existe
        // disco de três lados. 45 min = 1 disco (2 lados); 90 min = 2 discos
        // (4 lados). A exceção é o que cabe INTEIRO num lado.
        var nSides = if (total <= SIDE_MAX_MS) 1
                     else 2 * (((total + 2L * SIDE_MAX_MS - 1L) / (2L * SIDE_MAX_MS)).toInt())

        var sides = cortar(durs, total, nSides)
        var tries = 0
        while (tries < 3 && sides.size > 1 && sides.size % 2 == 1) {
            nSides = sides.size + 1
            sides = cortar(durs, total, nSides)
            tries++
        }
        if (sides.isEmpty()) sides = mutableListOf(0L to maxOf(1L, total))
        return sides.mapIndexed { i, p -> Lado(p.first, p.second, rotulo(i)) }
    }

    /** Um corte em `nSides` lados. Pode devolver mais: o teto é físico. */
    private fun cortar(
        durs: List<Long>, total: Long, nSides: Int
    ): MutableList<Pair<Long, Long>> {
        val sides = mutableListOf<Pair<Long, Long>>()
        var curStart = 0L
        var curCount = 0
        var start = 0L
        for (i in durs.indices) {
            val end = start + durs[i]
            // 1. o teto, que é físico: fecha ANTES de pôr a faixa que
            //    estoura. Um lado vazio nunca fecha — não se corta uma
            //    música ao meio.
            if (curCount > 0 && end - curStart > SIDE_MAX_MS) {
                sides.add(curStart to start)
                curStart = start
                curCount = 0
            }
            curCount++
            // 2. o equilíbrio, com o alvo vindo do que RESTA.
            val faltam = maxOf(1, nSides - sides.size)
            val alvo = curStart + (total - curStart) / faltam
            if (faltam > 1 && end >= alvo && (durs.size - i - 1) >= (faltam - 1)) {
                sides.add(curStart to end)
                curStart = end
                curCount = 0
            }
            start = end
        }
        if (curCount > 0) sides.add(curStart to total)
        return sides
    }
}
