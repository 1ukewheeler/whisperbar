#!/bin/bash
# Regenerates the synthetic test audio using macOS's built-in `say` (no
# microphone/human needed), converted to 16kHz mono WAV via ffmpeg.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

declare -A PHRASES=(
    [testing123]="Testing one two three, my PIN is one two three four"
    [numbers]="Call me at five five five, one two three, four five six seven"
    [short]="Testing"
)

for name in "${!PHRASES[@]}"; do
    say -o "${name}.aiff" "${PHRASES[$name]}"
    ffmpeg -y -i "${name}.aiff" -ar 16000 -ac 1 -f wav "${name}.wav" -loglevel error
    rm "${name}.aiff"
done

echo "Generated: $(ls *.wav)"
