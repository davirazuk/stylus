function up --description 'Go up N directories (default 1)'
    set -l levels 1
    test (count $argv) -gt 0; and set levels $argv[1]
    set -l path ""
    for i in (seq $levels)
        set path "$path../"
    end
    cd $path
end
