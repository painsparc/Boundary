import os
import sys

# Text-based file extensions to include
TEXT_EXTENSIONS = {
    '.py', '.dart', '.js', '.ts', '.jsx', '.tsx',
    '.html', '.css', '.scss', '.sass', '.less',
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.env',
    '.md', '.txt', '.rst', '.xml', '.svg',
    '.sh', '.bash', '.zsh', '.bat', '.ps1',
    '.kt', '.kts', '.java', '.swift', '.go', '.rs',
    '.c', '.cpp', '.h', '.hpp', '.cs', '.rb', '.php',
    '.sql', '.graphql', '.proto', '.gradle', '.cmake',
    '.dockerfile', '.gitignore', '.editorconfig',
    '.lock', '.properties', '.plist',
}

# Folders to always skip
SKIP_DIRS = {
    '.git', '.idea', '.vscode', '__pycache__', 'node_modules',
    '.dart_tool', '.flutter-plugins', 'build', 'dist', '.next',
    'venv', '.venv', 'env', '.env', '.gradle', '.pub-cache',
    'ios', 'android', 'windows', 'linux', 'macos', 'web',
}

script_name = os.path.basename(__file__)
output_filename = 'project_context.txt'
base_dir = os.path.dirname(os.path.abspath(__file__))

collected = []
skipped_binary = []

for root, dirs, files in os.walk(base_dir):
    # Prune skip dirs in-place
    dirs[:] = [d for d in sorted(dirs) if d not in SKIP_DIRS and not d.startswith('.')]
    
    for fname in sorted(files):
        if fname == script_name or fname == output_filename:
            continue
        
        _, ext = os.path.splitext(fname.lower())
        # Also include files with no extension but known names
        no_ext_whitelist = {'dockerfile', 'makefile', 'rakefile', 'procfile', 'gemfile', 'podfile'}
        
        if ext not in TEXT_EXTENSIONS and fname.lower() not in no_ext_whitelist:
            skipped_binary.append(os.path.relpath(os.path.join(root, fname), base_dir))
            continue
        
        full_path = os.path.join(root, fname)
        rel_path = os.path.relpath(full_path, base_dir)
        
        try:
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            collected.append((rel_path, content))
        except Exception as e:
            skipped_binary.append(f"{rel_path} (read error: {e})")

# Write output
output_path = os.path.join(base_dir, output_filename)
with open(output_path, 'w', encoding='utf-8') as out:
    out.write(f"PROJECT CONTEXT DUMP\n")
    out.write(f"Base directory: {base_dir}\n")
    out.write(f"Total files included: {len(collected)}\n")
    out.write("=" * 80 + "\n\n")
    
    for rel_path, content in collected:
        out.write(f"{'=' * 80}\n")
        out.write(f"FILE: {rel_path}\n")
        out.write(f"{'=' * 80}\n")
        out.write(content)
        if not content.endswith('\n'):
            out.write('\n')
        out.write('\n')
    
    if skipped_binary:
        out.write(f"\n{'=' * 80}\n")
        out.write("SKIPPED FILES (binary/unsupported):\n")
        out.write(f"{'=' * 80}\n")
        for s in skipped_binary:
            out.write(f"  - {s}\n")

print(f"Done! {len(collected)} files written to: {output_path}")
if skipped_binary:
    print(f"Skipped {len(skipped_binary)} binary/unsupported files (listed at bottom of output).")
