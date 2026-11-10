# Sourced by the run scripts. `run <label> <command...>` runs the command
# through $CLIFFS_RUNNER, or the command named in a .runner file, when either
# is set: a wrapper that takes a label and then the command, such as a queue
# that holds each run to a memory limit. Without one, the command runs directly.
RUNNER=${CLIFFS_RUNNER:-$(cat .runner 2>/dev/null)}
run() {
  local label=$1; shift
  if [ -n "$RUNNER" ]; then ${=RUNNER} $label "$@"; else "$@"; fi
}
