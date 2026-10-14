# Builds a clean, shareable copy of this project for a public repository (code + configs only, no game data).
#   python scripts\make_release.py --out C:\dev\recomp\GITHUB --status "Boots to the intro, then stops (work in progress)."
#        [--name <codename>] [--blocklist release_blocklist.txt] [--license <file>] [--redact] [--replace] [--no-git]
# What goes in (like a finished project's release): from the LAST COMMIT (git show HEAD:<file>, so half-done edits never
# leak) the files under runtime\ (sources, patches, CMakeLists, build.ps1, package), scripts\, splat\*.yaml, tools\
# get_tools.ps1 and the symbol/config lists; from disk only runtime\assets\ (fonts/icons the build embeds; git ignores
# them). Never: the ROM, anything extracted or generated from it (asm\, RecompiledFuncs\, *.bin, assets\), reference\,
# notes / worklog / rules, logs\, build output, dumps.
# Cleaning: absolute project paths -> relative, C:\Users\<you> -> %USERPROFILE%. Words that must never be published -
# the game's real title (read from the ROM header automatically) plus every line of the blocklist file (company names,
# your user name, other project names...; keep that file OUT of git) - stop the export with a report, or are replaced
# by "[redacted]" with --redact. The blocklist file itself is never exported.
# Output: <out>\<name>-release\ (README.md, LICENSE if given, a fresh git repo with one commit unless --no-git) and the
# report <out>\<name>-release.report.txt NEXT TO it (never inside). --replace overwrites only a folder this script made.
# Generic: no game values. Exit code 0 = exported, 2 = stopped (blocklisted words or unsafe output), 1 = error.
import argparse, datetime, glob, hashlib, os, re, shutil, subprocess, sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))    # --project overrides (testing)
MARKER = '.made_by_make_release'
INCLUDE = [r'^runtime/(src|include|patches|package)/', r'^runtime/(CMakeLists\.txt|build\.ps1|[^/]+\.txt)$',
           r'^scripts/', r'^splat/[^/]+\.ya?ml$', r'^tools/get_tools\.ps1$',
           r'^(symbol_addrs\.txt|config\.toml|symbols(\.splat)?\.toml|n64sym_[^/]*\.txt|known_warnings\.txt)$', r'^rsp/']
NEVER = [r'(^|/)(asm|RecompiledFuncs|reference|logs|dumps|rom|build[^/]*)/', r'\.(z64|n64|v64|bin|eep|sra|fla)$',
         r'(^|/)(NOTES|WORKLOG|CLAUDE|BLUEPRINT|SETUP)[^/]*\.md$', r'__pycache__', r'release_blocklist\.txt$']
DISK_DIRS = ['runtime/assets']          # needed by the build but ignored by git (fonts, icons)
TEXT_EXT = re.compile(r'\.(py|ps1|txt|md|toml|ya?ml|c|cpp|h|hpp|cmake|json|rcss|rml|html|css|cfg|ini|bat|sh|patch|diff|ld|s)$|'
                      r'(^|/)CMakeLists\.txt$', re.I)


def git(*args, binary=False):
    r = subprocess.run(['git', '-C', PROJECT, *args], capture_output=True)
    if r.returncode:
        raise SystemExit(f'git {" ".join(args)} failed: {r.stderr.decode(errors="replace").strip()}')
    return r.stdout if binary else r.stdout.decode('utf-8', errors='replace')


def rom_title():
    roms = sorted(glob.glob(os.path.join(PROJECT, 'rom', '*.z64')))
    if not roms:
        return None, None
    data = open(roms[0], 'rb').read()
    title = data[0x20:0x34].decode('ascii', errors='replace').strip(' \x00')
    return title or None, (hashlib.sha1(data).hexdigest(), len(data))


