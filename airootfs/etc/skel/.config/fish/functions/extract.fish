function extract --description 'Extract any archive, whatever it is'
    if test (count $argv) -eq 0
        echo "uso: extract <arquivo> [arquivo...]" >&2
        return 1
    end
    for file in $argv
        if not test -f "$file"
            echo "extract: não encontrado: $file" >&2
            continue
        end
        switch "$file"
            case '*.tar.bz2' '*.tbz2'; tar xjf "$file"
            case '*.tar.gz' '*.tgz';   tar xzf "$file"
            case '*.tar.xz' '*.txz';   tar xJf "$file"
            case '*.tar.zst';          tar --zstd -xf "$file"
            case '*.tar';              tar xf "$file"
            case '*.bz2';              bunzip2 "$file"
            case '*.gz';               gunzip "$file"
            case '*.zip';              unzip "$file"
            case '*.7z';               7z x "$file"
            case '*.rar';              unrar x "$file"
            case '*.xz';               unxz "$file"
            case '*';                  echo "extract: formato desconhecido: $file" >&2
        end
    end
end
