import zipfile, hashlib, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

orig  = 'powerbi/mf_analytics_dashboard.bak.pbix'
build = 'powerbi/mf_analytics_dashboard_p1.pbix'

with zipfile.ZipFile(orig, 'r') as o, zipfile.ZipFile(build, 'r') as b:
    oi = {i.filename: i for i in o.infolist()}
    bi = {i.filename: i for i in b.infolist()}

    # DataModel integrity
    dm_o = o.read('DataModel'); dm_b = b.read('DataModel')
    print(f"DataModel match: {dm_o == dm_b}  ({len(dm_o):,} bytes, md5 {hashlib.md5(dm_b).hexdigest()[:12]})")
    print(f"DataModel compress_type: orig={oi['DataModel'].compress_type} build={bi['DataModel'].compress_type}")
    print(f"DataModel external_attr: orig={oi['DataModel'].external_attr} build={bi['DataModel'].external_attr}")

    only_o = set(oi) - set(bi)
    only_b = set(bi) - set(oi)
    print(f"\nEntry count: orig={len(oi)} build={len(bi)}")
    print(f"Only in orig (deleted): {len(only_o)}")
    print(f"Only in build (added):  {len(only_b)}")

    # Verify all shared NON-visual files are byte-identical
    bad = []
    for fn in oi:
        if fn in bi and 'visuals/' not in fn:
            if o.read(fn) != b.read(fn):
                bad.append(fn)
    print(f"\nShared non-visual files with content diff: {len(bad)}")
    for f in bad: print(f"  CHANGED: {f}")

    # Last entry
    print(f"\nLast entry orig : {[i.filename for i in o.infolist()][-1]}")
    print(f"Last entry build: {[i.filename for i in b.infolist()][-1]}")

    # Test that the build is a readable, valid zip
    bad_crc = b.testzip()
    print(f"\nZIP CRC test (None=all ok): {bad_crc}")