def main():
    ap = argparse.ArgumentParser(description='Clean public copy of the project (code + configs, no game data).')
    ap.add_argument('--out', required=True, help='parent folder, e.g. C:\\dev\\recomp\\GITHUB')
    ap.add_argument('--name')
    ap.add_argument('--status', required=True, help='one or two sentences for the README: what works, what not')
    ap.add_argument('--blocklist', help='default: release_blocklist.txt in the project folder')
    ap.add_argument('--license', help='license file to copy as LICENSE (the runtime may require a specific one)')
    ap.add_argument('--redact', action='store_true', help='replace blocklisted words instead of stopping')
    ap.add_argument('--replace', action='store_true', help='overwrite an earlier export made by this script')
    ap.add_argument('--no-git', action='store_true')
    ap.add_argument('--project', help='project folder (default: the folder above the scripts folder)')
    a = ap.parse_args()
    global PROJECT
    if a.project:
        PROJECT = os.path.abspath(a.project)

    a.blocklist = a.blocklist or os.path.join(PROJECT, 'release_blocklist.txt')
    a.name = a.name or os.path.basename(PROJECT)
    out_parent = os.path.abspath(a.out)
    dest = os.path.join(out_parent, f'{a.name}-release')
    report_path = dest + '.report.txt'
    if os.path.normcase(dest).startswith(os.path.normcase(PROJECT) + os.sep):
        print('STOP: the export must be outside the project folder.')
        return 2
    if os.path.exists(dest):
        if not (a.replace and os.path.isfile(os.path.join(dest, MARKER))):
            print(f'STOP: {dest} exists. Use --replace (only works for a folder this script made) or another --out.')
            return 2

    # --- blocklist: the file + the ROM title; the user name and project path are cleaned automatically -------------
    words = []
    if os.path.isfile(a.blocklist):
        words += [l.strip() for l in open(a.blocklist, encoding='utf-8') if l.strip() and not l.startswith('#')]
        if os.path.normcase(os.path.abspath(a.blocklist)).startswith(os.path.normcase(PROJECT) + os.sep):
            rel_bl = os.path.relpath(a.blocklist, PROJECT)
            ignored = subprocess.run(['git', '-C', PROJECT, 'check-ignore', '-q', rel_bl]).returncode == 0
            tracked = bool(git('ls-files', '--', rel_bl).strip())
        else:
            ignored = tracked = None            # outside the project: git can't publish it anyway
    else:
        ignored = tracked = None
    title, romhash = rom_title()
    if title:
        words.append(title)
        words += [w for w in re.split(r'\W+', title) if len(w) >= 4]          # also the single title words
    user = os.path.basename(os.path.expanduser('~'))
    words = sorted(set(w for w in words if w), key=len, reverse=True)
    wordrx = re.compile('|'.join(re.escape(w) for w in words), re.I) if words else None

    # --- choose files ----------------------------------------------------------------------------------------------
    tracked_files = [f for f in git('ls-files').splitlines() if f]
    chosen = [f for f in tracked_files if any(re.search(p, f) for p in INCLUDE) and not any(re.search(p, f) for p in NEVER)]
    skipped = [f for f in tracked_files if f not in chosen]
    disk = []
    for d in DISK_DIRS:
        for root, _, names in os.walk(os.path.join(PROJECT, d)):
            for n in names:
                rel = os.path.relpath(os.path.join(root, n), PROJECT).replace('\\', '/')
                if rel not in chosen and not any(re.search(p, rel) for p in NEVER):
                    disk.append(rel)
    modified = [l[3:] for l in git('status', '--porcelain').splitlines() if l[:2].strip() and l[3:] in chosen]

    # --- read + clean ----------------------------------------------------------------------------------------------
    proj_variants = {PROJECT, PROJECT.replace('\\', '/'), PROJECT.replace('\\', '\\\\'),
                     '/' + PROJECT[0].lower() + PROJECT[2:].replace('\\', '/')}
    home = os.path.expanduser('~')
    home_variants = {home, home.replace('\\', '/'), home.replace('\\', '\\\\'),
                     '/' + home[0].lower() + home[2:].replace('\\', '/')}
    files, hits, cleaned = {}, [], []
    for rel in chosen + disk:
        data = git('show', f'HEAD:{rel}', binary=True) if rel in chosen else open(os.path.join(PROJECT, rel), 'rb').read()
        if TEXT_EXT.search(rel):
            text = data.decode('utf-8', errors='surrogateescape')
            before = text
            for v in sorted(proj_variants, key=len, reverse=True):
                text = re.sub(re.escape(v) + r'[\\/]?', '', text, flags=re.I) if v else text
            for v in sorted(home_variants, key=len, reverse=True):
                text = re.sub(re.escape(v), '%USERPROFILE%', text, flags=re.I)
            if text != before:
                cleaned.append(rel)
            for n, line in enumerate(text.splitlines(), 1):
                for rx, why in ((wordrx, 'blocklisted'), (re.compile(rf'\b{re.escape(user)}\b', re.I), 'user name'),
                                (re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+'), 'e-mail address')):
                    if rx and rx.search(line):
                        hits.append((rel, n, why, line.strip()[:160]))
            if a.redact and wordrx:
                text = wordrx.sub('[redacted]', text)
            data = text.encode('utf-8', errors='surrogateescape')
        elif wordrx and wordrx.search(data.decode('latin-1')):
            hits.append((rel, 0, 'blocklisted (binary file)', ''))
        files[rel] = data

    for why, rx in (('blocklisted', wordrx), ('user name', re.compile(rf'\b{re.escape(user)}\b', re.I))):
        if rx and rx.search(a.status):                   # the README text is written by hand: check it too
            hits.append(('--status (README)', 0, why, a.status[:160]))
    blocking = [h for h in hits if not (a.redact and h[2] == 'blocklisted' and h[0] != '--status (README)')]
    rep = [f'make_release {datetime.datetime.now():%Y-%m-%d %H:%M}  project {a.name}  commit {git("rev-parse", "--short", "HEAD").strip()}',
           f'export: {dest}', f'included: {len(chosen)} files from the last commit + {len(disk)} from disk ({", ".join(DISK_DIRS)})',
           f'cleaned paths in {len(cleaned)} files: {", ".join(cleaned) or "-"}',
           f'blocklist: {len(words)} words ({"file " + a.blocklist if os.path.isfile(a.blocklist) else "no file"}'
           f'{"; ROM title added" if title else "; no ROM found, title not checked"})']
    if tracked:
        rep.append('WARNING: the blocklist file is TRACKED by git - remove it from git (it names what must stay private).')
    elif ignored is False:
        rep.append('WARNING: the blocklist file is not in .gitignore - add it.')
    if modified:
        rep.append(f'NOTE: uncommitted changes NOT exported (last commit used): {", ".join(modified)}')
    rep.append(f'not exported (tracked but not on the list): {len(skipped)} files, e.g. ' + ', '.join(skipped[:12]))
    rep.append(f'findings: {len(hits)} ({len(blocking)} blocking)')
    rep += [f'  {f}:{n}  [{why}]  {line}' for f, n, why, line in hits[:200]]
    os.makedirs(out_parent, exist_ok=True)
    if blocking:
        rep.append('STOPPED: nothing exported. Fix the sources in the project (then commit), or use --redact for the '
                   'blocklisted words. The user name / e-mail findings must be fixed in the project.')
        open(report_path, 'w', encoding='utf-8').write('\n'.join(rep) + '\n')
        print('\n'.join(rep[:8] + [f'  {f}:{n} [{w}]' for f, n, w, _ in blocking[:15]] + [rep[-1], f'report: {report_path}']))
        return 2

    # --- write -----------------------------------------------------------------------------------------------------
    if os.path.exists(dest):
        def writable(func, path, _):            # git marks its object files read-only on Windows
            os.chmod(path, 0o666)
            func(path)
        shutil.rmtree(dest, onexc=writable)
    for rel, data in files.items():
        p = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(data)
    open(os.path.join(dest, MARKER), 'w').write('made by scripts/make_release.py\n')
    if a.license:
        shutil.copyfile(a.license, os.path.join(dest, 'LICENSE'))
    else:
        rep.append('WARNING: no --license given: without a license nobody may reuse the code. The runtime part usually '
                   'inherits the license of the project it was copied from - check before publishing.')
    hashline = (f'SHA-1 `{romhash[0]}`, {romhash[1] // (1024 * 1024)} MB, big-endian `.z64`' if romhash
                else 'see the project notes')
    readme = f'''# {a.name}

> [!WARNING]
> **Made with AI.** It has not been reviewed by experienced developers, so expect mistakes.

A static recompilation of an N64 game into a native Windows program, built with
[N64Recomp](https://github.com/N64Recomp/N64Recomp): the game's MIPS code is translated to C ahead of time and compiled
for the PC. Graphics by [RT64](https://github.com/rt64/rt64), runtime by
[N64ModernRuntime](https://github.com/N64Recomp/N64ModernRuntime), launcher and menus by
[RecompFrontend](https://github.com/N64Recomp/RecompFrontend).

This is a hobby and learning project, shared so others can learn from it.

**No game data is included.** This repository contains no ROM and no game code. You need your own legally obtained copy
of the game; it is recognised by its hash.

## Status

{a.status}

## Building from source

1. Windows 10/11 x64, Visual Studio with "Desktop development with C++", Python 3, Git, LLVM/clang.
2. `tools\\get_tools.ps1` clones the pinned tool versions into `tools\\`.
3. Put your ROM into `rom\\` ({hashline}).
4. Run the pipeline (`scripts\\rebuild.ps1`), then build the runtime (`runtime\\build.ps1`).

Exported {datetime.date.today():%Y-%m-%d} from commit `{git("rev-parse", "--short", "HEAD").strip()}`.
'''
    open(os.path.join(dest, 'README.md'), 'w', encoding='utf-8').write(readme)
    if not a.no_git:
        subprocess.run(['git', '-C', dest, 'init', '-q'], check=True, capture_output=True)
        with open(os.path.join(dest, '.git', 'info', 'exclude'), 'a') as fx:
            fx.write(MARKER + '\n')                      # the marker stays local, never in the published repo
        for cmd in (['add', '-A'], ['commit', '-q', '-m', f'{a.name}: release export']):
            subprocess.run(['git', '-C', dest, *cmd], check=True, capture_output=True)
        rep.append('git: fresh repository with one commit (no history from the project). Push it yourself.')
    rep.append(f'EXPORTED: {len(files)} files + README.md{" + LICENSE" if a.license else ""} -> {dest}')
    open(report_path, 'w', encoding='utf-8').write('\n'.join(rep) + '\n')
    print('\n'.join(rep[:7] + rep[-3:]) + f'\nreport: {report_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
