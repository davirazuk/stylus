# The `stylus` command — one entry point to everything the system adds.

function stylus --description 'STYLUS control command'
    set -l green (set_color 00a86b)
    set -l light (set_color 7ed957)
    set -l dim   (set_color 6c8f80)
    set -l reset (set_color normal)

    switch "$argv[1]"
        case apps software loja
            stylus-software $argv[2..-1]
        case launcher menu
            stylus-ui $argv[2..-1]
        case escola moodle
            stylus-ui --category escola-online
        case jogos games
            stylus-ui --category jogos
        case tema theme
        case instalar install
            sudo install-stylus $argv[2..-1]
        case atalhos keys teclas
            less -R /usr/share/stylus/keybindings.txt
        case update atualizar
            stylus-update $argv[2..-1]
        case aur yay
            install-yay
        case info
            fastfetch
        case '' help ajuda -h --help
            echo ''
            echo -s $green '  STYLUS' $reset ' — comandos'
            echo ''
            echo -s '   ' $light 'stylus apps      ' $reset $dim 'instalar programas, jogos e drivers' $reset
            echo -s '   ' $light 'stylus launcher  ' $reset $dim 'abrir o launcher em tela cheia' $reset
            echo -s '   ' $light 'stylus escola    ' $reset $dim 'Moodle e sistemas do IFMS' $reset
            echo -s '   ' $light 'stylus jogos     ' $reset $dim 'seção de jogos do launcher' $reset
            echo -s '   ' $light 'stylus tema      ' $reset $dim 'alternar tema (ifms | mocha)' $reset
            echo -s '   ' $light 'stylus instalar  ' $reset $dim 'instalar o STYLUS no computador' $reset
            echo -s '   ' $light 'stylus atalhos   ' $reset $dim 'lista de atalhos de teclado' $reset
            echo -s '   ' $light 'stylus update    ' $reset $dim 'atualizar o sistema e o próprio STYLUS' $reset
            echo -s '   ' $light 'stylus aur       ' $reset $dim 'habilitar o AUR (instala o yay)' $reset
            echo -s '   ' $light 'stylus info      ' $reset $dim 'informações do sistema' $reset
            echo ''
        case '*'
            echo "stylus: comando desconhecido '$argv[1]' — tente 'stylus help'" >&2
            return 1
    end
end
