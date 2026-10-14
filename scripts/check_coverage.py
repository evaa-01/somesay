"""Compare our symbols.toml function names with N64ModernRuntime coverage."""
import re, glob, os

base = os.path.join("tools", "N64ModernRuntime", "librecomp", "src")
runtime_funcs = set()

for path in glob.glob(os.path.join(base, "*.cpp")):
    with open(path) as f:
        for line in f:
            m = re.search(r'extern\s+"C"\s+\w+\s+(\w+)_recomp', line)
            if m:
                runtime_funcs.add(m.group(1))

# Read our symbols.toml names
with open("symbols.toml") as f:
    toml_content = f.read()
our_funcs = set(re.findall(r'name\s*=\s*"([^"]+)"', toml_content))

missing = []
for func in sorted(our_funcs):
    if func.startswith("func_"):
        continue
    if func not in runtime_funcs:
        missing.append(func)

print(f"Functions in our ROM but NOT provided by N64ModernRuntime ({len(missing)}):")
for m in missing:
    print(f"  {m}")

# Also show which are actually covered
covered = [f for f in sorted(our_funcs) if not f.startswith("func_") and f in runtime_funcs]
print(f"\nCovered libultra functions ({len(covered)}):")
for c in covered:
    print(f"  {c}")
