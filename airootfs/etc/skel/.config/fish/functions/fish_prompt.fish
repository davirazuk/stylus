# STYLUS prompt — two lines, so a long path never squeezes what you are typing.
#
#   ╭─ stylus ~/projeto  main ●2 ↑1  ⏱ 1.4s
#   ╰─λ

function fish_prompt --description 'STYLUS prompt'
    set -l last_status $status

    set -l green  (set_color 00a86b)
    set -l light  (set_color 7ed957)
    set -l text   (set_color e8f5e9)
    set -l dim    (set_color 7fa392)
    set -l red    (set_color f38ba8)
    set -l yellow (set_color f9e2af)
    set -l reset  (set_color normal)

    # ── top line ─────────────────────────────────────────────────────────────
    echo -n -s $dim '╭─ ' $reset

    if test (id -u) -eq 0
        echo -n -s $red 'root ' $reset
    else if set -q SSH_CONNECTION
        echo -n -s $yellow (whoami) '@' (prompt_hostname) ' ' $reset
    else
        echo -n -s $light (whoami) ' ' $reset
    end

    echo -n -s $text (prompt_pwd) $reset

    # ── git ──────────────────────────────────────────────────────────────────
    if command -sq git
        set -l branch (command git symbolic-ref --short HEAD 2>/dev/null; or command git rev-parse --short HEAD 2>/dev/null)
        if test -n "$branch"
            echo -n -s $green '  ' $branch $reset

            # number of changed files, if any
            set -l dirty (command git status --porcelain 2>/dev/null | count)
            if test $dirty -gt 0
                echo -n -s $yellow ' ●' $dirty $reset
            end

            # how far ahead of / behind the upstream branch
            set -l counts (command git rev-list --left-right --count HEAD...@{upstream} 2>/dev/null | string split \t)
            if test (count $counts) -eq 2
                test $counts[1] -gt 0; and echo -n -s $light ' ↑' $counts[1] $reset
                test $counts[2] -gt 0; and echo -n -s $red ' ↓' $counts[2] $reset
            end
        end
    end

    # ── background jobs ──────────────────────────────────────────────────────
    set -l jobcount (jobs | count)
    test $jobcount -gt 0; and echo -n -s $dim '  ⚙ ' $jobcount $reset

    # ── how long the last command took, when it was slow enough to care ──────
    if test $CMD_DURATION -gt 2000
        echo -n -s $dim '  ⏱ ' (math -s1 $CMD_DURATION/1000) 's' $reset
    end

    echo

    # ── bottom line ──────────────────────────────────────────────────────────
    echo -n -s $dim '╰─' $reset
    if test $last_status -ne 0
        echo -n -s $red 'λ ' $reset
    else
        echo -n -s $green 'λ ' $reset
    end
end
