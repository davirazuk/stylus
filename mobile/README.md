# O lado do celular

O STYLUS fala com o celular por `adb` — cabo ou wifi — e isso funciona sem
instalar nada lá. O que está aqui é o **opcional**: um agente para o Termux
que melhora duas coisas específicas.

## O que o agente resolve

**1. Sincronizar sem `adb`.** O `adb push` é lento para milhares de arquivos
pequenos porque cada transferência é um round-trip. Com um `sshd` no Termux,
o PC usa `rsync`, que compara e transfere em lote — e continua de onde parou
se a conexão cair.

**2. O que você ouviu no celular.** Metade da escuta acontece longe do PC, e
sem isso a memória da coleção é míope: o desgaste desenhado nos discos e a
contagem de "quantas vezes" só sabem de uma das metades.

## O que ele NÃO resolve, e por quê

Ler o que está tocando exige acesso à sessão de mídia do Android, que o
Termux não tem sem privilégio de sistema. Então o registro de escuta depende
do seu tocador exportar alguma coisa — o Pano Scrobbler exporta, e o agente
sabe ler o formato dele. Se o seu tocador não exporta nada, essa metade
simplesmente não funciona, e é melhor dizer isso do que fingir.

## Instalar

No Termux, no celular:

```sh
pkg install openssh rsync termux-api
curl -fsSL https://raw.githubusercontent.com/davirazuk/stylus/main/mobile/stylus-agent.sh -o stylus-agent.sh
sh stylus-agent.sh install
```

Depois, no PC: `stylus phone wifi` descobre o endereço e guarda.
