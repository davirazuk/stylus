package io.stylus.player

/**
 * O texto que a pessoa lê — as regras que valem nos DOIS lados.
 *
 * A coleção é a mesma no computador e no celular, e o vocabulário também tem
 * que ser: o que lá se chama "disco" não pode se chamar "álbum" aqui, e o
 * plural não pode estar certo de um lado e errado do outro.
 *
 * O irmão deste arquivo é o `model.plural` do lançador (ui/model.py), e a
 * lição é a mesma que custou quinze lugares lá: a regra do plural escrita à
 * mão em cada lugar ("$n faixas") esquece o caso do 1 em todos. "1 albuns",
 * "1 faixas", "1 discos" não derrubam nada e não somem sozinhos — só fazem o
 * sistema parecer traduzido por máquina, e o texto que a pessoa vê é a única
 * parte dele que ela lê inteira.
 */
object Texto {

    /** "1 disco", "2 discos". `muitos` só quando não é só juntar um "s". */
    fun plural(n: Int, um: String, muitos: String = ""): String {
        val outro = if (muitos.isNotEmpty()) muitos else um + "s"
        return "$n ${if (kotlin.math.abs(n) == 1) um else outro}"
    }

    /** "43min", "1h23" — o mesmo formato do `model.humano` do lançador. */
    fun humano(ms: Long): String {
        val seg = (if (ms > 0) ms else 0L) / 1000L
        val h = seg / 3600L
        val m = (seg % 3600L) / 60L
        return if (h > 0) "${h}h${String.format("%02d", m)}" else "${m}min"
    }
}
