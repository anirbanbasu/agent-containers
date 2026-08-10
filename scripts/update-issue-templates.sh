#!/usr/bin/env bash
# Regenerates the "Component" dropdown options in .github/ISSUE_TEMPLATE/*.yml
# from the current set of agent-images/* directories (excluding "shared").
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
images_dir="$repo_root/agent-images"
template_dir="$repo_root/.github/ISSUE_TEMPLATE"

images=()
for d in "$images_dir"/*/; do
  name="$(basename "$d")"
  [[ "$name" == "shared" ]] && continue
  images+=("$name")
done

IFS=$'\n' images=($(sort <<<"${images[*]}")); unset IFS

options=("${images[@]}" "shared (egress-allowlist.sh)" "docs/build tooling" "other")

for f in "$template_dir/bug_report.yml" "$template_dir/feature_request.yml" "$template_dir/documentation.yml"; do
  tmp="$f.tmp"
  : > "$tmp"
  skip=0
  while IFS= read -r line; do
    if [[ "$line" == *"# BEGIN component-options"* ]]; then
      printf '%s\n' "$line" >> "$tmp"
      for opt in "${options[@]}"; do
        printf '        - %s\n' "$opt" >> "$tmp"
      done
      skip=1
      continue
    fi
    if [[ "$line" == *"# END component-options"* ]]; then
      skip=0
    fi
    if [[ "$skip" -eq 1 ]]; then
      continue
    fi
    printf '%s\n' "$line" >> "$tmp"
  done < "$f"
  mv "$tmp" "$f"
done
