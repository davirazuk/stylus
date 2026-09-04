/* O que se mede aqui é o que falha em SILÊNCIO.
 *
 * A assinatura do track/getFileUrl e a leitura do JSON não avisam quando
 * estão erradas: a API responde "Invalid Request Signature" ou um campo sai
 * vazio, e na tela isso vira "não deu para baixar" sem dizer por quê. As
 * duas são puras — dependem só de entrada e saída —, então dão para provar
 * aqui, sem rede e sem conta.
 *
 * A ordem alfabética dos parâmetros na assinatura é a armadilha clássica.
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "md5.h"
#include "qobuz.h"

static void t_assinatura(void)
{
    /* Segredo e id de mentira: o que se confere é a FÓRMULA, e ela é
       verificável na mão. */
    char got[33];
    qobuz_assina("segredinho", "12345", 6, 1700000000L, got);

    char esperado[33];
    const char *cru = "trackgetFileUrlformat_id6intentstreamtrack_id123451700000000segredinho";
    md5_hex(cru, strlen(cru), esperado);

    printf("assinatura: %s\n", got);
    assert(strcmp(got, esperado) == 0 &&
           "os parametros vao em ordem alfabetica, colados, e o segredo por ultimo");

    /* Trocar o formato TEM de trocar a assinatura — senão o pedido de FLAC
       vai assinado como MP3 e volta recusado. */
    char mp3[33];
    qobuz_assina("segredinho", "12345", 5, 1700000000L, mp3);
    assert(strcmp(got, mp3) != 0 && "o formato entra na assinatura");

    /* E o timestamp também, senão a assinatura de ontem valeria hoje. */
    char outro[33];
    qobuz_assina("segredinho", "12345", 6, 1700000001L, outro);
    assert(strcmp(got, outro) != 0 && "o timestamp entra na assinatura");
    printf("ok: a assinatura muda com formato e com timestamp\n");
}

static void t_json(void)
{
    /* ESTA É A ESTRUTURA DE VERDADE, na ordem de verdade — copiada de uma
       resposta real, encurtada. Escrever o fixture "como faria sentido"
       esconderia os dois defeitos que só apareceram contra a API:

         - no item de ÁLBUM, o "id" do artista vem ANTES e é número;
           o do álbum vem depois e é string;
         - no item de FAIXA, "performer"."id" e "composer"."id" vêm ANTES
           do "id" da faixa, e os três são números.

       Nem "a primeira ocorrência" nem "a primeira do tipo certo" acertam os
       dois. Só profundidade acerta. */
    const char *alb =
        "{\"maximum_bit_depth\":24,"
        "\"image\":{\"small\":\"https://x/230.jpg\"},"
        "\"artist\":{\"image\":null,\"name\":\"Radiohead\",\"id\":43840},"
        "\"label\":{\"name\":\"XL Recordings\",\"id\":7},"
        "\"id\":\"0634904078164\",\"title\":\"OK Computer\","
        "\"tracks_count\":12,\"hires\":false}";

    char s[128];
    int i = 0;
    assert(qobuz_json_str(alb, "id", s, sizeof s));
    printf("id do album: %s\n", s);
    assert(!strcmp(s, "0634904078164") && "o id do ALBUM, nao o do artista");
    assert(qobuz_json_str(alb, "title", s, sizeof s) && !strcmp(s, "OK Computer"));
    assert(qobuz_json_int(alb, "tracks_count", &i) && i == 12);

    /* O artista sai do subobjeto, e tem de ser ele e não a gravadora. */
    const char *art = strstr(alb, "\"artist\"");
    assert(art && qobuz_json_str(art, "name", s, sizeof s));
    assert(!strcmp(s, "Radiohead") && "o artista, nao a gravadora");

    const char *fx =
        "{\"maximum_bit_depth\":16,"
        "\"performers\":\"RADIOHEAD, MainArtist\","
        "\"audio_info\":{\"replaygain_track_gain\":-9.24},"
        "\"performer\":{\"name\":\"Radiohead\",\"id\":43840},"
        "\"composer\":{\"name\":\"Thom Yorke\",\"id\":115553},"
        "\"isrc\":\"GBAYE9700731\",\"title\":\"Airbag\","
        "\"duration\":288,\"track_number\":1,"
        "\"id\":33978480,\"media_number\":1}";

    assert(qobuz_json_str(fx, "id", s, sizeof s));
    printf("id da faixa: %s\n", s);
    assert(!strcmp(s, "33978480") &&
           "o id da FAIXA, e como texto — no Qobuz ele vem numero");
    assert(qobuz_json_str(fx, "title", s, sizeof s) && !strcmp(s, "Airbag"));
    assert(qobuz_json_int(fx, "track_number", &i) && i == 1);
    assert(qobuz_json_int(fx, "duration", &i) && i == 288);

    /* Chave que não existe não pode devolver lixo do que veio antes. */
    assert(!qobuz_json_str(alb, "nao_existe", s, sizeof s));
    assert(s[0] == '\0');

    /* Chave que existe só DENTRO de um subobjeto não vale para o de fora:
       é exatamente isso que impede de ler o id errado. */
    assert(!qobuz_json_int(alb, "albums_count", &i));

    /* Fuga: aspas escapadas num título não podem cortar a string. */
    const char *e = "{\"title\":\"Rock \\\"n\\\" Roll\",\"x\":1}";
    assert(qobuz_json_str(e, "title", s, sizeof s));
    printf("titulo com fuga: %s\n", s);
    assert(strlen(s) > 6);

    /* Buffer curto corta, não estoura. */
    char curto[6];
    assert(qobuz_json_str(alb, "title", curto, sizeof curto));
    assert(strlen(curto) == 5);

    printf("ok: o extrator pega o campo do NIVEL DE CIMA\n");
}

static void t_tamanhos(void)
{
    /* O aviso de espaço só serve se as ordens de grandeza estiverem certas:
       um disco em FLAC tem de assustar mais que o mesmo em MP3. */
    assert(qobuz_mb_por_faixa(QB_MP3) < qobuz_mb_por_faixa(QB_FLAC));
    assert(qobuz_mb_por_faixa(QB_FLAC) < qobuz_mb_por_faixa(QB_HIRES));
    int disco = 12 * qobuz_mb_por_faixa(QB_FLAC);
    printf("um disco de 12 faixas em FLAC: ~%d MB\n", disco);
    assert(disco > 200 && disco < 500 && "a estimativa tem de ser plausivel");
    printf("ok: as estimativas de tamanho ordenam e sao plausiveis\n");
}

int main(void)
{
    t_assinatura();
    t_json();
    t_tamanhos();
    printf("ok: qobuz\n");
    return 0;
}
