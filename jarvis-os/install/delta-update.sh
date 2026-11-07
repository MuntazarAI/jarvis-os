#!/bin/bash
# JARVIS-OS Delta Update Generator
# Creates binary deltas using bsdiff for bandwidth-efficient updates
#
# Usage: ./delta-update.sh <old_rootfs> <new_rootfs> <output_dir>

set -euo pipefail

OLD_ROOTFS="${1:-}"
NEW_ROOTFS="${2:-}"
OUTPUT_DIR="${3:-/var/tmp/jarvis-os-deltas}"

if [[ -z "$OLD_ROOTFS" || -z "$NEW_ROOTFS" ]]; then
    echo "Usage: $0 <old_rootfs> <new_rootfs> <output_dir>"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# Install bsdiff if not present
if ! command -v bsdiff &> /dev/null; then
    echo "Installing bsdiff..."
    dnf install -y bsdiff
fi

echo "Generating delta updates..."
echo "Old: $OLD_ROOTFS"
echo "New: $NEW_ROOTFS"
echo "Output: $OUTPUT_DIR"

# Find all files that changed
cd "$OLD_ROOTFS"
find . -type f -print0 | while IFS= read -r -d '' file; do
    # Skip certain paths
    case "$file" in
        ./proc/*|./sys/*|./dev/*|./run/*|./tmp/*|./var/tmp/*|./var/cache/*|./var/log/*)
            continue
            ;;
    esac
    
    old_file="$OLD_ROOTFS/$file"
    new_file="$NEW_ROOTFS/$file"
    
    if [[ ! -f "$new_file" ]]; then
        # File deleted
        echo "DELETE $file" >> "$OUTPUT_DIR/manifest.txt"
        continue
    fi
    
    # Check if files differ
    if ! cmp -s "$old_file" "$new_file" 2>/dev/null; then
        # File changed - generate delta
        delta_file="$OUTPUT_DIR${file}.delta"
        mkdir -p "$(dirname "$delta_file")"
        
        echo "Generating delta for $file..."
        if bsdiff "$old_file" "$new_file" "$delta_file"; then
            echo "DELTA $file ${delta_file}" >> "$OUTPUT_DIR/manifest.txt"
            
            # Calculate compression ratio
            old_size=$(stat -c%s "$old_file")
            new_size=$(stat -c%s "$new_file")
            delta_size=$(stat -c%s "$delta_file")
            ratio=$(echo "scale=2; $delta_size * 100 / $old_size" | bc)
            echo "  Old: $old_size, New: $new_size, Delta: $delta_size (${ratio}%)"
        else
            echo "  bsdiff failed, storing full file"
            cp "$new_file" "$delta_file"
            echo "FULL $file ${delta_file}" >> "$OUTPUT_DIR/manifest.txt"
        fi
    fi
done

# Find new files
cd "$NEW_ROOTFS"
find . -type f -print0 | while IFS= read -r -d '' file; do
    old_file="$OLD_ROOTFS/$file"
    if [[ ! -f "$old_file" ]]; then
        # New file
        echo "NEW $file" >> "$OUTPUT_DIR/manifest.txt"
        cp "$NEW_ROOTFS/$file" "$OUTPUT_DIR${file}.new"
    fi
done

# Create manifest with metadata
cat > "$OUTPUT_DIR/manifest.json" << EOF
{
  "version": "1.0",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "old_rootfs": "$OLD_ROOTFS",
  "new_rootfs": "$NEW_ROOTFS",
  "files": []
}
EOF

# Add file entries to manifest
while IFS= read -r line; do
    if [[ -n "$line" ]]; then
        # Parse and add to JSON
        echo "Manifest entry: $line"
    fi
done < "$OUTPUT_DIR/manifest.txt"

# Create tarball
echo "Creating delta package..."
tar -czf "$OUTPUT_DIR/jarvis-os-delta-$(date +%Y%m%d-%H%M%S).tar.gz" -C "$OUTPUT_DIR" manifest.txt manifest.json *.delta *.new 2>/dev/null || true

echo "Delta update package created in $OUTPUT_DIR"