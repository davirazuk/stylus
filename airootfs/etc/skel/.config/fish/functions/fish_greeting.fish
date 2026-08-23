# Shown once per interactive shell. fastfetch is the identity of the thing, but
# it is a wall of text in every new terminal, so it only runs in the first shell
# of a session; later terminals get a single line instead.

function fish_greeting --description 'STYLUS greeting'
    set -l green (set_color 00a86b)
    set -l light (set_color 7ed957)
    set -l dim   (set_color 7fa392)
    set -l reset (set_color normal)

    set -l stamp /tmp/.stylus-greeted-(id -u)

    if not test -e $stamp; and type -q fastfetch
        fastfetch
        touch $stamp 2>/dev/null
    else
        echo -s $green '  STYLUS' $reset $dim '  ·  ' $reset \
                $light 'stylus' $reset $dim ' para os comandos, ' $reset \
                $light 'stylus apps' $reset $dim ' para instalar programas' $reset
    end
end
